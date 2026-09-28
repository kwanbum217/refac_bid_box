"""
src/app/services/result_coverage.py

개찰 완료 공고 대비 낙찰결과 매칭률 집계와 경고 판정.

2026-09-26 C1 분석(docs/analysis/result_collection_gap_20260926.md 6절 R3)에서
대형 공고 낙찰결과가 조달청 API 쪽에서 미등록·지연되어 매칭률이 급락했지만,
수집 적재 건수만 보는 감시로는 잡히지 않았다. 이 모듈은 매칭률 자체를
분류 x 개찰 주 x 규모(대형/소형)로 계산해 전년 동기와 비교한다.

2026-09-28 물품 경고 보정(docs/analysis/thng_match_rate_20260824.md 8절)에서
전년 단일 주 기저의 국지 변동과 입찰방식 구성 변화가 오탐을 키운다는 판정에
따라 세 가지를 적용했다(사용자 채택 A1·A2·A6).

- A1: 전년 기저를 364일 전 주 중심 앞뒤 BASELINE_WINDOW_WEEKS 주, 총 5주
  합산 비율로 넓힌다(주별 비율의 단순 평균이 아니다).
- A2: 대형 행에 기저 5주의 방식 구성비로 현재 주 방식별 매칭률을 가중한
  adjusted_rate 를 추가한다.
- A6: 분류별 최근 성숙 주와 직전 성숙 주가 모두 조건을 만족할 때만 경고한다.

2026-09-28 차수 불일치(docs/analysis/ord_mismatch_20260928.md)에서 변경공고로 옛
차수 공고 행이 남아 분모가 부풀려진다고 판정했다. 정본 정의는 그대로 두고, 같은
공고번호·분류의 여러 차수 행 중 최신 차수 행 하나만 세는 보조 지표 notice_* 를
각 행에 병행 산출한다. 보조 지표는 5주 기저·보정률·경고 판정에 쓰지 않는다.

2026-09-28 용역 대형 상류 공백 재조사(docs/analysis/servc_upstream_recheck_20260928.md)
에서 원인이 조달청 상류 영구 누락 우세로 확인된 경고가 매주 반복되어 다른 새 경고를
묻는다는 판정에 따라, 원인이 확인된 경고를 만료일까지 알림에서 빼는 임시 억제를
추가했다. 판정 규칙(5주 기저·방식 보정·2주 연속)은 바꾸지 않으며, 억제 대상도
판정 결과에는 suppressed 표시와 함께 남는다. 기본값은 억제 없음이다.

읽기 전용 함수다. DB 쓰기는 하지 않는다. openg_dt 에 인덱스가 없으므로 공고
조회는 반드시 bid_ntce_dt 범위(ix_bid_ann_dt_cat)로 먼저 좁힌 뒤 openg_dt
조건을 더한다. 차수 정규화와 주 집계는 파이썬에서 해 SQLite 테스트와 동작을
같게 유지한다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult

logger = logging.getLogger(__name__)

LARGE_PRICE_THRESHOLD = 230_000_000
MIN_WEEK_SAMPLES = 100
RATE_DROP_ALERT = 0.10
NOTICE_LOOKBACK_DAYS = 365

TARGET_CATEGORIES = ("Servc", "Cnstwk", "Thng")

MYSQL_EXECUTION_LIMIT_HINT = "/*+ MAX_EXECUTION_TIME(120000) */"
CANCELLED_NTCE_KIND = "취소공고"
BASELINE_OFFSET_DAYS = 364
# 전년 기저를 364일 전 주 중심 앞뒤 2주, 총 5주 합산으로 넓힌다(A1).
BASELINE_WINDOW_WEEKS = 2
# 분류별 최근 성숙 주와 직전 성숙 주가 연속으로 조건을 만족해야 경고한다(A6).
CONSECUTIVE_ALERT_WEEKS = 2
NULL_METHOD_LABEL = "(null)"

BAND_LARGE = "large"
BAND_SMALL = "small"

# 임시 억제는 규모 large 만 허용합니다. 경고 판정 자체가 대형 행에서만 나오므로
# 소형·기타 표기는 설정 실수로 보고 무시합니다.
SUPPRESS_ALLOWED_BANDS = (BAND_LARGE,)
SUPPRESS_FIELD_COUNT = 3


def normalize_ord(value: Any) -> str:
    """차수를 앞뒤 공백 제거, 선행 0 제거, 3자리 왼쪽 0 채움으로 정규화한다.

    '000'->'000', '0'->'000', '1'->'001', '001'->'001', ' 2 '->'002'.
    """
    text = str(value or "").strip()
    return (text.lstrip("0") or "0").zfill(3)


def week_start(day: date) -> date:
    """주 시작(월요일)을 돌려준다."""
    return day - timedelta(days=day.weekday())


def _mature_week_starts(as_of: date, weeks: int, min_elapsed_days: int) -> list[date]:
    """성숙 주(주 끝 날이 as_of - min_elapsed_days 이하) 시작 목록을 최신부터 돌려준다."""
    latest_limit = as_of - timedelta(days=min_elapsed_days)
    start = week_start(latest_limit - timedelta(days=6))
    return [start - timedelta(days=7 * i) for i in range(max(weeks, 0))]


def _rate(matched: int, announcements: int) -> float | None:
    if announcements <= 0:
        return None
    return matched / announcements


def _baseline_window(center: date) -> list[date]:
    """364일 전 주를 중심으로 앞뒤 BASELINE_WINDOW_WEEKS 주 시작 목록을 돌려준다."""
    return [
        center + timedelta(days=7 * offset)
        for offset in range(-BASELINE_WINDOW_WEEKS, BASELINE_WINDOW_WEEKS + 1)
    ]


def _with_mysql_execution_limit(stmt: Any) -> Any:
    return stmt.prefix_with(MYSQL_EXECUTION_LIMIT_HINT, dialect="mysql")


def _query_blocks(mature_starts: list[date]) -> list[tuple[date, date]]:
    """현재 성숙 주 블록과 전년 동기 5주 기저 블록을 만들고 겹치거나 맞닿으면 합친다.

    각 블록은 (블록 시작, 블록 끝)이며 블록 끝은 그 목록의 가장 늦은 주 시작 + 6일이다.
    전년 블록은 5주 기저를 덮도록 양끝을 7 * BASELINE_WINDOW_WEEKS 일씩 넓힌다.
    """
    baseline_starts = [s - timedelta(days=BASELINE_OFFSET_DAYS) for s in mature_starts]
    margin = timedelta(days=7 * BASELINE_WINDOW_WEEKS)
    blocks = sorted(
        [
            (min(baseline_starts) - margin, max(baseline_starts) + timedelta(days=6) + margin),
            (min(mature_starts), max(mature_starts) + timedelta(days=6)),
        ]
    )
    merged: list[tuple[date, date]] = [blocks[0]]
    for start, end in blocks[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= timedelta(days=1):
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _sum_band_counts(
    counts: dict[tuple[str, date, str], list[int]],
    category: str,
    band: str,
    weeks: list[date],
) -> tuple[int, int]:
    announcements = matched = 0
    for week in weeks:
        bucket = counts.get((category, week, band), [0, 0])
        announcements += bucket[0]
        matched += bucket[1]
    return announcements, matched


def _sum_method_counts(
    counts: dict[tuple[str, date, str, str], list[int]],
    category: str,
    band: str,
    weeks: list[date],
) -> dict[str, list[int]]:
    week_set = set(weeks)
    agg: dict[str, list[int]] = {}
    for (cat, week, bnd, method), bucket in counts.items():
        if cat != category or bnd != band or week not in week_set:
            continue
        target = agg.setdefault(method, [0, 0])
        target[0] += bucket[0]
        target[1] += bucket[1]
    return agg


def _adjusted_rate(
    current_methods: dict[str, list[int]],
    baseline_weights: dict[str, float],
    overall_rate: float,
) -> float | None:
    """기저 방식 구성비로 현재 주 방식별 매칭률을 가중합한다(A2).

    현재 주에 공고가 없는 방식은 현재 주 전체 매칭률(overall_rate)로 대체한다.
    """
    if not baseline_weights:
        return None
    total = 0.0
    for method, weight in baseline_weights.items():
        current = current_methods.get(method)
        if current is None or current[0] <= 0:
            method_rate = overall_rate
        else:
            method_rate = current[1] / current[0]
        total += weight * method_rate
    return total


def _notice_band_counts(
    announcement_rows: list[Any],
    result_keys: set[tuple[str, str, str]],
    target_weeks: set[date],
) -> dict[tuple[str, date, str], list[int]]:
    """공고번호·분류 단위 보조 지표용 (분류, 주, 규모) 집계를 만든다.

    같은 (bid_ntce_no, category) 의 여러 차수 공고 행 중 정규화 차수가 가장 큰
    행 하나만 대표로 남긴다. 대표 행의 openg_dt 로 개찰 주를, presmpt_prce 로
    규모를 정하고, 그 행의 (공고번호, 분류, 정규화 차수) 가 낙찰결과에 있는지로
    매칭한다. 조회 블록 경계에 걸려 target_weeks 밖인 주는 기존 집계와 같이 세지
    않는다. 분류가 다르면 서로 다른 공고로 센다.
    """
    latest: dict[tuple[str, str], tuple[str, Any]] = {}
    for row in announcement_rows:
        key = (row[0], row[2])
        ord_norm = normalize_ord(row[1])
        current = latest.get(key)
        if current is None or ord_norm > current[0]:
            latest[key] = (ord_norm, row)

    counts: dict[tuple[str, date, str], list[int]] = {}
    for ord_norm, row in latest.values():
        _no, _ord, category, presmpt_prce, openg_dt, _method = row
        if openg_dt is None:
            continue
        start = week_start(openg_dt.date())
        if start not in target_weeks:
            continue
        band = BAND_LARGE if (presmpt_prce or 0) >= LARGE_PRICE_THRESHOLD else BAND_SMALL
        bucket = counts.setdefault((category, start, band), [0, 0])
        bucket[0] += 1
        if (row[0], category, ord_norm) in result_keys:
            bucket[1] += 1
    return counts


def compute_result_match_rates(
    db: Session,
    *,
    as_of: date,
    weeks: int = 8,
    min_elapsed_days: int = 28,
) -> list[dict[str, Any]]:
    """분류 x 성숙 개찰 주 x 규모별 매칭률과 전년 동기 매칭률을 계산한다.

    공고는 openg_dt 가 개찰 주(월요일 시작 7일) 안에 들고 ntce_kind_nm 이
    '취소공고' 가 아닌 것(NULL 포함)만 센다. 대형은 presmpt_prce >=
    LARGE_PRICE_THRESHOLD, 그 밖(NULL 포함)은 소형이다. 매칭은
    (bid_ntce_no, category, 정규화 차수)가 낙찰결과에 존재하는 것이다.

    반환 행의 baseline_* 필드는 364일 전 같은 주 단일 주 값이고,
    baseline_multi_* 필드는 그 주를 중심으로 앞뒤 BASELINE_WINDOW_WEEKS 주를
    합산한 값이다(A1). 대형 행의 adjusted_rate 는 기저 5주의 방식 구성비로
    현재 주 방식별 매칭률을 가중한 보정률이다(A2). 소형 행과 현재 주 공고가
    0 인 행, 기저 5주 공고가 0 인 행은 adjusted_rate 가 None 이다.

    notice_* 필드는 같은 공고번호·분류의 여러 차수 공고 행 중 정규화 차수가 가장
    큰 행 하나만 센 보조 지표다. notice_rate 는 notice_matched / notice_announcements
    이고, baseline_notice_* 는 364일 전 같은 단일 주에서 같은 방식으로 센 값이다.
    보조 지표는 기존 필드와 adjusted_rate, 경고 판정에 쓰지 않는다.

    조회는 현재 성숙 주 구간과 전년 동기 5주 구간 두 블록으로 좁혀 각 블록마다
    공고는 bid_ntce_dt 를 [블록 시작 - NOTICE_LOOKBACK_DAYS 일, 블록 끝], openg_dt 를
    [블록 시작, 블록 끝]로, 결과는 rl_openg_dt 를 [블록 시작 - 14일,
    블록 끝 + 90일]로 가져온다. 두 블록이 겹치거나 맞닿으면 하나로 합친다.
    """
    mature_starts = _mature_week_starts(as_of, weeks, min_elapsed_days)
    if not mature_starts:
        return []

    baseline_windows: dict[date, list[date]] = {}
    target_weeks: set[date] = set(mature_starts)
    for start in mature_starts:
        window = _baseline_window(start - timedelta(days=BASELINE_OFFSET_DAYS))
        baseline_windows[start] = window
        target_weeks.update(window)

    announcement_rows: list[Any] = []
    result_rows: list[Any] = []
    for block_start, block_end in _query_blocks(mature_starts):
        block_start_dt = datetime.combine(block_start, time.min)
        block_end_dt = datetime.combine(block_end, time.max)
        announcement_rows.extend(
            _with_mysql_execution_limit(
                db.query(
                    BidAnnouncement.bid_ntce_no,
                    BidAnnouncement.bid_ntce_ord,
                    BidAnnouncement.category,
                    BidAnnouncement.presmpt_prce,
                    BidAnnouncement.openg_dt,
                    BidAnnouncement.bid_methd_nm,
                ).filter(
                    BidAnnouncement.bid_ntce_dt
                    >= datetime.combine(
                        block_start - timedelta(days=NOTICE_LOOKBACK_DAYS), time.min
                    ),
                    BidAnnouncement.bid_ntce_dt <= block_end_dt,
                    BidAnnouncement.openg_dt >= block_start_dt,
                    BidAnnouncement.openg_dt <= block_end_dt,
                    BidAnnouncement.category.in_(TARGET_CATEGORIES),
                    or_(
                        BidAnnouncement.ntce_kind_nm.is_(None),
                        BidAnnouncement.ntce_kind_nm != CANCELLED_NTCE_KIND,
                    ),
                )
            ).all()
        )
        result_rows.extend(
            _with_mysql_execution_limit(
                db.query(
                    BidResult.bid_ntce_no,
                    BidResult.bid_ntce_ord,
                    BidResult.category,
                ).filter(
                    BidResult.category.in_(TARGET_CATEGORIES),
                    BidResult.rl_openg_dt
                    >= datetime.combine(block_start - timedelta(days=14), time.min),
                    BidResult.rl_openg_dt
                    <= datetime.combine(block_end + timedelta(days=90), time.max),
                )
            ).all()
        )
    result_keys = {(no, category, normalize_ord(ord_)) for no, ord_, category in result_rows}

    band_counts: dict[tuple[str, date, str], list[int]] = {}
    method_counts: dict[tuple[str, date, str, str], list[int]] = {}
    for row in announcement_rows:
        no, ord_, category, presmpt_prce, openg_dt, bid_methd_nm = row
        if openg_dt is None:
            continue
        start = week_start(openg_dt.date())
        if start not in target_weeks:
            continue
        band = BAND_LARGE if (presmpt_prce or 0) >= LARGE_PRICE_THRESHOLD else BAND_SMALL
        method = bid_methd_nm if bid_methd_nm is not None else NULL_METHOD_LABEL
        is_matched = (no, category, normalize_ord(ord_)) in result_keys
        band_bucket = band_counts.setdefault((category, start, band), [0, 0])
        band_bucket[0] += 1
        method_bucket = method_counts.setdefault((category, start, band, method), [0, 0])
        method_bucket[0] += 1
        if is_matched:
            band_bucket[1] += 1
            method_bucket[1] += 1

    notice_band_counts = _notice_band_counts(announcement_rows, result_keys, target_weeks)

    rows: list[dict[str, Any]] = []
    for start in sorted(mature_starts):
        center = start - timedelta(days=BASELINE_OFFSET_DAYS)
        window = baseline_windows[start]
        for category in TARGET_CATEGORIES:
            for band in (BAND_LARGE, BAND_SMALL):
                announcements, matched = band_counts.get((category, start, band), [0, 0])
                baseline_announcements, baseline_matched = band_counts.get(
                    (category, center, band), [0, 0]
                )
                baseline_multi_announcements, baseline_multi_matched = _sum_band_counts(
                    band_counts, category, band, window
                )
                rate = _rate(matched, announcements)
                baseline_multi_rate = _rate(baseline_multi_matched, baseline_multi_announcements)
                notice_announcements, notice_matched = notice_band_counts.get(
                    (category, start, band), [0, 0]
                )
                baseline_notice_announcements, baseline_notice_matched = notice_band_counts.get(
                    (category, center, band), [0, 0]
                )
                adjusted_rate = None
                if (
                    band == BAND_LARGE
                    and announcements > 0
                    and baseline_multi_announcements > 0
                    and rate is not None
                ):
                    baseline_methods = _sum_method_counts(method_counts, category, band, window)
                    current_methods = _sum_method_counts(method_counts, category, band, [start])
                    baseline_weights = {
                        method: counts[0] / baseline_multi_announcements
                        for method, counts in baseline_methods.items()
                        if counts[0] > 0
                    }
                    adjusted_rate = _adjusted_rate(current_methods, baseline_weights, rate)
                rows.append(
                    {
                        "category": category,
                        "week_start": start.isoformat(),
                        "band": band,
                        "announcements": announcements,
                        "matched": matched,
                        "rate": rate,
                        "baseline_announcements": baseline_announcements,
                        "baseline_matched": baseline_matched,
                        "baseline_rate": _rate(baseline_matched, baseline_announcements),
                        "baseline_multi_announcements": baseline_multi_announcements,
                        "baseline_multi_matched": baseline_multi_matched,
                        "baseline_multi_rate": baseline_multi_rate,
                        "adjusted_rate": adjusted_rate,
                        "notice_announcements": notice_announcements,
                        "notice_matched": notice_matched,
                        "notice_rate": _rate(notice_matched, notice_announcements),
                        "baseline_notice_announcements": baseline_notice_announcements,
                        "baseline_notice_matched": baseline_notice_matched,
                        "baseline_notice_rate": _rate(
                            baseline_notice_matched, baseline_notice_announcements
                        ),
                    }
                )
    return rows


def parse_alert_suppressions(text: str | None) -> dict[tuple[str, str], date]:
    """임시 억제 설정 문자열을 (분류, 규모) -> 만료일 사전으로 파싱한다.

    형식은 쉼표로 구분한 '분류:규모:만료일' 항목이다(예: 'Servc:large:2026-11-30').
    각 항목의 앞뒤 공백은 허용하고, 항목 수가 3이 아니거나 분류·규모가 비었거나
    규모가 large 가 아니거나 만료일이 YYYY-MM-DD 가 아니면 그 항목만 경고 로그를
    남기고 무시한다. 빈 항목과 빈 문자열은 조용히 건너뛴다. 같은 (분류, 규모)가
    여러 번 오면 마지막 값이 남는다.
    """
    suppressions: dict[tuple[str, str], date] = {}
    if not text:
        return suppressions
    for raw in str(text).split(","):
        item = raw.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) != SUPPRESS_FIELD_COUNT or not parts[0] or not parts[1]:
            logger.warning("낙찰결과 매칭률 억제 항목 형식 오류로 무시합니다: %r", item)
            continue
        category, band, expiry_text = parts
        if band not in SUPPRESS_ALLOWED_BANDS:
            logger.warning(
                "낙찰결과 매칭률 억제 규모는 %s 만 허용합니다. 무시합니다: %r",
                "/".join(SUPPRESS_ALLOWED_BANDS),
                item,
            )
            continue
        try:
            expiry = date.fromisoformat(expiry_text)
        except ValueError:
            logger.warning("낙찰결과 매칭률 억제 만료일 형식 오류로 무시합니다: %r", item)
            continue
        suppressions[(category, band)] = expiry
    return suppressions


def _meets_alert_condition(row: dict[str, Any]) -> bool:
    """한 성숙 주가 경고 조건을 만족하는지 본다(A6)."""
    if row["announcements"] < MIN_WEEK_SAMPLES:
        return False
    if row["baseline_multi_announcements"] < MIN_WEEK_SAMPLES:
        return False
    adjusted_rate = row.get("adjusted_rate")
    baseline_multi_rate = row.get("baseline_multi_rate")
    if adjusted_rate is None or baseline_multi_rate is None:
        return False
    # 0.6 - 0.5 같은 부동소수점 오차로 경계값 0.10 이 밀리지 않게 6자리에서 반올림한다.
    return round(baseline_multi_rate - adjusted_rate, 6) >= RATE_DROP_ALERT


def evaluate_match_rate_alerts(
    rows: list[dict[str, Any]],
    *,
    suppressions: dict[tuple[str, str], date] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """분류별 최근 성숙 주와 직전 성숙 주가 모두 조건을 만족할 때만 경고한다.

    각 대형 행은 announcements >= MIN_WEEK_SAMPLES,
    baseline_multi_announcements >= MIN_WEEK_SAMPLES,
    baseline_multi_rate - adjusted_rate >= RATE_DROP_ALERT 를 만족해야 한다.
    직전 성숙 주 대형 행이 없으면 경고하지 않는다(A6).

    suppressions 는 (분류, 규모) -> 만료일 사전이다. 경고 조건을 만족한 항목이
    억제 대상(분류·규모 일치, today 가 만료일 이하)이면 반환 dict 에
    suppressed=True 와 suppressed_until=만료일 ISO 를 넣고, 아니면
    suppressed=False 와 suppressed_until=None 을 넣는다. 억제 대상이라도 반환
    목록에서 빼지 않으며 기존 키는 그대로 유지한다. suppressions 가 None 이거나
    today 가 None 이면 각각 억제 없음, 오늘 날짜로 해석한다.
    """
    reference = today if today is not None else date.today()
    lookup = suppressions or {}
    large_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("band") != BAND_LARGE:
            continue
        category = str(row.get("category", ""))
        large_by_category.setdefault(category, []).append(row)

    alerts: list[dict[str, Any]] = []
    for category in TARGET_CATEGORIES:
        candidates = sorted(
            large_by_category.get(category, []),
            key=lambda item: str(item["week_start"]),
        )
        if len(candidates) < CONSECUTIVE_ALERT_WEEKS:
            continue
        latest = candidates[-1]
        previous = candidates[-2]
        if not _meets_alert_condition(latest) or not _meets_alert_condition(previous):
            continue
        expiry = lookup.get((category, BAND_LARGE))
        is_suppressed = expiry is not None and reference <= expiry
        alerts.append(
            {
                "category": category,
                "week_start": latest["week_start"],
                "rate": latest["rate"],
                "baseline_rate": latest["baseline_rate"],
                "announcements": latest["announcements"],
                "baseline_announcements": latest["baseline_announcements"],
                "adjusted_rate": latest["adjusted_rate"],
                "baseline_multi_rate": latest["baseline_multi_rate"],
                "previous_week_start": previous["week_start"],
                "previous_adjusted_rate": previous["adjusted_rate"],
                "previous_baseline_multi_rate": previous["baseline_multi_rate"],
                "suppressed": is_suppressed,
                "suppressed_until": expiry.isoformat() if is_suppressed and expiry else None,
            }
        )
    return alerts
