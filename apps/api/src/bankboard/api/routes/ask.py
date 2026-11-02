from __future__ import annotations

from fastapi import APIRouter

from bankboard.ai.ask import ask as ask_service
from bankboard.api.deps import DB, Ctx
from bankboard.api.schemas import AskIn, AskOut

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", response_model=AskOut)
def ask(body: AskIn, ctx: Ctx, db: DB) -> AskOut:
    conv_id, answer = ask_service(db, ctx, body.question, conversation_id=body.conversation_id)
    return AskOut(conversation_id=conv_id, answer=answer.text, provider=answer.provider,
                  tools_used=[c.name for c in answer.tool_calls], unverified_numbers=answer.unverified_numbers,
                  refused=answer.refused)
