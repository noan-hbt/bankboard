"""Job runner: `python -m bankboard.jobs <command>`.

Commands are thin wrappers around services, so they can be driven by cron/systemd or a worker
without touching business code.
"""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from bankboard.core.db import session_scope
from bankboard.core.logging import configure_logging
from bankboard.events.bus import dispatch_pending
from bankboard.models import BankConnection, User
from bankboard.pipeline.reference_data import ensure_reference_data
from bankboard.providers.base import ProviderError
from bankboard.services.analysis import refresh_user
from bankboard.services.sync import sync_connection

log = logging.getLogger("bankboard.jobs")

SYNC_EVERY = timedelta(hours=6)
SNAPSHOT_HOUR_UTC = 2


def sync_all() -> int:
    with session_scope() as s:
        ids = list(s.scalars(select(BankConnection.id).where(BankConnection.status == "active")))
    ok = 0
    for cid in ids:
        try:
            with session_scope() as s:
                sync_connection(s, cid)
            ok += 1
        except ProviderError as exc:
            log.warning("sync failed connection=%s kind=%s", cid, exc.kind)
    with session_scope() as s:
        dispatch_pending(s)
    return ok


def snapshot_all() -> int:
    with session_scope() as s:
        ids = list(s.scalars(select(User.id)))
    for uid in ids:
        with session_scope() as s:
            refresh_user(s, uid, backfill_days=7)
    return len(ids)


def scheduler() -> None:
    last_sync = datetime.min.replace(tzinfo=UTC)
    last_snapshot_day = None
    while True:
        now = datetime.now(UTC)
        if now - last_sync >= SYNC_EVERY:
            log.info("scheduled sync: %d connections", sync_all())
            last_sync = now
        if now.hour >= SNAPSHOT_HOUR_UTC and last_snapshot_day != now.date():
            log.info("daily snapshot: %d users", snapshot_all())
            last_snapshot_day = now.date()
        with session_scope() as s:
            dispatch_pending(s)
        time.sleep(60)


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser(prog="bankboard.jobs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-all")
    sub.add_parser("snapshot")
    sub.add_parser("dispatch-events")
    sub.add_parser("seed-reference")
    sub.add_parser("scheduler")
    rp = sub.add_parser("replay-pipeline")
    rp.add_argument("--user", required=True, type=uuid.UUID)
    dm = sub.add_parser("seed-demo", help="create a demo user with 12 months of synthetic data")
    dm.add_argument("--email", default="demo@bankboard.local")
    dm.add_argument("--password", default="demo-password")
    args = p.parse_args()

    if args.cmd == "sync-all":
        print(f"synced {sync_all()} connections")
    elif args.cmd == "snapshot":
        print(f"refreshed {snapshot_all()} users")
    elif args.cmd == "dispatch-events":
        with session_scope() as s:
            print(f"processed {dispatch_pending(s)} events")
    elif args.cmd == "seed-reference":
        with session_scope() as s:
            ensure_reference_data(s)
    elif args.cmd == "replay-pipeline":
        with session_scope() as s:
            print(refresh_user(s, args.user))
    elif args.cmd == "seed-demo":
        from bankboard.demo.seed import seed_demo_user

        with session_scope() as s:
            user = seed_demo_user(s, email=args.email, password=args.password)
            print(f"demo user {user.email} ready")
    elif args.cmd == "scheduler":
        scheduler()


if __name__ == "__main__":
    main()
