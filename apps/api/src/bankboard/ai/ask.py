"""Ask Your Money service: provider selection, prompt, guardrail, persistence."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.ai.base import ChatTurn, LLMAnswer, LLMProvider, unverified_numbers
from bankboard.ai.offline import OfflineProvider
from bankboard.ai.tools import build_tools
from bankboard.core.config import get_settings
from bankboard.models import AdvisorConversation, AdvisorMessage
from bankboard.services.context import FinancialContext

SYSTEM_PROMPT = """Tu es le conseiller financier personnel intégré à Bankboard.
Règles absolues :
- Tu ne calcules jamais toi-même un montant, un total, une moyenne ou un pourcentage. Tous les chiffres que tu
  cites doivent provenir textuellement des résultats des outils. Si un chiffre manque, appelle un outil ; si
  aucun outil ne le fournit, dis-le.
- Cite les montants en euros, au format français.
- Si data_confidence < 0.8, signale que les données sont incomplètes et nuance tes conclusions.
- Sois bref : réponse directe d'abord, puis 2 à 5 puces d'explication, puis une action concrète si pertinent.
- Tu ne déclenches jamais de mouvement d'argent et tu ne présentes pas une projection comme une certitude.
Date du jour : {today}."""


def get_llm_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "openrouter" and s.openrouter_api_key.get_secret_value():
        from bankboard.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(api_key=s.openrouter_api_key.get_secret_value(), model=s.openrouter_model,
                                  app_url=s.frontend_url)
    return OfflineProvider()


def ask(session: Session, ctx: FinancialContext, question: str, *, conversation_id: uuid.UUID | None = None,
        provider: LLMProvider | None = None) -> tuple[uuid.UUID, LLMAnswer]:
    provider = provider or get_llm_provider()
    conv = session.get(AdvisorConversation, conversation_id) if conversation_id else None
    if conv is None or conv.user_id != ctx.user.id:
        conv = AdvisorConversation(id=uuid.uuid4(), user_id=ctx.user.id, title=question[:80])
        session.add(conv)
        session.flush()
    history = [ChatTurn(m.role, m.content) for m in session.scalars(
        select(AdvisorMessage).where(AdvisorMessage.conversation_id == conv.id,
                                     AdvisorMessage.role.in_(["user", "assistant"]))
        .order_by(AdvisorMessage.created_at))][-10:]
    try:
        answer = provider.answer(system=SYSTEM_PROMPT.format(today=ctx.today.isoformat()), history=history,
                                 question=question, tools=build_tools(session, ctx))
    except Exception as exc:  # LLM outage: fall back to the deterministic offline answer
        from bankboard.ai.openrouter_provider import LLMError

        if not isinstance(exc, LLMError):
            raise
        answer = OfflineProvider().answer(system="", history=history, question=question,
                                          tools=build_tools(session, ctx))
        answer.provider = "offline (fallback)"
    answer.unverified_numbers = unverified_numbers(answer.text, answer.tool_calls, question)
    session.add(AdvisorMessage(id=uuid.uuid4(), conversation_id=conv.id, role="user", content=question))
    session.add(AdvisorMessage(id=uuid.uuid4(), conversation_id=conv.id, role="assistant", content=answer.text,
                               tool_calls=[asdict(c) for c in answer.tool_calls], provider=answer.provider))
    session.flush()
    return conv.id, answer
