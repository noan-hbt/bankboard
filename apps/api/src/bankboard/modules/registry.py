"""Module registry: modules declare widgets, detectors, event handlers and routes.

Adding a module = one new package calling `register_module(...)` and one import in `builtin.py`.
The dashboard renders widgets generically from this catalog.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from bankboard.detectors.base import Detector

if TYPE_CHECKING:
    from fastapi import APIRouter
    from sqlalchemy.orm import Session

    from bankboard.models import DomainEvent, UserPreferences

WidgetKind = Literal["metric", "breakdown", "timeline", "series", "list", "insights", "feed", "score", "ask",
                     "calendar"]
Tier = Literal["P0", "P1", "P2", "P3"]


@dataclass(frozen=True)
class WidgetSpec:
    id: str
    title: str
    kind: WidgetKind
    endpoint: str
    description: str = ""
    w: int = 4
    h: int = 4
    min_w: int = 2
    min_h: int = 2
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Module:
    key: str
    title: str
    tier: Tier
    description: str
    widgets: Sequence[WidgetSpec] = ()
    detectors: Sequence[Detector] = ()
    event_handlers: Mapping[str, Sequence[Callable[[Session, DomainEvent], None]]] = field(default_factory=dict)
    router_factory: Callable[[], APIRouter] | None = None
    enabled_by_default: bool = True


_MODULES: dict[str, Module] = {}
_lock = threading.Lock()
_loaded = False


def register_module(module: Module) -> None:
    from bankboard.events.bus import subscribe

    if module.key in _MODULES:
        return
    _MODULES[module.key] = module
    for event_type, handlers in module.event_handlers.items():
        for h in handlers:
            subscribe(event_type, h)


def ensure_modules_loaded() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        import bankboard.modules.builtin  # noqa: F401  (registers modules on import)

        _loaded = True


def all_modules() -> list[Module]:
    ensure_modules_loaded()
    return list(_MODULES.values())


def is_enabled(module: Module, prefs: UserPreferences | None) -> bool:
    if prefs and module.key in prefs.modules:
        return bool(prefs.modules[module.key])
    return module.enabled_by_default


def enabled_modules(prefs: UserPreferences | None) -> list[Module]:
    return [m for m in all_modules() if is_enabled(m, prefs)]


def widget_catalog(prefs: UserPreferences | None) -> list[tuple[Module, WidgetSpec]]:
    return [(m, w) for m in enabled_modules(prefs) for w in m.widgets]
