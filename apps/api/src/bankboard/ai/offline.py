"""Offline provider: deterministic intent routing + templated answers. No network, no model.

Used when no LLM is configured, and in tests. Every number is copied from tool outputs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from bankboard.ai.base import ChatTurn, LLMAnswer, ToolCall, ToolSpec


def _n(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return s[:-3] if s.endswith(",00") else s


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


class OfflineProvider:
    name = "offline"

    def answer(self, *, system: str, history: list[ChatTurn], question: str, tools: list[ToolSpec]) -> LLMAnswer:
        registry = {t.name: t for t in tools}
        calls: list[ToolCall] = []

        def call(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            out = registry[name].handler(args or {})
            calls.append(ToolCall(name=name, input=args or {}, output=out))
            return out

        q = _plain(question)
        if re.search(r"combien.*(depenser|claquer)|safe|puis-je depenser|week-end|weekend", q):
            out = call("get_safe_to_spend")
            hz = {h["horizon"]: h for h in out["horizons"]}
            key = "week" if "semaine" in q or "week" in q else "until_next_income"
            h = hz[key]
            lines = [f"Tu peux dépenser environ {_n(h['safe_to_spend'])} € jusqu'au {h['until']} "
                     f"(≈ {_n(h['per_day'])} €/jour) sans entamer ton buffer."]
            lines += [f"• {b['label']} : {_n(b['amount'])} €" for b in h["breakdown"]]
            text = "\n".join(lines)
        elif re.search(r"pourquoi|change|plus que|augment|hausse|depense plus", q):
            out = call("compare_periods", {"preset": "mtd" if "mois" in q else "30d"})
            drivers = [d for d in out["category_drivers"] if d["delta"] != 0][:4]
            text = out["headline"] + "\n" + "\n".join(
                f"• {d['label']} : {'+' if d['delta'] > 0 else ''}{_n(d['delta'])} € "
                f"({_n(d['previous'])} → {_n(d['current'])} €)" for d in drivers)
        elif re.search(r"abonnement|recurr|prelevement", q):
            out = call("get_recurring")
            subs = [p for p in out["patterns"] if p["is_subscription"]]
            text = f"{len(subs)} abonnements détectés :\n" + "\n".join(
                f"• {p['label']} : {_n(-p['amount'])} € ({p['cadence']})" for p in subs)
        elif m := re.search(r"combien.*(?:chez|pour|avec|sur|a)\s+([\w'.-]+)", q):
            term = m.group(1)
            out = call("query_transactions", {"search": term})
            text = (f"{out['count']} transactions correspondant à « {term} » sur la période "
                    f"{out['period']['start']} → {out['period']['end']} : {_n(out['total_spending'])} € dépensés.")
        elif re.search(r"prevu|a venir|prochain|bientot", q):
            out = call("get_predictions", {"days": 30})
            text = "Événements attendus sur 30 jours :\n" + "\n".join(
                f"• {e['date']} {e['label']} {_n(e['amount'])} € ({e['confidence'] * 100:.0f} %)"
                for e in out["events"][:10])
        else:
            out = call("get_financial_state")
            text = (f"Patrimoine suivi : {_n(out['net_worth'])} €, dont {_n(out['spending_cash'])} € sur tes comptes "
                    f"courants. Sur 30 jours : {_n(out['last_30_days']['income'])} € de revenus, "
                    f"{_n(out['last_30_days']['expenses'])} € de dépenses. Financial State : "
                    f"{_n(out['financial_state_score'])}/100 ({out['grade']}).")
        return LLMAnswer(text=text, tool_calls=calls, provider=self.name)
