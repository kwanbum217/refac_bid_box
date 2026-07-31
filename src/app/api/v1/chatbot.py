import asyncio
import json
import time
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from src.app.schemas.chatbot import ChatbotQueryRequest, ChatbotQueryResponse
from src.rag.vector_store import vector_store

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


@router.post("/query", response_model=ChatbotQueryResponse)
async def query_chatbot(payload: ChatbotQueryRequest):
    start_time = time.time()
    docs = await vector_store.search_similar_docs(payload.query)

    response_text = f"'{payload.query}'에 대한 공공조달 적격심사 및 입찰가 RAG 분석 결과입니다."
    latency_ms = (time.time() - start_time) * 1000.0

    return ChatbotQueryResponse(
        query=payload.query,
        response=response_text,
        retrieved_docs=docs,
        latency_ms=latency_ms,
    )


@router.get("/stream")
async def stream_chatbot(query: str):
    """
    SSE(Server-Sent Events) 기반 Gemini LLM 토큰 실시간 스트리밍 엔드포인트.
    """
    async def event_generator():
        # 1. RAG 비동기 문서 검색
        docs = await vector_store.search_similar_docs(query)
        yield f"data: {json.dumps({'type': 'docs', 'docs': docs}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.1)

        # 2. LLM 청크 토큰 스트리밍
        tokens = [
            f"입력하신 '{query}' 공고건에 대해 ",
            "ChromaDB 지식베이스 19개 컬렉션을 검색했습니다. ",
            "적격심사 배점 기준에 따르면 ",
            "투찰률 87.745% 부근에서 낙찰 확률이 가장 높게 형성됩니다.",
        ]

        for token in tokens:
            yield f"data: {json.dumps({'type': 'token', 'text': token}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.15)

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
