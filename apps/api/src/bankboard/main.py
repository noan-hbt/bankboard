"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bankboard import __version__
from bankboard.api.routes import analytics, ask, auth, bank, command, dashboard, ledger
from bankboard.api.security import OriginCheckMiddleware
from bankboard.core.config import get_settings
from bankboard.core.logging import configure_logging
from bankboard.modules.registry import all_modules


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.app_env != "test":
        configure_logging()
    app = FastAPI(title="Bankboard — Personal Finance OS", version=__version__)
    origins = [*settings.allowed_origins, settings.frontend_url, settings.app_base_url]
    app.add_middleware(OriginCheckMiddleware, allowed_origins=origins)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    for r in (auth.router, bank.router, ledger.router, analytics.router, command.router, dashboard.router,
              ask.router):
        app.include_router(r)
    for module in all_modules():
        if module.router_factory:
            app.include_router(module.router_factory())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
