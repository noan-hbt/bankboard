"""Provider registry: maps provider keys to factories."""

from __future__ import annotations

from collections.abc import Callable

from bankboard.providers.base import BankingProvider, ProviderError

_FACTORIES: dict[str, Callable[[], BankingProvider]] = {}


def register_provider(key: str, factory: Callable[[], BankingProvider]) -> None:
    _FACTORIES[key] = factory


def get_provider(key: str) -> BankingProvider:
    _ensure_builtin()
    try:
        return _FACTORIES[key]()
    except KeyError as exc:
        raise ProviderError("config", f"Unknown banking provider '{key}'") from exc


def available_providers() -> list[str]:
    _ensure_builtin()
    return sorted(_FACTORIES)


def _ensure_builtin() -> None:
    if _FACTORIES:
        return
    from bankboard.providers.demo.provider import DemoProvider
    from bankboard.providers.enable_banking.provider import EnableBankingProvider

    register_provider(EnableBankingProvider.key, EnableBankingProvider.from_settings)
    register_provider(DemoProvider.key, DemoProvider)
