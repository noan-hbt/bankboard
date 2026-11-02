from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from bankboard.api.deps import DB, SESSION_COOKIE, CurrentUser
from bankboard.api.schemas import LoginIn, RegisterIn, UserOut
from bankboard.core.config import get_settings
from bankboard.services import auth as auth_service

router = APIRouter(prefix="/api", tags=["auth"])


def _user_out(u: object) -> UserOut:
    return UserOut.model_validate(u, from_attributes=True)


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.is_production, samesite="lax",
                        max_age=s.session_ttl_days * 86400, path="/")


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, db: DB, request: Request, response: Response) -> UserOut:
    try:
        user = auth_service.register(db, email=body.email, password=body.password, display_name=body.display_name)
        _, token = auth_service.login(db, email=body.email, password=body.password,
                                      user_agent=request.headers.get("user-agent"))
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _set_cookie(response, token)
    return _user_out(user)


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, db: DB, request: Request, response: Response) -> UserOut:
    try:
        user, token = auth_service.login(db, email=body.email, password=body.password,
                                         user_agent=request.headers.get("user-agent"),
                                         ip=request.client.host if request.client else None)
    except auth_service.AuthError as exc:
        db.commit()  # keep the failed-login audit row
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    _set_cookie(response, token)
    return _user_out(user)


@router.post("/auth/logout", status_code=204)
def logout(db: DB, response: Response, bb_session: Annotated[str | None, Cookie()] = None) -> None:
    auth_service.logout(db, bb_session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.delete("/me", status_code=204)
def delete_me(user: CurrentUser, db: DB, response: Response) -> None:
    auth_service.delete_all_data(db, user)
    response.delete_cookie(SESSION_COOKIE, path="/")
