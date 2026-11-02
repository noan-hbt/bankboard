"""Domain event outbox + in-process dispatcher.

`publish` writes the event in the caller's transaction (outbox pattern). `dispatch_pending`
delivers events to registered handlers; handlers must be idempotent. Swapping the in-process
dispatcher for a queue worker does not change publishers or handlers.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.core.clock import utcnow
from bankboard.models import DomainEvent

log = logging.getLogger(__name__)

Handler = Callable[[Session, DomainEvent], None]

EVENT_TYPES = frozenset({
    "transaction.created", "transaction.updated", "bank.sync.completed", "income.detected",
    "salary.received", "goal.updated", "month.closed", "financial_state.changed", "anomaly.detected",
    "pipeline.completed",
})

_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_type: str, handler: Handler) -> None:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type {event_type}")
    if handler not in _handlers[event_type]:
        _handlers[event_type].append(handler)


def handlers_for(event_type: str) -> list[Handler]:
    return list(_handlers.get(event_type, []))


def publish(session: Session, user_id: uuid.UUID | None, event_type: str,
            payload: dict[str, Any] | None = None) -> DomainEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type {event_type}")
    event = DomainEvent(user_id=user_id, type=event_type, payload=payload or {}, occurred_at=utcnow(),
                        attempts=0)
    session.add(event)
    return event


MAX_ATTEMPTS = 5


def dispatch_pending(session: Session, *, limit: int = 100, max_rounds: int = 10) -> int:
    """Process unprocessed events (including those emitted by handlers). Returns count processed."""
    from bankboard.modules.registry import ensure_modules_loaded

    ensure_modules_loaded()
    processed = 0
    for _ in range(max_rounds):
        events = list(session.scalars(
            select(DomainEvent)
            .where(DomainEvent.processed_at.is_(None), DomainEvent.attempts < MAX_ATTEMPTS)
            .order_by(DomainEvent.id).limit(limit).with_for_update(skip_locked=True)
        ))
        if not events:
            break
        for event in events:
            event.attempts += 1
            try:
                with session.begin_nested():
                    for handler in handlers_for(event.type):
                        handler(session, event)
                event.processed_at = utcnow()
                event.last_error = None
            except Exception as exc:  # isolate failing handlers
                log.exception("event handler failed type=%s id=%s", event.type, event.id)
                event.last_error = type(exc).__name__
            processed += 1
        session.commit()
    return processed
