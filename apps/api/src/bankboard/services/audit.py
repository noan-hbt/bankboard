from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from sqlalchemy.orm import Session

from bankboard.models import AuditLog


def audit(session: Session, user_id: uuid.UUID | None, action: str, *, target: str | None = None,
          metadata: dict[str, Any] | None = None, ip: str | None = None) -> None:
    """Record a security-relevant action. Never pass financial values in metadata."""
    try:
        ip = str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        ip = None
    session.add(AuditLog(user_id=user_id, action=action, target=target, metadata_=metadata or {}, ip=ip))
