from fastapi import APIRouter, Depends
import secrets
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.shopping_copilot.models import CopilotMessage, CopilotSession
from app.ai.shopping_copilot.schemas import ChatRequest, ChatResponse
from app.ai.shopping_copilot.workflow import run_workflow
from app.db.session import get_session
from app.modules.cart.router import token_hash
from app.core.exceptions import AppError

router = APIRouter(prefix="/copilot", tags=["shopping-copilot"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, session: AsyncSession = Depends(get_session)
) -> ChatResponse:
    conversation = (
        await session.get(CopilotSession, payload.session_id)
        if payload.session_id
        else None
    )
    raw_token = payload.session_token
    if payload.session_id and (
        conversation is None
        or not conversation.token_hash
        or not raw_token
        or not secrets.compare_digest(conversation.token_hash, token_hash(raw_token))
    ):
        raise AppError(404, "copilot_session_not_found", "Conversation not found")
    if conversation is None:
        raw_token = secrets.token_urlsafe(32)
        conversation = CopilotSession(token_hash=token_hash(raw_token))
        session.add(conversation)
        await session.flush()
    session.add(
        CopilotMessage(session_id=conversation.id, role="user", content=payload.message)
    )
    result = await run_workflow(session, payload.message)
    evidence = [item.model_dump(mode="json") for item in result.products]
    session.add(
        CopilotMessage(
            session_id=conversation.id,
            role="assistant",
            content=result.answer,
            evidence=evidence,
        )
    )
    await session.commit()
    return ChatResponse(
        session_id=conversation.id,
        session_token=raw_token,
        answer=result.answer,
        intent=result.intent,
        products=result.products,
        disclaimer=result.disclaimer,
    )
