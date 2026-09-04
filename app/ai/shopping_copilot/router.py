from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.shopping_copilot.models import CopilotMessage, CopilotSession
from app.ai.shopping_copilot.schemas import ChatRequest, ChatResponse
from app.ai.shopping_copilot.workflow import run_workflow
from app.db.session import get_session

router = APIRouter(prefix="/copilot", tags=["shopping-copilot"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    conversation = await session.get(CopilotSession, payload.session_id) if payload.session_id else None
    if conversation is None:
        conversation = CopilotSession()
        session.add(conversation)
        await session.flush()
    session.add(CopilotMessage(session_id=conversation.id, role="user", content=payload.message))
    result = await run_workflow(session, payload.message)
    evidence = [item.model_dump(mode="json") for item in result.products]
    session.add(CopilotMessage(session_id=conversation.id, role="assistant", content=result.answer, evidence=evidence))
    await session.commit()
    return ChatResponse(session_id=conversation.id, answer=result.answer, intent=result.intent, products=result.products, disclaimer=result.disclaimer)

