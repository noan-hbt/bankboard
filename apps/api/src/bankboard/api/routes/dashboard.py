from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from bankboard.api.deps import DB, CurrentUser
from bankboard.api.schemas import GoalIn, GoalOut, LayoutIn, PreferencesIn
from bankboard.events.bus import publish
from bankboard.models import Account, DashboardLayout, Goal, UserPreferences
from bankboard.modules.registry import all_modules, is_enabled, widget_catalog

router = APIRouter(prefix="/api", tags=["dashboard"])

DEFAULT_LAYOUT: list[dict[str, Any]] = [
    {"i": "financial_state", "widget": "financial_state", "x": 0, "y": 0, "w": 4, "h": 4},
    {"i": "safe_to_spend", "widget": "safe_to_spend", "x": 4, "y": 0, "w": 4, "h": 4},
    {"i": "attention", "widget": "attention", "x": 8, "y": 0, "w": 4, "h": 4},
    {"i": "wealth_trajectory", "widget": "wealth_trajectory", "x": 0, "y": 4, "w": 8, "h": 5},
    {"i": "opportunities", "widget": "opportunities", "x": 8, "y": 4, "w": 4, "h": 5},
    {"i": "what_changed", "widget": "what_changed", "x": 0, "y": 9, "w": 6, "h": 5},
    {"i": "next_30_days", "widget": "next_30_days", "x": 6, "y": 9, "w": 6, "h": 5},
    {"i": "ask", "widget": "ask", "x": 0, "y": 14, "w": 8, "h": 4},
    {"i": "feed", "widget": "feed", "x": 8, "y": 14, "w": 4, "h": 4},
]


def _prefs(db: DB, user_id: uuid.UUID) -> UserPreferences:
    p = db.get(UserPreferences, user_id)
    if p is None:
        p = UserPreferences(user_id=user_id, modules={}, settings={}, opportunity_rate=Decimal("0.05"),
                            notification_min_level="important")
        db.add(p)
        db.flush()
    return p


@router.get("/modules")
def modules(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    prefs = _prefs(db, user.id)
    return [{"key": m.key, "title": m.title, "tier": m.tier, "description": m.description,
             "enabled": is_enabled(m, prefs), "widgets": [w.id for w in m.widgets]} for m in all_modules()]


@router.get("/widgets")
def widgets(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [{"id": w.id, "module": m.key, "title": w.title, "kind": w.kind, "endpoint": w.endpoint,
             "description": w.description, "w": w.w, "h": w.h, "min_w": w.min_w, "min_h": w.min_h,
             "config": dict(w.config)} for m, w in widget_catalog(_prefs(db, user.id))]


@router.get("/dashboard/layout")
def get_layout(user: CurrentUser, db: DB, name: str = "default") -> dict[str, Any]:
    row = db.scalars(select(DashboardLayout).where(DashboardLayout.user_id == user.id,
                                                   DashboardLayout.name == name)).first()
    return {"name": name, "items": row.layout if row else DEFAULT_LAYOUT, "is_default": row is None}


@router.put("/dashboard/layout")
def put_layout(body: LayoutIn, user: CurrentUser, db: DB, name: str = "default") -> dict[str, Any]:
    known = {w["id"] for w in widgets(user, db)}
    unknown = {i.widget for i in body.items} - known
    if unknown:
        raise HTTPException(422, f"Unknown widgets: {sorted(unknown)}")
    row = db.scalars(select(DashboardLayout).where(DashboardLayout.user_id == user.id,
                                                   DashboardLayout.name == name)).first()
    items = [i.model_dump() for i in body.items]
    if row is None:
        db.add(DashboardLayout(id=uuid.uuid4(), user_id=user.id, name=name, layout=items))
    else:
        row.layout = items
    return {"name": name, "items": items, "is_default": False}


@router.delete("/dashboard/layout", status_code=204)
def reset_layout(user: CurrentUser, db: DB, name: str = "default") -> None:
    row = db.scalars(select(DashboardLayout).where(DashboardLayout.user_id == user.id,
                                                   DashboardLayout.name == name)).first()
    if row:
        db.delete(row)


@router.get("/preferences")
def get_preferences(user: CurrentUser, db: DB) -> dict[str, Any]:
    p = _prefs(db, user.id)
    return {"min_buffer": p.min_buffer, "opportunity_rate": p.opportunity_rate, "modules": p.modules,
            "notification_min_level": p.notification_min_level}


@router.put("/preferences")
def put_preferences(body: PreferencesIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    p = _prefs(db, user.id)
    data = body.model_dump(exclude_unset=True)
    if "modules" in data and data["modules"] is not None:
        p.modules = {**p.modules, **data.pop("modules")}
    for k, v in data.items():
        setattr(p, k, v)
    return get_preferences(user, db)


@router.get("/goals", response_model=list[GoalOut])
def goals(user: CurrentUser, db: DB) -> list[GoalOut]:
    return [GoalOut.model_validate(g, from_attributes=True)
            for g in db.scalars(select(Goal).where(Goal.user_id == user.id).order_by(Goal.priority))]


@router.post("/goals", response_model=GoalOut, status_code=201)
def create_goal(body: GoalIn, user: CurrentUser, db: DB) -> GoalOut:
    if body.linked_account_id:
        acc = db.get(Account, body.linked_account_id)
        if acc is None or acc.user_id != user.id:
            raise HTTPException(422, "Unknown account")
    g = Goal(id=uuid.uuid4(), user_id=user.id, status="active", **body.model_dump())
    db.add(g)
    db.flush()
    publish(db, user.id, "goal.updated", {"goal_id": str(g.id)})
    return GoalOut.model_validate(g, from_attributes=True)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: uuid.UUID, user: CurrentUser, db: DB) -> None:
    g = db.get(Goal, goal_id)
    if g is None or g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(g)
