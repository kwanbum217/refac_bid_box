"""
src/rag/answer_format.py

RAG 응답 포매팅, Markdown 테이블 조립, Source 인용 생성, Evidence 및 fallback 답변 빌더.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.rag.query_planning import (
    LIST_REQUEST_MARKERS,
    _category_label,
    _normalize_text,
    _single_metric,
    unapplied_result_condition_notice,
)
from src.rag.schemas import (
    EvidenceItem,
    RetrievalPlan,
)
from src.rag.snapshots import (
    _extract_kb_snapshot,
    _extract_statistical_snapshot,
    _extract_trend_snapshot,
)

PRICE_TERM_NOTES = (
    "- 기초금액: 발주기관이 예정가격 작성의 기준으로 공고하는 금액입니다.\n"
    "- 예정가격: 기초금액을 바탕으로 복수예비가격 추첨 등을 거쳐 개찰 시점에 확정되는 낙찰자 결정 기준 가격이며, 개찰 전에는 공개되지 않습니다.\n"
    "- 추정가격: 입찰 방법 결정 등에 쓰도록 부가가치세를 제외하고 산정한 금액입니다.\n"
    "- 공고별 값은 아래 Source 에 있는 값만 인용하고, 없는 값은 추정하지 않습니다."
)


def _format_filters_for_prompt(filters: dict | None) -> str:
    if not filters:
        return ""

    labels = {
        "institution_name": "기관/지역",
        "institution_names": "대상 기관",
        "region_names": "대상 지역",
        "date_from": "시작일",
        "date_to": "종료일",
        "relative_years": "최근 연수",
        "analysis_mode": "분석 모드",
        "result_limit": "요청 목록 수",
        "bid_ntce_no": "공고번호",
        "group_by": "집계 축",
        "metric": "집계 지표",
        "group_limit": "집계 행 상한",
    }
    lines = []
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key == "category":
            lines.append(f"- 분야: {_category_label(str(value))}")
            continue
        if key in ("institution_names", "region_names") and isinstance(value, list):
            lines.append(f"- {labels[key]}: {', '.join(str(v) for v in value)}")
            continue
        lines.append(f"- {labels.get(key, key)}: {value}")
    return "\n".join(lines)


def _normalize_category_wording(answer_text: str, plan: RetrievalPlan) -> str:
    """분야 코드(Servc)가 사용자 답변에 노출되지 않도록 교정합니다."""
    category = str((plan.filters or {}).get("category") or "")
    if category != "Servc":
        return answer_text

    normalized = str(answer_text or "")
    replacements = (
        (r"서비스\s*\(\s*Servc\s*\)", "용역"),
        (r"Service\s*\(\s*Servc\s*\)", "용역"),
        (r"\bServc\b", "용역"),
        (r"서비스\s*분야", "용역 분야"),
        (r"서비스\s*공고", "용역 공고"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def _markdown_result_cell(value: Any) -> str:
    return str(value or "-").replace("|", "\\|").replace("\n", " ").strip()


def _format_result_amount(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return "-"


def _format_result_rate(value: Any) -> str:
    try:
        return f"{float(value):.4f}%"
    except (TypeError, ValueError):
        return "-"


def _build_result_list_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """목록 질의는 LLM 추측 없이 DB 결과를 그대로 표시합니다."""
    result_limit = (plan.filters or {}).get("result_limit")
    if not result_limit or not structured_data:
        return ""

    summary = structured_data.get("summary") or {}
    results = summary.get("recent_results") or []
    category_label = (structured_data.get("filters") or {}).get("category_label") or "조건"
    # 낙찰 결과 테이블에 없는 축(추정가격·기초금액·마감일)의 조건은 조회에서
    # 빠집니다. 표만 보여주면 조건이 적용된 줄 오해하므로 한 줄로 밝힙니다.
    unapplied_notice = unapplied_result_condition_notice(
        structured_data.get("unapplied_conditions") or []
    )
    if not results:
        latest = summary.get("latest_available_result_at")
        answer = f"요청하신 기간에 조건에 맞는 최근 {category_label} 낙찰 결과는 0건입니다."
        if latest:
            answer += f"\n현재 DB에서 확인 가능한 해당 분야의 최신 개찰일은 {latest}입니다."
        if unapplied_notice:
            answer += f"\n{unapplied_notice}"
        return answer

    lines = [
        f"최근 {category_label} 낙찰 결과 {len(results)}건입니다.",
        "",
    ]
    if unapplied_notice:
        lines.extend([unapplied_notice, ""])
    lines.extend(
        [
            "| # | 공고명 | 수요기관 | 낙찰업체 | 낙찰금액 | 낙찰률 | 개찰일 |",
            "| ---: | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for index, item in enumerate(results, start=1):
        lines.append(
            f"| {index} | {_markdown_result_cell(item.get('bid_ntce_nm'))} "
            f"({_markdown_result_cell(item.get('bid_ntce_no'))}) | "
            f"{_markdown_result_cell(item.get('dminstt_nm'))} | "
            f"{_markdown_result_cell(item.get('bidwinnr_nm'))} | "
            f"{_format_result_amount(item.get('sucsf_bid_amt'))} | "
            f"{_format_result_rate(item.get('sucsf_bid_rate'))} | "
            f"{_markdown_result_cell(item.get('rl_openg_dt'))} |"
        )
    return "\n".join(lines)


AMOUNT_FIELD_LABELS = {
    "presmpt_prce": "추정가격",
    "base_amount": "기초금액",
    "sucsf_bid_amt": "낙찰금액",
}
SORT_FIELD_LABELS = {
    **AMOUNT_FIELD_LABELS,
    "bid_clse_dt": "마감일",
}
SORT_DIRECTION_LABELS = {"asc": "오름차순", "desc": "내림차순"}


def _format_condition_amount(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return str(value)


def _announcement_condition_line(filters: dict | None) -> str:
    """목록 표에 적용된 마감일·금액·정렬 조건을 한 줄로 요약합니다."""
    if not filters:
        return ""
    parts: list[str] = []
    close_from = filters.get("close_from")
    close_to = filters.get("close_to")
    if close_from and close_to and close_from == close_to:
        parts.append(f"마감일 {close_from}")
    elif close_from and close_to:
        parts.append(f"마감일 {close_from}~{close_to}")
    elif close_from:
        parts.append(f"마감일 {close_from} 이후")
    elif close_to:
        parts.append(f"마감일 {close_to} 이전")

    amount_label = AMOUNT_FIELD_LABELS.get(str(filters.get("amount_field") or ""), "금액")
    min_amount = filters.get("min_amount")
    max_amount = filters.get("max_amount")
    if min_amount is not None and max_amount is not None:
        parts.append(
            f"{amount_label} {_format_condition_amount(min_amount)}"
            f"~{_format_condition_amount(max_amount)}"
        )
    elif min_amount is not None:
        parts.append(f"{amount_label} {_format_condition_amount(min_amount)} 이상")
    elif max_amount is not None:
        parts.append(f"{amount_label} {_format_condition_amount(max_amount)} 이하")

    order_by = str(filters.get("order_by") or "")
    if order_by:
        sort_label = SORT_FIELD_LABELS.get(order_by, order_by)
        direction = SORT_DIRECTION_LABELS.get(
            str(filters.get("order_dir") or "desc").lower(), "내림차순"
        )
        parts.append(f"{sort_label} {direction}")

    return f"적용 조건: {', '.join(parts)}" if parts else ""


def _build_announcement_list_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """공고 목록 질의는 LLM 추측 없이 DB 결과를 최신 공고일순 표로 표시합니다."""
    announcement_limit = (plan.filters or {}).get("announcement_limit")
    if not announcement_limit or not structured_data:
        return ""

    summary = structured_data.get("summary") or {}
    samples = summary.get("sample_announcements") or []
    category_label = (structured_data.get("filters") or {}).get("category_label") or "조건"
    condition_line = _announcement_condition_line(plan.filters)
    if not samples:
        answer = f"요청하신 기간에 조건에 맞는 {category_label} 공고는 0건입니다."
        if condition_line:
            answer += f"\n{condition_line}"
        return answer

    head_sentence = (
        f"조건에 맞는 {category_label} 공고 {len(samples)}건입니다."
        if condition_line
        else f"최근 {category_label} 공고 {len(samples)}건입니다."
    )
    lines = [
        head_sentence,
        "",
    ]
    if condition_line:
        lines.extend([condition_line, ""])
    lines.extend(
        [
            "| # | 공고명(공고번호) | 수요기관 | 추정가격 | 공고일 | 마감일 |",
            "| ---: | --- | --- | ---: | --- | --- |",
        ]
    )
    for index, item in enumerate(samples, start=1):
        lines.append(
            f"| {index} | {_markdown_result_cell(item.get('bid_ntce_nm'))} "
            f"({_markdown_result_cell(item.get('bid_ntce_no'))}) | "
            f"{_markdown_result_cell(item.get('dminstt_nm'))} | "
            f"{_format_result_amount(item.get('presmpt_prce'))} | "
            f"{_markdown_result_cell(item.get('bid_ntce_dt'))} | "
            f"{_markdown_result_cell(item.get('bid_clse_dt'))} |"
        )
    return "\n".join(lines)


def _format_bid_rate_comparison(result: dict, comparison: Any) -> str:
    """낙찰률을 같은 분류 평균과 비교한 문장을 만듭니다."""
    if not isinstance(comparison, dict):
        return ""
    rate = result.get("sucsf_bid_rate")
    baseline = comparison.get("average_winning_rate")
    if rate is None or baseline is None:
        return ""
    try:
        rate_value = float(rate)
        baseline_value = float(baseline)
    except (TypeError, ValueError):
        return ""
    category_label = str(comparison.get("category_label") or "같은 분류")
    sample_count = comparison.get("sample_count")
    try:
        suffix = f" (표본 {int(sample_count):,}건)" if sample_count else ""
    except (TypeError, ValueError):
        suffix = ""
    diff = rate_value - baseline_value
    if abs(diff) < 0.005:
        return f"{category_label} 평균 낙찰률 {baseline_value:.4f}% 와 같습니다.{suffix}"
    direction = "높습니다" if diff > 0 else "낮습니다"
    return (
        f"{category_label} 평균 낙찰률 {baseline_value:.4f}% 보다 "
        f"{abs(diff):.2f}%p {direction}.{suffix}"
    )


def _build_bid_detail_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """공고번호 단건은 공고·낙찰 필드와 같은 분류 평균 비교를 LLM 없이 냅니다."""
    bid_ntce_no = _normalize_text(str((plan.filters or {}).get("bid_ntce_no") or ""))
    if not bid_ntce_no or not structured_data:
        return ""

    summary = structured_data.get("summary") or {}
    detail = summary.get("bid_detail")
    if not isinstance(detail, dict):
        return f"공고번호 {bid_ntce_no} 은(는) 수집 데이터에서 확인할 수 없습니다."

    announcement = detail.get("announcement") or {}
    result = detail.get("result") or {}

    if result:
        lines = [
            f"공고번호 {bid_ntce_no} 낙찰 결과입니다.",
            "",
            "| 항목 | 값 |",
            "| --- | --- |",
            f"| 공고명 | {_markdown_result_cell(result.get('bid_ntce_nm'))} |",
            f"| 수요기관 | {_markdown_result_cell(result.get('dminstt_nm'))} |",
            f"| 분류 | {_markdown_result_cell(result.get('category_label'))} |",
            f"| 낙찰업체 | {_markdown_result_cell(result.get('bidwinnr_nm'))} |",
            f"| 낙찰금액 | {_format_result_amount(result.get('sucsf_bid_amt'))} |",
            f"| 낙찰률 | {_format_result_rate(result.get('sucsf_bid_rate'))} |",
            f"| 개찰일 | {_markdown_result_cell(result.get('rl_openg_dt'))} |",
        ]
        comparison_line = _format_bid_rate_comparison(result, detail.get("comparison"))
        if comparison_line:
            lines.extend(["", comparison_line])
        return "\n".join(lines)

    lines = [
        f"공고번호 {bid_ntce_no} 공고 정보입니다. 아직 수집된 낙찰 결과가 없습니다.",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 공고명 | {_markdown_result_cell(announcement.get('bid_ntce_nm'))} |",
        f"| 수요기관 | {_markdown_result_cell(announcement.get('dminstt_nm'))} |",
        f"| 분류 | {_markdown_result_cell(announcement.get('category_label'))} |",
        f"| 추정가격 | {_format_result_amount(announcement.get('presmpt_prce'))} |",
        f"| 공고일 | {_markdown_result_cell(announcement.get('bid_ntce_dt'))} |",
        f"| 마감일 | {_markdown_result_cell(announcement.get('bid_clse_dt'))} |",
    ]
    return "\n".join(lines)


AXIS_LABELS = {
    "category": "분류",
    "institution": "기관",
    "region": "지역",
    "winner": "업체",
}
METRIC_LABELS = {
    "announcement_count": "공고 건수",
    "bid_count": "낙찰 건수",
    "avg_rate": "평균 낙찰률",
}


def _format_axis_value(metric: str, value: Any) -> str:
    if value is None:
        return "-"
    try:
        if metric == "avg_rate":
            return f"{float(value):.4f}%"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _winner_axis_caption(
    plan: RetrievalPlan,
    structured_data: dict,
    metric_label: str,
    meta: dict,
) -> str:
    """업체 순위 표 위에 집계 기간과 분야를 명시합니다.

    같은 1위라도 기간이 있으면 그 기간의 실시간 집계이고, 없으면 전체 기간
    집계입니다. 어느 쪽인지 밝히지 않으면 사용자는 질문에 없는 창을 답으로
    읽습니다.
    """
    window = meta.get("window") or {}
    date_from = str(window.get("date_from") or "")
    date_to = str(window.get("date_to") or "")
    relative_years = int((plan.filters or {}).get("relative_years") or 0)
    filters = structured_data.get("filters") or {}
    category = str(filters.get("category_label") or "").strip()
    if not category:
        category_code = str((plan.filters or {}).get("category") or "")
        category = _category_label(category_code) if category_code else ""
    category = category or "전체 분야"
    if date_from and date_to:
        period = f"{date_from} ~ {date_to}"
    elif date_from:
        period = f"{date_from} 이후"
    elif date_to:
        period = f"{date_to} 이전"
    elif relative_years:
        period = f"최근 {relative_years}년 기준"
    else:
        period = "전체 기간 기준"
    return f"{period} {category} 업체별 {metric_label}입니다."


def _build_axis_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """축별 집계는 LLM 없이 선택한 지표 하나만 표로 냅니다.

    두 지표를 한 표에 나란히 놓으면 "공고 건수" 질문에 "낙찰 건수" 를 답하는
    혼동이 재발합니다. 나머지 지표는 axis_breakdown 에 남겨 두고 화면에는
    내지 않습니다.
    """
    if not structured_data:
        return ""
    summary = structured_data.get("summary") or {}
    rows = summary.get("axis_breakdown") or []
    meta = summary.get("aggregate_meta") or {}
    group_by = str(meta.get("group_by") or "")
    metric = str(meta.get("metric") or "")
    if not rows or group_by not in AXIS_LABELS or metric not in METRIC_LABELS:
        return ""

    axis_label = AXIS_LABELS[group_by]
    metric_label = METRIC_LABELS[metric]
    if group_by == "winner":
        headline = _winner_axis_caption(plan, structured_data, metric_label, meta)
    else:
        headline = f"{axis_label}별 {metric_label}입니다."
    lines = [
        headline,
        "",
        f"| {axis_label} | {metric_label} |",
        "| --- | ---: |",
    ]
    for item in rows:
        lines.append(
            f"| {_markdown_result_cell(item.get('label'))} | "
            f"{_format_axis_value(metric, item.get(metric))} |"
        )
    if meta.get("truncated"):
        lines.extend(["", f"상위 {len(rows)}건만 표시했습니다."])
    return "\n".join(lines)


SERIES_PERIOD_LABELS = {
    "quarter": ("분기별", "분기"),
    "month": ("월별", "월"),
    "day": ("일별", "일자"),
}
IN_PROGRESS_SUFFIX = "(진행 중)"


def _series_period_labels(period: str) -> tuple[str, str]:
    return SERIES_PERIOD_LABELS.get(period, SERIES_PERIOD_LABELS["month"])


def _is_current_series_bucket(label: str, period: str) -> bool:
    """오늘이 속한 분기·월·일 구간인지 판정합니다.

    마지막 구간은 아직 채워지는 중입니다. 완결된 구간과 같은 무게로 읽히지
    않도록 라벨에 표시합니다.
    """
    today = date.today()
    text = _normalize_text(str(label or ""))
    if period == "quarter":
        matched = re.fullmatch(r"(\d{4})\s*년\s*([1-4])\s*분기", text)
        if not matched:
            return False
        return int(matched.group(1)) == today.year and int(matched.group(2)) == (
            (today.month - 1) // 3 + 1
        )
    if period == "day":
        return text == today.isoformat()
    matched = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if not matched:
        return False
    return (int(matched.group(1)), int(matched.group(2))) == (today.year, today.month)


def _series_label_cell(item: dict, period: str) -> str:
    label = str(item.get("label") or "")
    if _is_current_series_bucket(label, period):
        return _markdown_result_cell(f"{label} {IN_PROGRESS_SUFFIX}")
    return _markdown_result_cell(label)


def _format_series_cell(metric: str, value: Any) -> str:
    if value is None:
        return "-"
    try:
        if metric == "avg_rate":
            return f"{float(value):.2f}%"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _resolve_series_metric(plan: RetrievalPlan, meta: dict) -> str:
    """요청 지표를 정합니다. 지표 기록이 없으면 빈 문자열로 기존 경로에 맡깁니다."""
    metric = str(meta.get("metric") or (plan.filters or {}).get("metric") or "")
    return metric if metric in ("avg_rate", "bid_count") else ""


def _series_period_text(plan: RetrievalPlan, structured_data: dict) -> str:
    filters = dict(structured_data.get("filters") or {})
    for key, value in (plan.filters or {}).items():
        if value not in (None, ""):
            filters[key] = value
    period_text = _format_single_metric_period(filters)
    return "" if period_text == "전체 기간" else period_text


def _build_announcement_series_answer(series: list[dict]) -> str:
    """공고 건수 시계열은 기존 계약대로 공고 건수 열만 냅니다."""
    period = str(series[0].get("period") or "quarter")
    period_label, unit_label = _series_period_labels(period)
    lines = [
        f"{period_label} 공고 건수입니다.",
        "",
        f"| {unit_label} | 공고 건수 |",
        "| --- | ---: |",
    ]
    for item in series:
        value = item.get("announcement_count")
        try:
            rendered = f"{int(value or 0):,}"
        except (TypeError, ValueError):
            rendered = "-"
        lines.append(f"| {_markdown_result_cell(item.get('label'))} | {rendered} |")
    return "\n".join(lines)


def _build_series_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """낙찰 지표 시계열은 LLM 없이 DB 시계열 표로 직접 답합니다.

    시계열 딕셔너리에는 avg_rate, bid_count, announcement_count 가 함께
    있습니다. 요청 지표의 열만 골라 렌더링하고 원시 키 이름은 답에 쓰지
    않습니다. 값이 모두 없으면 빈 문자열을 돌려 기존 경로로 넘깁니다.
    """
    if not structured_data:
        return ""
    summary = structured_data.get("summary") or {}
    meta = summary.get("aggregate_meta") or {}
    series = summary.get("time_series") or []
    if not series:
        return ""

    if str(meta.get("metric") or "") == "announcement_count":
        return _build_announcement_series_answer(series)
    metric = _resolve_series_metric(plan, meta)
    if not metric:
        return ""
    if all(item.get(metric) is None for item in series):
        return ""

    period = str(series[0].get("period") or "quarter")
    period_label, unit_label = _series_period_labels(period)
    metric_label = METRIC_LABELS[metric]
    lines = [f"{period_label} {metric_label} 추이입니다."]
    period_text = _series_period_text(plan, structured_data)
    if period_text:
        lines.append(f"기간: {period_text}")
    lines.append("")
    if metric == "avg_rate":
        lines.extend([f"| {unit_label} | 평균 낙찰률 | 낙찰 건수 |", "| --- | ---: | ---: |"])
        for item in series:
            lines.append(
                f"| {_series_label_cell(item, period)} "
                f"| {_format_series_cell('avg_rate', item.get('avg_rate'))} "
                f"| {_format_series_cell('bid_count', item.get('bid_count'))} |"
            )
    else:
        lines.extend([f"| {unit_label} | 낙찰 건수 |", "| --- | ---: |"])
        for item in series:
            lines.append(
                f"| {_series_label_cell(item, period)} "
                f"| {_format_series_cell('bid_count', item.get('bid_count'))} |"
            )
    return "\n".join(lines)


COMPARISON_DIMENSION_LABELS = {
    "region": "지역",
    "institution": "기관",
}


def _build_comparison_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """지역·기관 비교는 요청한 지표 하나만 표로 냅니다.

    공고 건수 비교에 낙찰 건수를 함께 놓으면 지표 혼동이 재발합니다. 나머지
    값은 summary["comparison"] 에 남기고 화면에는 요청 지표 열만 냅니다.
    """
    if not structured_data:
        return ""
    summary = structured_data.get("summary") or {}
    rows = summary.get("comparison") or []
    meta = summary.get("comparison_meta") or {}
    dimension = str(meta.get("dimension") or "")
    metric = str(meta.get("metric") or "")
    if not rows or dimension not in COMPARISON_DIMENSION_LABELS or metric not in METRIC_LABELS:
        return ""

    dimension_label = COMPARISON_DIMENSION_LABELS[dimension]
    metric_label = METRIC_LABELS[metric]
    lines = [
        f"{dimension_label}별 {metric_label} 비교입니다.",
        "",
        f"| {dimension_label} | {metric_label} |",
        "| --- | ---: |",
    ]
    for item in rows:
        lines.append(
            f"| {_markdown_result_cell(item.get('label'))} | "
            f"{_format_axis_value(metric, item.get(metric))} |"
        )
    return "\n".join(lines)


SINGLE_METRIC_LABELS = {
    "bid_count": "낙찰 건수는",
    "announcement_count": "공고는",
    "avg_rate": "평균 낙찰률은",
}
# 단일 지표 직접 응답이 답하면 안 되는 질문입니다. 순위·경쟁률·추세·설명형은
# 값 하나로 답할 수 없거나 다른 경로가 맡습니다. 설명형은 값(얼마야, 몇 건이야)이
# 아니라 뜻·정의·산식·이유를 묻는 표지로 넓게 잡습니다.
SINGLE_METRIC_EXCLUDED_MARKERS = (
    "경쟁률",
    "순위",
    "업체별",
    "상위",
    "top",
    "비율",
    "분포",
    "추세",
    "추이",
    "흐름",
    "변화",
    "상승",
    "하락",
    "올랐",
    "내렸",
    "증가",
    "감소",
    "월별",
    "분기별",
    "비교",
    "대비",
    "차이",
    "많이",
    "뜻",
    "무슨",
    "무엇",
    "뭐야",
    "의미",
    "정의",
    "개념",
    "이란",
    "란 무엇",
    "기준이",
    "산식",
    "공식",
    "계산",
    "구하는",
    "왜",
    "어떻게",
    "이유",
    "원인",
    "설명",
    "방법",
    "절차",
)


def _format_single_metric_period(filters: dict) -> str:
    date_from = _normalize_text(str(filters.get("date_from") or ""))
    date_to = _normalize_text(str(filters.get("date_to") or ""))
    if date_from and date_to:
        return f"{date_from} ~ {date_to}"
    if date_from:
        return f"{date_from} 이후"
    if date_to:
        return f"{date_to} 이전"
    relative_years = int(filters.get("relative_years") or 0)
    if relative_years:
        return f"최근 {relative_years}년"
    return "전체 기간"


def _build_single_metric_answer(
    plan: RetrievalPlan,
    structured_data: dict | None,
) -> str:
    """기간·분류가 걸린 단일 지표 질의는 DB 집계값을 문장 하나로 냅니다.

    목록·축·시계열·비교·공고번호 단건은 각자의 직접 응답이 먼저 처리합니다.
    여기서는 지표가 하나로 정해지고 summary 에 그 값이 있을 때만 답합니다.
    값이 None 이면 빈 문자열을 돌려 LLM 경로로 넘깁니다. 0 은 측정값이므로
    그대로 답합니다.
    """
    if not plan.use_sql or not isinstance(structured_data, dict):
        return ""
    if structured_data.get("query_skipped"):
        return ""

    summary = structured_data.get("summary")
    if not isinstance(summary, dict) or not summary:
        return ""

    plan_filters = dict(plan.filters or {})
    for key in ("result_limit", "announcement_limit", "bid_ntce_no", "group_by", "time_bucket"):
        if plan_filters.get(key):
            return ""
    if plan_filters.get("analysis_mode") == "trend":
        return ""
    if (
        summary.get("axis_breakdown")
        or summary.get("comparison")
        or summary.get("comparison_meta")
        or summary.get("bid_detail")
        or summary.get("by_institution")
        or summary.get("time_series")
    ):
        return ""

    query = _normalize_text(plan.semantic_query).lower()
    if any(marker in query for marker in LIST_REQUEST_MARKERS):
        return ""
    if any(marker in query for marker in SINGLE_METRIC_EXCLUDED_MARKERS):
        return ""

    metric = _single_metric(query)
    if metric not in SINGLE_METRIC_LABELS:
        return ""

    value_key = {
        "bid_count": "total_bids",
        "announcement_count": "announcement_count",
        "avg_rate": "average_winning_rate",
    }[metric]
    value = summary.get(value_key)
    if value is None:
        return ""
    try:
        rendered = f"{float(value):.2f}%" if metric == "avg_rate" else f"{int(value):,}건"
    except (TypeError, ValueError):
        return ""

    filters = dict(structured_data.get("filters") or {})
    for key, filter_value in plan_filters.items():
        if filter_value not in (None, ""):
            filters[key] = filter_value

    subject = [_format_single_metric_period(filters)]
    region_names = filters.get("region_names")
    institution_names = filters.get("institution_names")
    institution_name = str(filters.get("institution_name") or "")
    if isinstance(region_names, list) and region_names:
        subject.append(", ".join(str(name) for name in region_names))
    elif isinstance(institution_names, list) and institution_names:
        subject.append(", ".join(str(name) for name in institution_names))
    elif institution_name:
        subject.append(institution_name)

    category = _normalize_text(str(plan_filters.get("category") or filters.get("category") or ""))
    if category:
        category_label = _category_label(category)
        if category_label and category_label != "-":
            subject.append(category_label)

    answer = f"{' '.join(subject)} {SINGLE_METRIC_LABELS[metric]} {rendered}입니다."
    unapplied_notice = unapplied_result_condition_notice(
        structured_data.get("unapplied_conditions") or []
    )
    if unapplied_notice:
        answer += f"\n{unapplied_notice}"
    return answer


def _compose_context_text(
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    sections = [f"검색 라우팅: {plan.route_reason}"]
    formatted_filters = _format_filters_for_prompt(plan.filters)
    if formatted_filters:
        sections.append(f"적용 필터:\n{formatted_filters}")

    query_text = plan.lexical_query if plan.lexical_query else plan.semantic_query
    if query_text and any(term in query_text for term in ("예정가격", "추정가격", "기초금액")):
        sections.append("금액 용어 안내 (시스템 기준 정의, 인용 번호 없음):\n" + PRICE_TERM_NOTES)

    # 통계 및 수치 데이터 (Source [1])
    statistical_snapshot = _extract_statistical_snapshot(structured_data)
    if statistical_snapshot:
        sections.append(f"Source [1] (통계/수치):\n{statistical_snapshot}")

    # 추세 분석 (Source [2])
    trend_snapshot = _extract_trend_snapshot(
        (structured_data or {}).get("trend_analysis") if structured_data else None
    )
    if trend_snapshot:
        sections.append(f"Source [2] (추세 분석):\n{trend_snapshot}")

    # 문맥/의미 검색 결과 (Source [3], [4], [5])
    if vector_docs:
        semantic_lines = ["문맥 검색 결과:"]
        for i, item in enumerate(vector_docs[:3], start=3):
            snippet = _normalize_text(str(item.get("document") or ""))
            if len(snippet) > 250:
                snippet = f"{snippet[:250]}..."
            semantic_lines.append(f"Source [{i}]: {snippet}")
        sections.append("\n".join(semantic_lines))

    # KB 메타데이터 (Source [6])
    kb_snapshot = _extract_kb_snapshot(kb_status)
    if kb_snapshot:
        sections.append(f"Source [6] (지식베이스 상태):\n{kb_snapshot}")

    insufficiency_hints = list(plan.insufficiency_hints)
    if structured_data:
        insufficiency_hints.extend(structured_data.get("insufficiency_hints") or [])
    if not vector_docs and plan.use_vector:
        insufficiency_hints.append("문맥 검색 결과가 충분하지 않습니다.")

    if insufficiency_hints:
        sections.append(
            "한계 및 주의:\n"
            + "\n".join(f"- {item}" for item in dict.fromkeys(insufficiency_hints))
        )

    return "\n\n".join(section for section in sections if section)


def _build_source_citation_from_context(
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    has_sql_evidence = bool(structured_data and not structured_data.get("query_skipped"))
    if has_sql_evidence and vector_docs:
        return "\n\n근거: 혼합 근거"
    if vector_docs:
        return "\n\n근거: Chroma 문맥 기반"
    if has_sql_evidence or kb_status:
        return "\n\n근거: DB 집계 기반"
    return ""


def _fallback_answer(
    query: str,
    plan: RetrievalPlan,
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> str:
    lines = [f"질문: {query}"]
    query_skipped = bool(structured_data and structured_data.get("query_skipped"))
    summary = structured_data.get("summary") if structured_data else {}

    if query_skipped:
        lines.append("- 조회를 수행하지 않아 통계가 없습니다.")
    elif summary:
        lines.append(
            f"- 낙찰 결과 {_stat_text(summary.get('total_bids'))}건, "
            f"공고 {_stat_text(summary.get('announcement_count'))}건, "
            f"평균 낙찰률 {_stat_text(summary.get('average_winning_rate'))}"
        )
        top_winners = summary.get("top_winners") or []
        if top_winners:
            top_line = ", ".join(
                f"{item.get('bidwinnr_nm') or '-'} {item.get('win_count', 0)}건"
                for item in top_winners[:3]
            )
            lines.append(f"- 상위 낙찰 업체: {top_line}")

        recent_results = summary.get("recent_results") or []
        latest_available_result_at = summary.get("latest_available_result_at")
        if latest_available_result_at:
            lines.append(f"- DB 최신 개찰일: {latest_available_result_at}")
        if recent_results:
            lines.append("- 최근 낙찰 결과:")
            for index, item in enumerate(recent_results, start=1):
                lines.append(
                    f"  {index}. {item.get('bid_ntce_nm') or '-'} | "
                    f"{item.get('dminstt_nm') or '-'} | "
                    f"{item.get('bidwinnr_nm') or '-'} | "
                    f"{item.get('sucsf_bid_amt') or '-'}원 | "
                    f"{item.get('sucsf_bid_rate') or '-'}%"
                )

    if vector_docs:
        snippet = _normalize_text(str(vector_docs[0].get("document") or ""))
        if len(snippet) > 200:
            snippet = f"{snippet[:200]}..."
        lines.append(f"- 문맥 참고: {snippet}")

    if kb_status:
        lines.append(
            f"- KB 색인 상태: {kb_status.get('status') or 'unknown'} / "
            f"원본 문서 {kb_status.get('source_bid_count', 0)}건"
        )

    insufficiency_hints = list(plan.insufficiency_hints)
    if structured_data:
        insufficiency_hints.extend(structured_data.get("insufficiency_hints") or [])
    if insufficiency_hints:
        lines.append("- 한계: " + " / ".join(dict.fromkeys(insufficiency_hints)))

    return "\n".join(lines) + _build_source_citation_from_context(
        structured_data, vector_docs, kb_status
    )


def _stat_text(value) -> str:
    """0 은 측정값, None 은 값 없음. 값 없음을 0 으로 표기하지 않습니다."""
    return "확인되지 않음" if value is None else str(value)


def _build_evidence_items(
    structured_data: dict | None,
    vector_docs: list[dict],
    kb_status: dict | None,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    # 조회를 수행하지 않았는데 통계 Source 를 만들면, 모델과 사용자 모두
    # "조회했더니 이런 값이 나왔다" 로 읽습니다. 근거가 없으므로 만들지 않습니다.
    # 건너뛴 사유는 Provenance 의 insufficiency_hints 로 이미 전달됩니다.
    if structured_data and not structured_data.get("query_skipped"):
        summary = structured_data.get("summary") or {}
        items.append(
            EvidenceItem(
                id="sql_summary",
                type="sql_stats",
                content=summary,
                metadata={
                    "filters": structured_data.get("filters", {}),
                    "citation_number": 1,
                    "citation_label": "Source [1]",
                    "citation_role": "통계/수치",
                },
            )
        )
        for i, sample in enumerate(summary.get("sample_announcements") or []):
            items.append(
                EvidenceItem(
                    id=f"bid_{sample.get('bid_ntce_no', i)}",
                    type="sql_stats",
                    content=sample,
                    metadata={
                        "source": "BidAnnouncement",
                        "citation_number": 1,
                        "citation_label": "Source [1]",
                        "citation_role": "통계/수치 상세 공고",
                    },
                )
            )
        for i, result in enumerate(summary.get("recent_results") or []):
            items.append(
                EvidenceItem(
                    id=f"result_{result.get('bid_ntce_no') or i}",
                    type="sql_stats",
                    content=result,
                    metadata={
                        "source": "BidResult",
                        "citation_number": 1,
                        "citation_label": "Source [1]",
                        "citation_role": "최근 낙찰 결과 목록",
                    },
                )
            )
        trend_analysis = structured_data.get("trend_analysis") or {}
        if trend_analysis:
            items.append(
                EvidenceItem(
                    id="trend_analysis",
                    type="sql_stats",
                    content=trend_analysis,
                    metadata={
                        "source": "TrendAnalysis",
                        "citation_number": 2,
                        "citation_label": "Source [2]",
                        "citation_role": "추세 분석",
                    },
                )
            )

    for i, doc in enumerate(vector_docs):
        metadata = dict(doc.get("metadata") or {})
        citation_number = i + 3
        metadata.update(
            {
                "citation_number": citation_number,
                "citation_label": f"Source [{citation_number}]",
                "citation_role": "문맥 검색",
            }
        )
        items.append(
            EvidenceItem(
                id=f"vec_{i}",
                type="vector_snippet",
                content=doc.get("document", ""),
                metadata=metadata,
                relevance_score=doc.get("distance"),
            )
        )

    if kb_status:
        items.append(
            EvidenceItem(
                id="kb_meta",
                type="kb_metadata",
                content=kb_status,
                metadata={
                    "citation_number": 6,
                    "citation_label": "Source [6]",
                    "citation_role": "지식베이스 상태",
                },
            )
        )
    return items
