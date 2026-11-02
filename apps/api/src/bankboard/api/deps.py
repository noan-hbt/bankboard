from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from bankboard.core.clock import today
from bankboard.core.db import get_db
from bankboard.models import User
from bankboard.services.auth import user_for_token
from bankboard.services.context import FinancialContext, build_context

SESSION_COOKIE = "bb_session"

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, bb_session: Annotated[str | None, Cookie()] = None) -> User:
    user = user_for_token(db, bb_session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def today_dep() -> date:
    return today()


Today = Annotated[date, Depends(today_dep)]


def financial_context(db: DB, user: CurrentUser, t: Today) -> FinancialContext:
    return build_context(db, user.id, t)


Ctx = Annotated[FinancialContext, Depends(financial_context)]
