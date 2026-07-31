import time
from fastapi import APIRouter
from src.app.schemas.chatbot import ChatbotQueryRequest, ChatbotQueryResponse

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


@router.post("/query", response_model=ChatbotQueryResponse)
async def query_chatbot(payload: ChatbotQueryRequest):
    start_time = time.time()

    # RAG 질의응답 비동기 로직
    response_text = f"'{payload.query}'에 대한 공공조달 하이브리드 RAG 분석 결과입니다."
    mock_docs = [
        {"title": "국가를 당사자로 하는 계약에 관한 법률 시행령 제42조", "score": 0.92},
        {"title": "조달청 물품구매 적격심사 세부기준", "score": 0.88},
    ]

    latency_ms = (time.time() - start_time) * 1000.0

    return ChatbotQueryResponse(
        query=payload.query,
        response=response_text,
        retrieved_docs=mock_docs,
        latency_ms=latency_ms,
    )
