"""
src/rag/snapshots.py

RAG 컨텍스트 구성을 위한 정형/문맥/KB/추세 스냅샷 텍스트 추출 모듈.
"""

from __future__ import annotations

from src.rag.query_planning import _normalize_text


def _stat_value_text(value) -> str:
    """0 은 측정값, None 은 값 없음. 값 없음은 0 으로 표기하지 않는다."""
    if value is None:
        return "확인되지 않음"
    return str(value)


def _extract_statistical_snapshot(structured_data: dict | None) -> str:
    if not structured_data:
        return ""

    if structured_data.get("query_skipped"):
        lines = ["정형 데이터 집계: 조회를 수행하지 않아 통계가 없습니다."]
        for item in structured_data.get("insufficiency_hints") or []:
            lines.append(f"- 한계: {item}")
        return "\n".join(lines)

    summary = structured_data.get("summary") or {}
    lines = [
        "정형 데이터 집계:",
        f"- 낙찰 결과 수: {_stat_value_text(summary.get('total_bids'))}",
        f"- 공고 수: {_stat_value_text(summary.get('announcement_count'))}",
        f"- 평균 낙찰률: {_stat_value_text(summary.get('average_winning_rate'))}",
        f"- 총 낙찰 금액: {_stat_value_text(summary.get('total_winning_amount'))}",
    ]

    top_winners = summary.get("top_winners") or []
    if top_winners:
        winner_snapshot = ", ".join(
            f"{item.get('bidwinnr_nm') or '-'}({item.get('win_count', 0)}건)"
            for item in top_winners[:3]
        )
        lines.append(f"- 상위 낙찰 업체: {winner_snapshot}")

    top_institutions = summary.get("top_institutions") or []
    if top_institutions:
        inst_snapshot = ", ".join(
            f"{item.get('dminstt_nm') or '-'}({item.get('ntce_count', 0)}건)"
            for item in top_institutions[:3]
        )
        lines.append(f"- 빈번 공고 기관: {inst_snapshot}")

    top_announcements = summary.get("top_announcements") or []
    if top_announcements:
        ntce_snapshot = ", ".join(
            f"{item.get('bid_ntce_nm') or '-'}({item.get('ntce_count', 0)}건)"
            for item in top_announcements[:3]
        )
        lines.append(f"- 자주 올라오는 공고 명칭: {ntce_snapshot}")

    recent_results = summary.get("recent_results") or []
    latest_available_result_at = summary.get("latest_available_result_at")
    if latest_available_result_at:
        lines.append(f"- 해당 조건의 DB 최신 개찰일: {latest_available_result_at}")
    if recent_results:
        lines.append("- 최근 낙찰 결과 목록:")
        for index, item in enumerate(recent_results, start=1):
            lines.append(
                f"  - {index}. 공고명={item.get('bid_ntce_nm') or '-'} / "
                f"공고번호={item.get('bid_ntce_no') or '-'} / "
                f"수요기관={item.get('dminstt_nm') or '-'} / "
                f"낙찰업체={item.get('bidwinnr_nm') or '-'} / "
                f"낙찰금액={item.get('sucsf_bid_amt') or '-'}원 / "
                f"낙찰률={item.get('sucsf_bid_rate') or '-'}% / "
                f"개찰일={item.get('rl_openg_dt') or '-'}"
            )

    time_series = summary.get("time_series") or []
    if time_series:
        period_label = "일별" if (time_series[0].get("period") == "day") else "월별"
        lines.append(f"- {period_label} 추세:")
        for row in time_series[-6:]:
            lines.append(
                f"  - {row.get('label') or row.get('month')}: "
                f"avg_rate={row.get('avg_rate', 0)}, bid_count={row.get('bid_count', 0)}"
            )

    for item in structured_data.get("insufficiency_hints") or []:
        lines.append(f"- 한계: {item}")
    return "\n".join(lines)


def _extract_semantic_snapshot(vector_docs: list[dict]) -> str:
    if not vector_docs:
        return ""

    lines = ["문맥 검색 결과:"]
    for item in vector_docs[:3]:
        snippet = _normalize_text(str(item.get("document") or ""))
        if len(snippet) > 220:
            snippet = f"{snippet[:220]}..."
        lines.append(f"- {snippet}")
    return "\n".join(lines)


def _extract_kb_snapshot(kb_status: dict | None) -> str:
    if not kb_status:
        return ""

    return "\n".join(
        [
            "KB 색인 상태:",
            f"- 상태: {kb_status.get('status') or 'unknown'}",
            f"- 색인된 원본 문서 수: {kb_status.get('source_bid_count', 0)}",
            f"- 마지막 파이프라인: {kb_status.get('last_pipeline_run_id') or '-'}",
        ]
    )


def _extract_trend_snapshot(trend_analysis: dict | None) -> str:
    if not trend_analysis:
        return ""

    lines = ["추세 분석:"]
    summary_text = str(trend_analysis.get("summary_text") or "").strip()
    if summary_text:
        lines.append(f"- {summary_text}")

    direction = str(trend_analysis.get("direction") or "").strip()
    if direction:
        lines.append(f"- 방향: {direction}")

    peak = trend_analysis.get("peak") or {}
    trough = trend_analysis.get("trough") or {}
    if peak:
        lines.append(f"- 최고 구간: {peak.get('label') or '-'} / {peak.get('value', 0)}")
    if trough:
        lines.append(f"- 최저 구간: {trough.get('label') or '-'} / {trough.get('value', 0)}")
    return "\n".join(lines)
