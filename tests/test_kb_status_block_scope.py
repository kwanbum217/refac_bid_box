"""KB 색인 상태 블록 부착 범위 시험.

전체 블록은 플래너가 kb_status_tool 단계를 고른 명시적 KB 상태 질문에만 붙고,
범위 밖 거절·DB 직접 응답·벡터 검색 응답에서는 답변 본문에 붙지 않아야 합니다.
응답 JSON 의 kb_status 필드는 경로와 무관하게 계속 실립니다.
"""

import json
from unittest.mock import patch

from src.app.models.chatbot import KnowledgeBaseStatus
from src.app.services.tools.kb_status_tool import build_kb_status_summary
from src.rag.schemas import AnswerBundle, Provenance

PLAN_EXEC_TARGET = "src.app.api.v1.chatbot.execute_plan_steps"
RAG_SYNC_TARGET = "src.app.api.v1.chatbot.rag_engine.get_answer_sync"
RAG_STREAM_TARGET = "src.app.api.v1.chatbot.rag_engine.stream_tokens"

BLOCK_HEADER = "KB 색인 상태:"
BLOCK_BODY = "색인된 원본 문서 수"
REFUSAL_ANSWER = "저는 공공입찰 데이터 분석 도우미입니다. 입찰 공고와 낙찰 분석을 도와드립니다."
DB_ANSWER = "2026-10-01 ~ 2026-10-25 건설 공고는 8,539건입니다.\n\n근거: DB 집계 기반"
VECTOR_ANSWER = "최근 공고의 특징은 물품 공고 비중이 높다는 점입니다.\n\n근거: Chroma 문맥 기반"


def _seed_kb_status(db, **overrides) -> KnowledgeBaseStatus:
    payload = {
        "kb_version": "bidding_kb",
        "status": "ready",
        "source_bid_count": 321,
        "last_pipeline_run_id": "exec_002",
    }
    payload.update(overrides)
    kb = KnowledgeBaseStatus(**payload)
    db.add(kb)
    db.commit()
    return kb


def _chat(client, message: str):
    return client.post("/api/v1/chatbot/chat", json={"message": message})


def _bundle(answer: str, retrieval_mode: str = "vector") -> AnswerBundle:
    return AnswerBundle(
        answer=answer,
        provenance=Provenance(trace_id="test-trace", retrieval_mode=retrieval_mode),
    )


def _final_event(response) -> dict:
    for chunk in response.text.split("\n\n"):
        lines = [line for line in chunk.splitlines() if line]
        if len(lines) < 2 or not lines[0].startswith("event: final"):
            continue
        return json.loads(lines[1].removeprefix("data: "))
    raise AssertionError("final 이벤트를 찾지 못했습니다")


def _fake_stream(answer: str):
    async def stream(*_args, **_kwargs):
        yield {"type": "token", "text": answer}
        yield {"type": "done", "final_answer": answer, "trace_id": "test-trace"}

    return stream


# --------------------------------------------------------------------------- #
# 비스트리밍 경로
# --------------------------------------------------------------------------- #


@patch(RAG_SYNC_TARGET, return_value=_bundle(REFUSAL_ANSWER, "out_of_scope_refusal"))
@patch(PLAN_EXEC_TARGET, return_value={})
def test_out_of_scope_refusal_has_no_kb_block(mocked_plan_steps, mocked_rag, client, isolated_db):
    _seed_kb_status(isolated_db)

    payload = _chat(client, "안녕하세요, 너는 누구야?").json()

    assert payload["answer"] == REFUSAL_ANSWER
    assert BLOCK_HEADER not in payload["answer"]
    assert BLOCK_BODY not in payload["answer"]
    assert payload["kb_status"]["source_bid_count"] == 321


