"""
src/tasks/rag_stats_warm.py

자주 묻는 시·도 단위 용역 통계의 RAG 집계 캐시 예열.

"인천 용역 낙찰률 알려줘" 같은 질문은 캐시가 비어 있으면 5년 창 집계 다섯 개가
차례로 돌아 첫 답이 1분을 넘습니다. 반면 질문 문구는 17개 시·도에서 거의 같은
형태로 반복됩니다. 그래서 수집 직후와 하루 한 번, 챗봇 정형 경로가 만드는 것과
같은 SQL·캐시 키(rag:agg:, rag:top:, rag:rows:)를 미리 계산해 둡니다. 사용자의
첫 질문은 캐시 적중으로 끝나고 무거운 집계는 다시 돌지 않습니다.

예열은 LLM 을 부르지 않습니다. src/rag/structured_data.py 의
retrieve_structured_data 만 호출하고, 계획 수립도 챗봇과 같은 공개 함수를
씁니다(src/rag/engine.py 의 _prepare_context 정형 분기와 같은 순서).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from src.rag.query_planning import (
    apply_default_statistics_window,
    build_retrieval_plan,
    replace_whole_period_insufficiency_hint,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data
from src.tasks.error_payload import safe_error, summarize_error

logger = logging.getLogger(__name__)

# 17개 시·도 짧은 명칭. 챗봇의 지역 추출기(REGION_KEYWORDS)와 같은 표기를 씁니다.
# "충청북도" 처럼 정식 명칭을 쓰면 어휘 추출 결과가 달라져 캐시 키가 갈립니다.
WARM_REGIONS: tuple[str, ...] = (
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
)

# 실제 사용자 로그에서 반복되는 두 형태만 둡니다. 문구가 조금만 달라도 기간·지표
# 추출이 달라져 다른 SQL(따라서 다른 캐시 키)이 만들어지므로, 챗봇이 같은 계획을
# 만드는 문구로 한정합니다. "낙찰률" 질의는 기본 5년 창을, "공고 건수" 질의는
# 공고 건수 기본 창(최근 30일)을 씁니다. 둘 다 챗봇 요청 경로의 실제 규칙입니다.
WARM_QUESTION_TEMPLATES: tuple[str, ...] = (
    "{region} 용역 낙찰률 알려줘",
    "{region} 용역 공고 건수",
)


def warm_questions() -> tuple[str, ...]:
    """예열 대상 질문 목록(17개 시·도 x 2문구)을 돌려줍니다."""
    return tuple(
        template.format(region=region)
        for region in WARM_REGIONS
        for template in WARM_QUESTION_TEMPLATES
    )


def build_warm_plan(question: str) -> RetrievalPlan:
    """챗봇 정형 분기가 세우는 것과 같은 검색 계획을 만듭니다.

    engine._prepare_context 는 build_retrieval_plan 뒤에, 어휘 채널이 아니고
    공고번호 단건도 아닌 계획에만 기본 통계 창을 채웁니다. 같은 규칙을 공개
    함수로 다시 적용해 예열이 만드는 SQL 과 캐시 키가 요청 경로와 일치하게
    합니다. 규칙이 갈리면 tests/test_stats_warm_20261122.py 가 잡습니다.
    """
    plan = build_retrieval_plan(question)
    filters = dict(plan.filters or {})
    if plan.use_lexical or filters.get("bid_ntce_no"):
        return plan
    windowed = apply_default_statistics_window(filters, query=plan.semantic_query)
    return plan.model_copy(
        update={
            "filters": windowed,
            "insufficiency_hints": replace_whole_period_insufficiency_hint(
                plan.insufficiency_hints, windowed
            ),
        }
    )


def warm_rag_region_stats(
    db: Session,
    *,
    questions: Iterable[str] | None = None,
) -> dict[str, Any]:
    """질문을 순차로 실행해 RAG 집계 캐시를 채우고 결과를 요약합니다.

    동시 실행은 하지 않습니다. 5년 창 집계 한 건이 20초를 넘길 수 있어 병렬로
    돌리면 운영 DB 를 붙잡습니다. 한 질문이 실패해도 롤백한 뒤 다음 질문을
    계속하고, 성공·실패·소요 초를 반환값과 로그에 남깁니다.
    """
    started = time.perf_counter()
    targets = tuple(questions) if questions is not None else warm_questions()
    succeeded = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    for question in targets:
        plan = build_warm_plan(question)
        if not plan.use_sql:
            skipped += 1
            logger.warning("RAG 통계 예열 질문이 정형 경로가 아닙니다: %s", question)
            continue
        try:
            retrieve_structured_data(db, plan)
        except Exception as exc:
            failures.append({"question": question, **safe_error(exc)})
            logger.warning("RAG 통계 예열 실패 (%s): %s", question, summarize_error(exc))
            try:
                db.rollback()
            except Exception:
                logger.debug("예열 실패 뒤 세션 롤백도 실패했습니다.", exc_info=True)
            continue
        succeeded += 1

    failed = len(failures)
    if failed == 0 and skipped == 0:
        status = "success"
    elif succeeded == 0:
        status = "failed"
    else:
        status = "partial_success"
    outcome: dict[str, Any] = {
        "status": status,
        "question_count": len(targets),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    if failures:
        outcome["failures"] = failures
    return outcome
