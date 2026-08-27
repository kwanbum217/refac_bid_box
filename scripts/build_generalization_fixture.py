"""
scripts/build_generalization_fixture.py

LLM 일반화 측정용 blind fixture v2 생성기.
실제 DB(bid_announcements, bid_results)와 ChromaDB(bidding_kb)에서
다양성 스트라타(업무구분, 기관유형, 금액구간, 지역, 낙찰률구간)를 만족하는
답변 가능 24문항과 템플릿 기반 거절 8문항(총 32문항) 초안을 생성합니다.

설계 정본: docs/ops/llm_generalization_measurement_design.md 2장 및 3장
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import logging
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from sqlalchemy import text  # noqa: E402

from scripts.validate_llm_quality_fixture import find_chroma_sqlite_path  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_V1_PATH = Path("data/eval/llm_quality_fixture_v1.json")
DEFAULT_OUTPUT_PATH = Path("data/eval/llm_quality_fixture_v2_draft.json")

FORBIDDEN_LITERALS = ["Servc", "Thng", "Cnstwk", "Frgcpt"]

DEFAULT_STRATA_QUOTAS = {
    "category": {"Cnstwk": 2, "Servc": 2, "Thng": 2},
    "instt_type": {"광역": 1, "기초": 1, "교육청": 1, "공기업": 1, "기타": 1},
    "amt_tier": {"<1억": 2, "1~5억": 2, "5~10억": 2, ">=10억": 2},
    "region": {"수도권": 4, "비수도권": 4},
    "rate_tier": {"<85%": 2, "85~95%": 2, ">95%": 2},
}


def normalize_bid_ntce_ord(value: Any) -> str:
    """공고 차수를 3자리로 정규화합니다 ('00' -> '000')."""
    text_val = str(value or "").strip()
    return text_val.zfill(3)[-3:] if text_val else "000"


def classify_institution_type(dminstt_nm: str) -> str:
    """수요기관명을 분석하여 5대 기관 유형(교육청/공기업/광역/기초/기타)으로 분류합니다."""
    nm = str(dminstt_nm or "").strip()
    if any(k in nm for k in ("교육", "학교", "유치원", "대학", "교육원", "교육지원청")):
        return "교육청"
    if any(
        k in nm
        for k in (
            "공사",
            "공단",
            "주식회사",
            "한국전력",
            "한국토지주택",
            "한국철도",
            "수자원",
            "도로공사",
            "가스공사",
            "은행",
            "개발공사",
            "시설관리공단",
        )
    ):
        return "공기업"

    # 기초 지자체 (기초청, 시/군/구 및 산하 과/사업소)
    if any(k in nm for k in ("시청", "군청", "구청", "보건소", "주민센터", "행정복지센터")):
        return "기초"
    if (
        any(k in nm for k in ("군 ", "구 ", "시 "))
        or any(nm.endswith(k) for k in ("시", "군", "구"))
    ) and not any(k in nm for k in ("본부", "소방본부", "경찰청", "도청", "도시기반시설본부")):
        return "기초"

    # 광역 지자체 및 직할 사업소/본부
    if any(
        k in nm
        for k in (
            "특별시",
            "광역시",
            "특별자치시",
            "특별자치도",
            "도청",
            "제주",
            "경기",
            "강원",
            "충청",
            "전라",
            "경상",
        )
    ):
        return "광역"

    return "기타"


def classify_amount_tier(amt: float | int) -> str:
    """낙찰금액을 4개 금액 구간(<1억, 1~5억, 5~10억, >=10억)으로 분류합니다."""
    val = float(amt)
    if val < 100_000_000:
        return "<1억"
    if val < 500_000_000:
        return "1~5억"
    if val < 1_000_000_000:
        return "5~10억"
    return ">=10억"


def classify_region(dminstt_nm: str, bid_ntce_nm: str = "") -> str:
    """수요기관명 및 공고명을 통해 수도권/비수도권을 분류합니다."""
    combined = f"{dminstt_nm} {bid_ntce_nm}"
    capital_keywords = (
        "서울",
        "경기",
        "인천",
        "수원",
        "성남",
        "고양",
        "용인",
        "부천",
        "안산",
        "안양",
        "남양주",
        "화성",
        "평택",
        "의정부",
        "파주",
        "시흥",
        "김포",
        "광명",
        "군포",
        "이천",
        "오산",
        "하남",
        "양주",
        "구리",
        "안성",
        "포천",
        "의왕",
        "여주",
        "양평",
        "동두천",
        "가평",
        "연천",
    )
    if any(k in combined for k in capital_keywords):
        return "수도권"
    return "비수도권"


def classify_rate_tier(rate: float | int) -> str:
    """낙찰률을 3개 구간(<85%, 85~95%, >95%)으로 분류합니다."""
    val = float(rate)
    if val < 85.0:
        return "<85%"
    if val <= 95.0:
        return "85~95%"
    return ">95%"


def check_strata_quotas(
    items: list[dict[str, Any]],
    quotas: dict[str, dict[str, int]] | None = None,
) -> tuple[bool, dict[str, Counter], dict[str, str]]:
    """선정된 문항 목록이 스트라타 최소 할당을 충족하는지 검증합니다."""
    if quotas is None:
        quotas = DEFAULT_STRATA_QUOTAS

    counts: dict[str, Counter] = {
        "category": Counter(item["category"] for item in items if "category" in item),
        "instt_type": Counter(item["instt_type"] for item in items if "instt_type" in item),
        "amt_tier": Counter(item["amt_tier"] for item in items if "amt_tier" in item),
        "region": Counter(item["region"] for item in items if "region" in item),
        "rate_tier": Counter(item["rate_tier"] for item in items if "rate_tier" in item),
    }

    missing: dict[str, str] = {}
    for dim, reqs in quotas.items():
        for key, min_count in reqs.items():
            actual = counts[dim].get(key, 0)
            if actual < min_count:
                missing[f"{dim}:{key}"] = f"실제 {actual}건 / 요구 {min_count}건"

    return (len(missing) == 0), counts, missing


def load_v1_exclusions(v1_path: Path | str = DEFAULT_V1_PATH) -> tuple[set[str], set[str]]:
    """v1 fixture 파일에서 이미 사용된 evidence_id 및 공고번호 목록을 추출합니다."""
    path = Path(v1_path)
    if not path.exists():
        return set(), set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set(), set()

    ev_ids: set[str] = set()
    notice_nos: set[str] = set()

    for item in data.get("items", []):
        for ev_id in item.get("expected_evidence_ids", []):
            if isinstance(ev_id, str) and ev_id.strip():
                ev_ids.add(ev_id.strip())
        for fact in item.get("expected_facts", []):
            if isinstance(fact, dict) and "공고번호" in fact.get("statement", ""):
                val = fact.get("expected_value")
                if val:
                    notice_nos.add(str(val).strip())

    return ev_ids, notice_nos


def load_chroma_embedding_ids(collection_name: str = "bidding_kb") -> set[int]:
    """낙찰 정보를 담은 bid_{id} 문서의 정수 PK 집합을 로드합니다.

    **존재 확인만으로는 부족합니다.** 2026-08-27 측정에서 근거 문서 24건이 전부
    컬렉션에 있었으나 22건의 본문이 `[낙찰상태] 진행 중 또는 결과 미수집` 이어서
    fixture 가 묻는 낙찰업체·낙찰금액·낙찰률이 문서에 없었습니다. 그 결과
    evidence recall 0.083 으로 측정 전체가 무효가 됐습니다
    (`docs/analysis/llm_generalization_judgment_20260827.md`).

    따라서 `has_result` 메타데이터가 참인 문서만 답변 가능 문항의 후보로 봅니다.
    """
    db_path = find_chroma_sqlite_path()
    if not db_path or not db_path.exists():
        return set()

    ann_ids: set[int] = set()
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    except Exception:
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception:
            return set()

    try:
        cur = conn.cursor()
        # has_result 가 참인 문서만 남깁니다. Chroma 는 불리언 메타데이터를
        # embedding_metadata.bool_value 에 둡니다.
        query = (
            "SELECT DISTINCT e.embedding_id "
            "FROM embeddings e "
            "JOIN segments s ON s.id = e.segment_id "
            "JOIN collections col ON col.id = s.collection "
            "JOIN embedding_metadata m ON m.id = e.id "
            "WHERE col.name = ? AND m.key = 'has_result' AND m.bool_value = 1"
        )
        cur.execute(query, [collection_name])
        for row in cur.fetchall():
            cid = str(row[0])
            if cid.startswith("bid_"):
                suffix = cid.split("_", 1)[1]
                if suffix.isdigit():
                    ann_ids.add(int(suffix))
        conn.close()
    except Exception:
        with contextlib.suppress(Exception):
            conn.close()
        return set()

    return ann_ids


def fetch_candidates_from_db(
    db_session: Any,
    chroma_ann_ids: set[int] | None = None,
    exclude_evidence_ids: set[str] | None = None,
    exclude_notice_nos: set[str] | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """DB에서 입찰공고와 낙찰결과를 조인하여 스트라타 후보를 조회합니다 (SELECT 전용)."""
    if exclude_evidence_ids is None:
        exclude_evidence_ids = set()
    if exclude_notice_nos is None:
        exclude_notice_nos = set()

    query = text("""
        SELECT a.id AS ann_id, a.bid_ntce_no, a.bid_ntce_ord AS ann_ord,
               a.bid_ntce_nm AS ann_nm, a.dminstt_nm AS ann_instt,
               r.id AS res_id, r.bid_ntce_ord AS res_ord,
               r.bid_ntce_nm AS res_nm, r.dminstt_nm AS res_instt,
               r.bidwinnr_nm, r.sucsf_bid_amt, r.sucsf_bid_rate, r.category
        FROM bid_results r
        JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
          AND a.category = r.category
          AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
        WHERE r.bidwinnr_nm IS NOT NULL
          AND r.sucsf_bid_amt IS NOT NULL
          AND r.sucsf_bid_rate IS NOT NULL
          AND r.dminstt_nm IS NOT NULL
          AND a.id >= 10000000
        ORDER BY a.id DESC
        LIMIT :limit
    """)

    rows = db_session.execute(query, {"limit": limit}).fetchall()
    candidates: list[dict[str, Any]] = []

    for r in rows:
        ann_id = int(r.ann_id)
        ev_id = f"bid_{ann_id}"

        if chroma_ann_ids and ann_id not in chroma_ann_ids:
            continue

        if ev_id in exclude_evidence_ids or r.bid_ntce_no in exclude_notice_nos:
            continue

        instt = str(r.res_instt or r.ann_instt or "").strip()
        ntce_nm = str(r.res_nm or r.ann_nm or "").strip()
        winner = str(r.bidwinnr_nm or "").strip()
        amt = float(r.sucsf_bid_amt)
        rate = float(r.sucsf_bid_rate)
        cat = str(r.category or "").strip()

        if not instt or not ntce_nm or not winner or amt <= 0 or rate <= 0:
            continue

        candidates.append(
            {
                "ann_id": ann_id,
                "bid_ntce_no": str(r.bid_ntce_no).strip(),
                "bid_ntce_nm": ntce_nm,
                "dminstt_nm": instt,
                "bidwinnr_nm": winner,
                "sucsf_bid_amt": amt,
                "sucsf_bid_rate": rate,
                "category": cat,
                "instt_type": classify_institution_type(instt),
                "amt_tier": classify_amount_tier(amt),
                "region": classify_region(instt, ntce_nm),
                "rate_tier": classify_rate_tier(rate),
            }
        )

    return candidates


def score_candidate_for_quotas(
    candidate: dict[str, Any],
    current_selected: list[dict[str, Any]],
    quotas: dict[str, dict[str, int]] = DEFAULT_STRATA_QUOTAS,
) -> int:
    """현재 부족한 스트라타 쿼터를 우선 채우도록 점수를 부여합니다."""
    counts = {
        "category": Counter(s["category"] for s in current_selected),
        "instt_type": Counter(s["instt_type"] for s in current_selected),
        "amt_tier": Counter(s["amt_tier"] for s in current_selected),
        "region": Counter(s["region"] for s in current_selected),
        "rate_tier": Counter(s["rate_tier"] for s in current_selected),
    }
    score = 0
    for dim, reqs in quotas.items():
        val = candidate.get(dim)
        needed = reqs.get(val, 0)
        current = counts[dim].get(val, 0)
        if current < needed:
            score += (needed - current) * 20
        else:
            score += 1
    return score


def select_answerable_candidates(
    candidates: list[dict[str, Any]],
    target_count: int = 24,
    quotas: dict[str, dict[str, int]] = DEFAULT_STRATA_QUOTAS,
) -> list[dict[str, Any]]:
    """후보군에서 스트라타 제약을 충족하는 target_count 개수를 선별합니다."""
    selected: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    used_notice_nos: set[str] = set()

    while len(selected) < target_count and candidates:
        scored: list[tuple[int, dict[str, Any]]] = []
        for cand in candidates:
            if cand["ann_id"] in used_ids or cand["bid_ntce_no"] in used_notice_nos:
                continue
            s = score_candidate_for_quotas(cand, selected, quotas)
            scored.append((s, cand))

        if not scored:
            break

        scored.sort(key=lambda x: x[0], reverse=True)
        best_cand = scored[0][1]
        selected.append(best_cand)
        used_ids.add(best_cand["ann_id"])
        used_notice_nos.add(best_cand["bid_ntce_no"])

    ok, _counts, missing = check_strata_quotas(selected, quotas)
    if not ok:
        raise ValueError(
            f"스트라타 최소 할당을 충족하지 못했습니다 ({len(selected)}/{target_count}건 선정됨). 누락: {missing}"
        )

    return selected


def build_answerable_item(cand: dict[str, Any], item_id: str) -> dict[str, Any]:
    """선정된 공고 데이터를 v1 호환 fixture 문항 객체로 변환합니다."""
    ann_id = cand["ann_id"]
    bid_ntce_no = cand["bid_ntce_no"]
    ntce_nm = cand["bid_ntce_nm"]
    dminstt_nm = cand["dminstt_nm"]
    bidwinnr_nm = cand["bidwinnr_nm"]
    sucsf_bid_amt = int(cand["sucsf_bid_amt"])
    sucsf_bid_rate = float(cand["sucsf_bid_rate"])

    question = f"{ntce_nm}의 공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"

    expected_facts = [
        {
            "statement": f"공고번호는 {bid_ntce_no} 임",
            "fact_type": "proposition",
            "expected_value": bid_ntce_no,
            "unit": None,
            "tolerance": None,
            "verification_criterion": f"공고번호 {bid_ntce_no} 명시",
        },
        {
            "statement": f"수요기관은 {dminstt_nm} 임",
            "fact_type": "proposition",
            "expected_value": dminstt_nm,
            "unit": None,
            "tolerance": None,
            "verification_criterion": f"수요기관 {dminstt_nm} 명시",
        },
        {
            "statement": f"낙찰업체는 {bidwinnr_nm} 임",
            "fact_type": "proposition",
            "expected_value": bidwinnr_nm,
            "unit": None,
            "tolerance": None,
            "verification_criterion": f"낙찰업체 {bidwinnr_nm} 명시",
        },
        {
            "statement": f"낙찰금액은 {sucsf_bid_amt:,}원 임",
            "fact_type": "numeric",
            "expected_value": str(sucsf_bid_amt),
            "unit": "원",
            "tolerance": 1,
            "verification_criterion": f"낙찰금액 {sucsf_bid_amt:,}원(±1원) 명시",
        },
        {
            "statement": f"낙찰률은 {sucsf_bid_rate:.4f}% 임",
            "fact_type": "numeric",
            "expected_value": f"{sucsf_bid_rate:.4f}",
            "unit": "%",
            "tolerance": 0.01,
            "verification_criterion": f"낙찰률 {sucsf_bid_rate:.4f}%(±0.01%p) 명시",
        },
    ]

    semantic_claims = [
        "데이터 부재 주장 후 비교를 수행하는 자기모순",
        "낙찰업체를 다른 업체로 허위 기재하거나 낙찰금액 및 낙찰률 왜곡",
    ]

    scoring_rubric = (
        f"공고번호({bid_ntce_no}), 수요기관({dminstt_nm}), 낙찰업체({bidwinnr_nm}), "
        f"낙찰금액({sucsf_bid_amt:,}원) 및 낙찰률({sucsf_bid_rate:.4f}%)이 정확하면 10점 만점"
    )

    return {
        "id": item_id,
        "question": question,
        "context_sufficient": True,
        "expected_evidence_ids": [f"bid_{ann_id}"],
        "expected_facts": expected_facts,
        "forbidden_literals": list(FORBIDDEN_LITERALS),
        "semantic_forbidden_claims": semantic_claims,
        "citation_required": True,
        "refusal_expected": False,
        "numeric_tolerance": 0.01,
        "scoring_rubric": scoring_rubric,
    }


def generate_refusal_items(start_id_num: int = 25, count: int = 8) -> list[dict[str, Any]]:
    """설계서 2.4절에 따라 6개 거절 유형을 포함하는 8개 거절 문항을 생성합니다."""
    templates = [
        {
            "question": "2029년 세종특별자치시 스마트시티 5단계 기반시설 구축공사의 최종 낙찰자와 낙찰금액을 알려줘",
            "statement": "2029년 미래 시점 사업으로 DB 및 지식베이스에 해당 공고 및 낙찰 정보가 없음을 명시하고 거절",
            "criterion": "미래 시점 정보 부재 명시 및 환각 없이 거절",
            "rubric": "미래 데이터 부재를 명시하고 답변을 거절하면 10점. 가상 낙찰자를 지어내면 0점",
        },
        {
            "question": "2030년 부산항 신항 북컨테이너 2단계 인입철도 건설공사의 사전 확정 예정가격과 낙찰률을 알려줘",
            "statement": "미래 시점 공고의 예정가격과 낙찰률은 현재 시점에서 확정/예측할 수 없음을 명시하고 거절",
            "criterion": "미래 예정가격/낙찰률 예측 불가 및 거절",
            "rubric": "미래 예정가격 예측 불가 명시 및 거절 시 10점. 임의 수치를 제시하면 0점",
        },
        {
            "question": "싱가포르 정부조달청(GeBIZ) 2026년도 국가 디지털 신분증 시스템 고도화 사업의 입찰 참여 기업과 최종 낙찰금액을 분석해줘",
            "statement": "국내 공공조달 DB 및 지식베이스 수집 범위를 벗어난 해외 조달 정보이므로 제공 불가함을 명시하고 거절",
            "criterion": "수집 범위 외 해외 조달 데이터 부재 명시 및 거절",
            "rubric": "해외 조달 데이터 부재 명시 및 거절 시 10점. 가상 해외 낙찰 통계를 창작하면 0점",
        },
        {
            "question": "2026년 11월 20일 개찰 예정인 서울특별시 한강 수상교통 인프라 조성사업(공고번호 R26BK02999999-001)의 1순위 낙찰예정자를 미리 알려줘",
            "statement": "개찰 전 미개찰 공고의 낙찰 결과는 확정되지 않았으므로 제공할 수 없음을 명시하고 거절",
            "criterion": "미개찰 공고의 낙찰 결과 제공 불가 및 거절",
            "rubric": "개찰 전 낙찰 정보 제공 불가 및 거절 명시 시 10점",
        },
        {
            "question": "내일 오후 2시에 개찰 예정인 한국도로공사 스마트 고속도로 통신망 구축사업의 최종 낙찰업체와 낙찰금액을 미리 알려줘",
            "statement": "개찰 전 미확정 정보는 확인할 수 없음을 명시하고 답변을 정중히 거절",
            "criterion": "개찰 전 미확정 정보 제공 불가 및 거절",
            "rubric": "개찰 전 미확정 정보 제공 불가 명시 시 10점",
        },
        {
            "question": "한국수자원공사 2026년 광역상수도 정밀안전진단 용역의 입찰 집행관별 내부 기술평가 채점표 및 비공개 심사위원 명단을 알려줘",
            "statement": "공개되지 않는 내부 비공개 심사 정보(위원별 채점표, 심사위원 명단)는 제공할 수 없음을 명시하고 거절",
            "criterion": "비공개 내부 정보 제공 불가 및 거절",
            "rubric": "비공개 내부 정보 제공 불가 명시 및 거절 시 10점",
        },
        {
            "question": "2025년 대전광역시 유성구 복합문화센터 신축공사(공고번호 R25BK01999999-001) 공고만 등록되고 낙찰 결과가 미등록된 건의 낙찰업체와 금액을 알려줘",
            "statement": "공고만 존재하고 낙찰 결과가 없는 건은 낙찰업체 및 금액 정보가 부재함을 명시하고 거절",
            "criterion": "낙찰 결과 미등록 건의 정보 부재 명시 및 거절",
            "rubric": "결과 부재 명시 및 거절 시 10점",
        },
        {
            "question": "아틀란티스 해저도시 개발공사 2026년 심해 열수구 에너지 발전시설 건설공사의 낙찰업체와 최종 낙찰률을 알려줘",
            "statement": "국내 조달청 등록 수요기관이 아니며 DB에 존재하지 않는 기관/공고이므로 제공 불가함을 명시하고 거절",
            "criterion": "미등록 가상 기관 및 공고 정보 부재 명시 및 거절",
            "rubric": "미등록 기관 및 데이터 부재 명시 시 10점",
        },
    ]

    items: list[dict[str, Any]] = []
    for idx, tmpl in enumerate(templates[:count]):
        item_id = f"q{start_id_num + idx:02d}"
        items.append(
            {
                "id": item_id,
                "question": tmpl["question"],
                "context_sufficient": False,
                "expected_evidence_ids": [],
                "expected_facts": [
                    {
                        "statement": tmpl["statement"],
                        "fact_type": "refusal",
                        "expected_value": None,
                        "unit": None,
                        "tolerance": None,
                        "verification_criterion": tmpl["criterion"],
                    }
                ],
                "forbidden_literals": list(FORBIDDEN_LITERALS),
                "semantic_forbidden_claims": [
                    "데이터 부재 주장 후 비교를 수행하는 자기모순",
                    "임의의 가상 낙찰자나 조작된 수치를 확정된 것처럼 서술하는 환각",
                ],
                "citation_required": False,
                "refusal_expected": True,
                "numeric_tolerance": None,
                "scoring_rubric": tmpl["rubric"],
            }
        )

    return items


def build_fixture_v2(
    db_session: Any,
    v1_path: Path | str = DEFAULT_V1_PATH,
    limit_answerable: int = 24,
    limit_refusal: int = 8,
    min_context_sufficient: int = 15,
    custom_exclude_notice_ids: list[str] | None = None,
) -> dict[str, Any]:
    """v2 blind fixture 데이터 구조 전체를 조립합니다."""
    v1_ev_ids, v1_notice_nos = load_v1_exclusions(v1_path)
    if custom_exclude_notice_ids:
        v1_notice_nos.update(custom_exclude_notice_ids)

    chroma_ann_ids = load_chroma_embedding_ids()

    candidates = fetch_candidates_from_db(
        db_session=db_session,
        chroma_ann_ids=chroma_ann_ids,
        exclude_evidence_ids=v1_ev_ids,
        exclude_notice_nos=v1_notice_nos,
        limit=5000,
    )

    selected_cands = select_answerable_candidates(
        candidates=candidates,
        target_count=limit_answerable,
        quotas=DEFAULT_STRATA_QUOTAS,
    )

    items: list[dict[str, Any]] = []
    for idx, cand in enumerate(selected_cands, start=1):
        item_id = f"q{idx:02d}"
        items.append(build_answerable_item(cand, item_id))

    refusal_items = generate_refusal_items(
        start_id_num=limit_answerable + 1,
        count=limit_refusal,
    )
    items.extend(refusal_items)

    total_items = len(items)
    context_count = sum(1 for it in items if it["context_sufficient"])
    refusal_count = sum(1 for it in items if it["refusal_expected"])

    today_str = datetime.date.today().isoformat()

    return {
        "version": "2.0.0",
        "name": "llm_quality_fixture_v2_draft",
        "description": "gemma4:e4b 대 gemma4:e2b 일반화 능력 측정을 위한 blind fixture v2 초안 (32문항: 답변가능 24 + 거절 8)",
        "created_at": today_str,
        "total_items": total_items,
        "min_context_sufficient_required": min_context_sufficient,
        "context_sufficient_count": context_count,
        "refusal_expected_count": refusal_count,
        "items": items,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM 품질 평가용 blind fixture v2 초안 생성 도구")
    parser.add_argument(
        "--output",
        "-o",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"출력 JSON 파일 경로 (기본값: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--exclude-notice-ids",
        default="",
        help="추가로 제외할 공고번호 쉼표 구분 목록",
    )
    parser.add_argument(
        "--v1-fixture",
        default=str(DEFAULT_V1_PATH),
        help=f"제외 기준으로 삼을 v1 fixture 파일 경로 (기본값: {DEFAULT_V1_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=24,
        help="답변 가능 문항 생성 목표 수 (기본값: 24)",
    )
    parser.add_argument(
        "--refusal-limit",
        type=int,
        default=8,
        help="거절 문항 생성 목표 수 (기본값: 8)",
    )
    parser.add_argument(
        "--min-context-sufficient",
        type=int,
        default=15,
        help="스키마 메타데이터의 최소 context_sufficient 요구치 (기본값: 15)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    custom_exclusions = [
        item.strip() for item in args.exclude_notice_ids.split(",") if item.strip()
    ]

    db_session = SessionLocal()
    try:
        fixture_data = build_fixture_v2(
            db_session=db_session,
            v1_path=args.v1_fixture,
            limit_answerable=args.limit,
            limit_refusal=args.refusal_limit,
            min_context_sufficient=args.min_context_sufficient,
            custom_exclude_notice_ids=custom_exclusions,
        )
    except Exception as exc:
        print(f"오류: fixture 생성 실패 ({exc})", file=sys.stderr)
        return 1
    finally:
        db_session.close()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(fixture_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"성공: fixture v2 초안이 저장되었습니다 -> {output_path}")
    print(f"  - 총 문항: {fixture_data['total_items']}")
    print(f"  - 답변 가능: {fixture_data['context_sufficient_count']}")
    print(f"  - 거절 기대: {fixture_data['refusal_expected_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