@patch(RAG_SYNC_TARGET, return_value=_bundle(DB_ANSWER, "sql"))
@patch(PLAN_EXEC_TARGET, return_value={})
def test_db_direct_answer_has_no_kb_block_and_keeps_citation(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    _seed_kb_status(isolated_db)

    payload = _chat(client, "2026-10-01 ~ 2026-10-25 건설 공고는 몇 건이야?").json()

    assert payload["answer"] == DB_ANSWER
    assert "근거: DB 집계 기반" in payload["answer"]
    assert BLOCK_HEADER not in payload["answer"]
    assert BLOCK_BODY not in payload["answer"]
    assert payload["kb_status"]["source_bid_count"] == 321


@patch(RAG_SYNC_TARGET, return_value=_bundle(VECTOR_ANSWER))
@patch(PLAN_EXEC_TARGET, return_value={})
def test_vector_answer_has_no_kb_block_and_keeps_citation(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    _seed_kb_status(isolated_db)

    payload = _chat(client, "최근 공고 특징 알려줘").json()

    assert payload["answer"] == VECTOR_ANSWER
    assert "근거: Chroma 문맥 기반" in payload["answer"]
    assert BLOCK_HEADER not in payload["answer"]
    assert BLOCK_BODY not in payload["answer"]
    assert payload["kb_status"]["source_bid_count"] == 321


@patch(RAG_SYNC_TARGET, return_value=_bundle("기본 답변"))
@patch(PLAN_EXEC_TARGET)
def test_kb_status_question_attaches_block_once(mocked_plan_steps, mocked_rag, client, isolated_db):
    _seed_kb_status(isolated_db)
    mocked_plan_steps.return_value = {
        "tool_results": {
            "kb_status": {
                "kb_status": {"status": "ready", "source_bid_count": 321},
                "summary": build_kb_status_summary(
                    {"kb_version": "bidding_kb", "status": "ready", "source_bid_count": 321}
                ),
            }
        }
    }

    payload = _chat(client, "KB 색인 상태 알려줘").json()

    assert payload["plan_steps"][0]["tool"] == "kb_status_tool"
    assert payload["answer"].count(BLOCK_HEADER) == 1
    assert payload["answer"].count(BLOCK_BODY) == 1
    assert payload["answer"].startswith("기본 답변")
    assert payload["kb_status"]["source_bid_count"] == 321


@patch(
    RAG_SYNC_TARGET,
    return_value=_bundle("- KB 색인 상태: ready / 원본 문서 321건\n\n근거: DB 집계 기반", "sql"),
)
@patch(PLAN_EXEC_TARGET, return_value={})
def test_kb_status_question_does_not_duplicate_engine_kb_line(
    mocked_plan_steps, mocked_rag, client, isolated_db
):
    _seed_kb_status(isolated_db)
    engine_answer = "- KB 색인 상태: ready / 원본 문서 321건\n\n근거: DB 집계 기반"

    payload = _chat(client, "KB 색인 상태 알려줘").json()

    assert payload["plan_steps"][0]["tool"] == "kb_status_tool"
    assert payload["answer"] == engine_answer
    assert payload["answer"].count(BLOCK_HEADER) == 1
    assert BLOCK_BODY not in payload["answer"]


# --------------------------------------------------------------------------- #
# 스트리밍 경로
# --------------------------------------------------------------------------- #


def test_stream_out_of_scope_refusal_has_no_kb_block(client, isolated_db):
    _seed_kb_status(isolated_db)

    with (
        patch(PLAN_EXEC_TARGET, return_value={}),
        patch(RAG_STREAM_TARGET, _fake_stream(REFUSAL_ANSWER)),
    ):
        response = client.post(
            "/api/v1/chatbot/chat/stream", json={"message": "안녕하세요, 너는 누구야?"}
        )

    final = _final_event(response)
    assert final["answer"] == REFUSAL_ANSWER
    assert BLOCK_HEADER not in final["answer"]
    assert BLOCK_BODY not in final["answer"]
    assert final["kb_status"]["source_bid_count"] == 321


def test_stream_kb_status_question_attaches_block_once(client, isolated_db):
    _seed_kb_status(isolated_db)
    summary = build_kb_status_summary(
        {"kb_version": "bidding_kb", "status": "ready", "source_bid_count": 321}
    )

    with (
        patch(
            PLAN_EXEC_TARGET,
            return_value={
                "tool_results": {
                    "kb_status": {
                        "kb_status": {"status": "ready", "source_bid_count": 321},
                        "summary": summary,
                    }
                }
            },
        ),
        patch(RAG_STREAM_TARGET, _fake_stream("기본 답변")),
    ):
        response = client.post(
            "/api/v1/chatbot/chat/stream", json={"message": "KB 색인 상태 알려줘"}
        )

    final = _final_event(response)
    assert final["plan_steps"][0]["tool"] == "kb_status_tool"
    assert final["answer"].count(BLOCK_HEADER) == 1
    assert final["answer"].count(BLOCK_BODY) == 1
    assert final["kb_status"]["source_bid_count"] == 321
