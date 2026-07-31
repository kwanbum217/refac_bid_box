import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.app.core.db import get_db
from src.app.schemas.chatbot import ChatbotQueryRequest, ChatbotQueryResponse
from src.app.services.planner import build_chat_plan
from src.rag.engine import rag_engine

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


@router.post("/query", response_model=ChatbotQueryResponse)
async def query_chatbot(payload: ChatbotQueryRequest, db: Session = Depends(get_db)):
    plan = build_chat_plan(payload.query)
    bundle = await rag_engine.get_answer(payload.query, db=db if plan.intent_type == "statistics_query" else None)

    return ChatbotQueryResponse(
        query=payload.query,
        response=bundle.answer,
        retrieved_docs=bundle.retrieved_docs,
        latency_ms=bundle.latency_ms,
    )


@router.get("/stream")
async def stream_chatbot(query: str, db: Session = Depends(get_db)):
    async def event_generator():
        async for event in rag_engine.stream_tokens(query, db=db):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
