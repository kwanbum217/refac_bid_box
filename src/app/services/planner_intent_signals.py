"""
src/app/services/planner_intent_signals.py

챗봇 질의 해석 및 의도 신호 추출 헬퍼 모듈.
키워드 사전 및 사용자 메시지로부터 지역, 분야, 투찰가 예측, 수집, KB 갱신 등의 신호를 추출합니다.
"""

from __future__ import annotations

from typing import Any

from src.app.services.action_catalog import ACTION_CATALOG

ADVISORY_KEYWORDS = ("매일", "매주", "알림", "구독", "자동으로", "정기")
STATISTICS_KEYWORDS = (
    "통계",
    "평균",
    "추세",
    "비교",
    "건수",
    "낙찰률",
    "경쟁률",
    "집계",
    "그래프",
    "차트",
    "흐름",
)
SEMANTIC_KEYWORDS = (
    "최근",
    "여부",
    "상세",
    "자세히",
    "설명",
    "왜",
    "특징",
    "문맥",
    "무엇",
    "어떤",
    "원인",
    "리스크",
)
KB_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩", "인덱스", "색인")
FOLLOWUP_SPLITTERS = ("그리고", "필요하면", "이상하면", "같이", "함께")
CATEGORY_KEYWORDS = {
    "공사": "Cnstwk",
    "물품": "Thng",
    "용역": "Servc",
    "외자": "Frgcpt",
}
REGION_KEYWORDS = (
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
FOLLOWUP_DETAIL_KEYWORDS = ("자세히", "더 자세히", "좀 더", "왜", "설명")
FOLLOWUP_CHART_KEYWORDS = ("그래프", "차트", "시각화")
FOLLOWUP_RERUN_KEYWORDS = ("다시", "이번엔", "이번에는", "방금", "그 결과", "재실행")
FOLLOWUP_KB_REFRESH_KEYWORDS = (
    "kb 갱신",
    "kb 업데이트",
    "kb 최신화",
    "지식베이스 갱신",
    "지식베이스 업데이트",
    "지식베이스 최신화",
    "벡터 갱신",
    "벡터 업데이트",
    "벡터 최신화",
    "임베딩 갱신",
    "임베딩 업데이트",
    "임베딩 최신화",
    "인덱스 갱신",
    "인덱스 업데이트",
    "인덱스 최신화",
    "색인 갱신",
    "색인 업데이트",
    "색인 최신화",
)
KB_REFRESH_TARGET_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩", "인덱스", "색인")
KB_REFRESH_COMMAND_KEYWORDS = ("갱신", "업데이트", "최신화", "재생성", "다시 구축", "새로 구축")
FOLLOWUP_RESULT_REFERENCE_KEYWORDS = (
    "그 결과",
    "방금 결과",
    "이전 결과",
    "그 차트",
    "방금 차트",
    "이 그래프",
    "결과",
    "상태",
    "성공",
    "실패",
)
FOLLOWUP_RANKING_KEYWORDS = (
    "상위 업체",
    "상위 낙찰업체",
    "top 업체",
    "우승 업체",
    "많이 나온 업체",
)
FOLLOWUP_TREND_DETAIL_KEYWORDS = (
    "감소한 구간",
    "하락 구간",
    "상승 구간",
    "피크",
    "최고 구간",
    "최저 구간",
    "변동폭",
)
TREND_VISUAL_KEYWORDS = ("추세", "흐름", "변동", "그래프", "차트", "시각화")
STATUS_QUERY_KEYWORDS = ("상태", "성공", "실패", "결과", "완료", "어떻게 됐어", "다 됐어")
AUTOMATION_STATUS_KEYWORDS = (
    "진행 상황",
    "진행상황",
    "점검 진행",
    "현재 점검",
    "실행 상태",
    "자동화 상태",
    "작업 상태",
    "방금 점검",
    "방금 실행",
    "전체 점검 최종",
)
PREDICTION_CONTEXT_KEYWORDS = (
    "예측",
    "투찰가",
    "투찰 금액",
    "입찰가",
    "낙찰가",
    "모델",
    "v13",
    "v25",
    "ssh_hist_premium",
    "quantum_leap",
)
PREDICTION_ACTION_KEYWORDS = (
    "예측해",
    "예측 해",
    "예측 실행",
    "예측 돌려",
    "예측 다시",
    "예측 재실행",
    "투찰가",
    "투찰 금액",
    "입찰가",
    "모델 검증",
    "검증해",
    "품질 기준",
    "기준 미달",
)
MODEL_VALIDATION_KEYWORDS = (
    "모델 검증",
    "예측 모델 검증",
    "품질 기준",
    "기준 미달",
    "성능 검증",
    "acceptance",
)
BID_PRICE_PREDICTION_KEYWORDS = (
    "투찰가",
    "투찰 금액",
    "투찰금액",
    "입찰가",
    "낙찰가",
)
COLLECTION_COMMAND_KEYWORDS = (
    "수집해",
    "수집하",
    "수집 실행",
    "수집 돌려",
    "수집하고",
    "데이터 수집",
    "입찰 수집",
    "공고 수집",
    "공고 업데이트",
    "신규 공고 반영",
)
COLLECTION_CONTEXT_KEYWORDS = ("수집된", "수집한", "수집 완료")


def _extract_bid_query_params(
    message: str, filters: dict[str, Any] | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"query": message, "years": 5}
    lowered = message.lower()

    if filters:
        for key in ("category", "institution_name", "years", "date_from", "date_to"):
            if key in filters:
                params[key] = filters[key]

    if "category" not in params:
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in lowered:
                params["category"] = category
                break

    if "years" not in params and any(kw in lowered for kw in ("최근", "요즘", "이번")):
        params["years"] = 1

    return params


def _extract_followup_region(message: str) -> str:
    normalized = (message or "").strip().lower()
    for region in REGION_KEYWORDS:
        if region in normalized:
            return region
    return ""


def _extract_followup_category(message: str) -> tuple[str, str]:
    normalized = (message or "").strip().lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in normalized:
            return keyword, category
    return "", ""


def _has_prediction_action_intent(message: str) -> bool:
    has_prediction_context = any(keyword in message for keyword in PREDICTION_CONTEXT_KEYWORDS)
    has_prediction_command = any(keyword in message for keyword in PREDICTION_ACTION_KEYWORDS)
    return has_prediction_context and has_prediction_command


def _has_collection_command(message: str) -> bool:
    return any(keyword in message for keyword in COLLECTION_COMMAND_KEYWORDS)


def _has_collection_context_only(message: str) -> bool:
    return any(
        keyword in message for keyword in COLLECTION_CONTEXT_KEYWORDS
    ) and not _has_collection_command(message)


def _is_model_validation_request(message: str) -> bool:
    return any(keyword in message for keyword in MODEL_VALIDATION_KEYWORDS)


def _is_bid_price_prediction_request(message: str) -> bool:
    has_price_target = any(keyword in message for keyword in BID_PRICE_PREDICTION_KEYWORDS)
    has_prediction_signal = any(keyword in message for keyword in PREDICTION_CONTEXT_KEYWORDS)
    return has_price_target and has_prediction_signal and not _is_model_validation_request(message)


def _extract_prediction_model_id(message: str) -> str:
    if "quantum_leap_v25_pro" in message or "quantum leap" in message:
        return "quantum_leap_v25_pro"
    if "ssh_hist_premium" in message or "ssh" in message:
        return "ssh_hist_premium"
    if "v13_hybrid" in message or "v13" in message:
        return "v13_hybrid"
    if "v25" in message:
        return "v25"
    return ""


def _extract_prediction_limit(message: str) -> int:
    try:
        from src.app.services.tools.bid_prediction_tool import coerce_limit
    except ImportError:
        return 1
    return coerce_limit(0, message)


def _select_action(message: str, matched_actions: list) -> Any:
    wants_visual_answer = any(
        keyword in message for keyword in ("그래프", "차트", "시각화", "보여줘", "분석")
    )
    selected_action = matched_actions[0]
    if wants_visual_answer and any(
        action.action_key == "data_refresh" for action in matched_actions
    ):
        return ACTION_CATALOG["data_refresh"]
    if wants_visual_answer and selected_action.action_key in {"collect_refresh", "kb_refresh"}:
        return ACTION_CATALOG["data_refresh"]
    if len(matched_actions) > 1:
        return ACTION_CATALOG["full_validation"]
    return selected_action


def _has_kb_refresh_intent(message: str) -> bool:
    normalized = message or ""
    if any(keyword in normalized for keyword in FOLLOWUP_KB_REFRESH_KEYWORDS):
        return True
    has_target = any(keyword in normalized for keyword in KB_REFRESH_TARGET_KEYWORDS)
    has_command = any(keyword in normalized for keyword in KB_REFRESH_COMMAND_KEYWORDS)
    return has_target and has_command
