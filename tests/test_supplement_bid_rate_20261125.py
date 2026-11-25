"""보완 투찰률 기반 내 조건 추천 투찰가 계약 시험 (2026-11-25).

정본: .orca/capsules/task_supplement_bid_rate_20261125/capsule.yaml

시험 항목:
 (a) 예시 1 금액 374,078,500원과 예시 2 최소 격자 투찰률
 (b) 필요 가격점수가 하한 금액 점수 이하이면 하한율 이상 최소 격자
 (c) 필요 가격점수가 배점한도를 넘으면 impossible 과 투찰 비권장 사유
 (d) 응답 금액이 resolve_price_compensation 의 complement_bid_amount 와 같음
 (e) 정량점수가 1점 오르면 투찰률이 내려가거나 같음
 (f) 사정률 p50 이 있으면 중심, 없으면 이론 중심 1.0 과 출처 표기
 (g) /evaluations/recommend 응답에 member_bid 가 있고 정량점수에 따라 투찰률이 바뀜
 (h) 기존 member_recommended_* 필드가 유지됨
 (i) 공고 하한율이 없으면 member_bid.status 는 금액 없이 unverifiable
"""
# ruff: noqa: F811 - 가져온 픽스처 이름을 시험 인자로 받는다

from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.prearng_prices import InstitutionSajeongRateStat
from src.app.services.evaluation_scoring import resolve_price_compensation
from tests.test_evaluation_recommend import (  # noqa: F401 - 픽스처는 모듈 이름 그대로 등록돼야 한다
    MEMBER_CREDIT_GRADE,
    _add_member_facts,
    _create_bid,
    _recommend,
    _registry_overrides,
    as_user,
    auto_stub_prediction,
)

TEMPLATE_PATH = Path("src/app/templates/bids/detail.html")

EXAMPLE_ONE_LWLT = Decimal("86.995")
EXAMPLE_TWO_LWLT = Decimal("87.75")


def _base_scenario(result):
    return next(row for row in result.scenarios if row.scenario_type == "base")


def _resolve_example_one():
    """영상 예시 1: B=70·k=4·T=95·Q=29·예정가격 430,000,000·기준율 0.88."""
    return resolve_price_compensation(
        pass_threshold=Decimal("95"),
        non_price_score=Decimal("29"),
        base_rate=Decimal("0.88"),
        max_price_score=Decimal("70"),
        multiplier=Decimal("4"),
        announcement_lwlt_rate=EXAMPLE_ONE_LWLT,
        reference_pred_price=Decimal("430000000"),
        scenarios=(
            ("하단", "lower", Decimal("430000000")),
            ("기준", "base", Decimal("430000000")),
            ("상단", "upper", Decimal("430000000")),
        ),
    )


def _resolve_example_two():
    """영상 예시 2: B=80·k=20·T=95·Q=19.5·예정가격 1,000,000,000·기준율 0.88."""
    return resolve_price_compensation(
        pass_threshold=Decimal("95"),
        non_price_score=Decimal("19.5"),
        base_rate=Decimal("0.88"),
        max_price_score=Decimal("80"),
        multiplier=Decimal("20"),
        announcement_lwlt_rate=EXAMPLE_TWO_LWLT,
        reference_pred_price=Decimal("1000000000"),
        scenarios=(
            ("하단", "lower", Decimal("1000000000")),
            ("기준", "base", Decimal("1000000000")),
            ("상단", "upper", Decimal("1000000000")),
        ),
    )


# --------------------------------------------------------------------------- #
# (a) 원문 예시 재현
# --------------------------------------------------------------------------- #


def test_example_one_complement_amount_uses_won_ceiling():
    """예시 1 보완 금액은 격자 하한 경계를 원 단위로 절상한 374,078,500원이다."""
    result = _resolve_example_one()

    # 하한율 금액의 평점이 필요점수와 같아 '이미 충족'으로 판정되지만, 그 금액은
    # 하한 경계 0.86995 를 원 단위로 절상한 값이다.
    assert result.score_status == "already_sufficient"
    base = _base_scenario(result)
    assert base.row_status == "already_sufficient"
    assert base.complement_bid_amount == Decimal("374078500")
    assert base.verified_price_ratio == Decimal("0.8700")
    assert base.meets_p_req is True


def test_example_two_rate_is_minimum_four_decimal_grid():
    """예시 2 투찰률 경계 0.87775 를 만족하는 최소 4자리 격자는 0.8778 이다."""
    result = _resolve_example_two()

    assert result.score_status == "compensate"
    base = _base_scenario(result)
    assert base.verified_price_ratio == Decimal("0.8778")
    assert base.complement_bid_amount == Decimal("877750000")
    assert base.verified_price_score is not None
    assert base.verified_price_score >= Decimal("75.5")


# --------------------------------------------------------------------------- #
# (b) 정량점수 충분 -> 하한율 이상 최소 격자
# --------------------------------------------------------------------------- #


def test_sufficient_quant_score_uses_lowest_grid_above_lwlt():
    """필요 가격점수가 하한 금액 점수 이하이면 하한율 이상 최소 격자로 확정한다."""
    result = resolve_price_compensation(
        pass_threshold=Decimal("95"),
        non_price_score=Decimal("41"),
        base_rate=Decimal("0.93"),
        max_price_score=Decimal("60"),
        multiplier=Decimal("2"),
        announcement_lwlt_rate=Decimal("89.995"),
        reference_pred_price=Decimal("500000000"),
        scenarios=(
            ("하단", "lower", Decimal("490000000")),
            ("기준", "base", Decimal("500000000")),
            ("상단", "upper", Decimal("510000000")),
        ),
    )

    assert result.score_status == "already_sufficient"
    base = _base_scenario(result)
    # 하한 금액 500,000,000 x 0.89995 = 449,975,000 이고, 평점 반영 비율은 0.9000 이다.
    assert base.complement_bid_amount == Decimal("449975000")
    assert base.verified_price_ratio == Decimal("0.9000")
    assert base.verified_price_ratio * Decimal("100") >= Decimal("89.995")


# --------------------------------------------------------------------------- #
# (c) 필요 가격점수가 배점한도를 넘는 경우
# --------------------------------------------------------------------------- #


def test_required_price_score_over_max_is_impossible():
    """필요 가격점수가 배점한도를 넘으면 금액 없이 impossible 로 판정한다."""
    result = resolve_price_compensation(
        pass_threshold=Decimal("95"),
        non_price_score=Decimal("20"),
        base_rate=Decimal("0.88"),
        max_price_score=Decimal("70"),
        multiplier=Decimal("4"),
        announcement_lwlt_rate=Decimal("86.995"),
        reference_pred_price=Decimal("430000000"),
        scenarios=(("기준", "base", Decimal("430000000")),),
    )

    assert result.score_status == "impossible"
    base = _base_scenario(result)
    assert base.row_status == "impossible"
    assert base.complement_bid_amount is None
    assert result.p_req > result.max_price_score


def test_recommend_marks_impossible_member_bid(client, isolated_db, as_user):
    """추천 API 는 통과 불가 점수를 member_bid.status=impossible 과 사유로 돌려준다."""
    as_user(10)
    bid = _create_bid(isolated_db, notice_no="SUPP-IMPOSSIBLE-001")

    payload = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 10.0, "labor_plan": 0.0}),
    ).json()

    assert payload["blocked"] is True
    member_bid = payload["member_bid"]
    assert member_bid is not None
    assert member_bid["status"] == "impossible"
    assert member_bid["bid_amount"] is None
    assert member_bid["bid_rate_percent"] is None
    assert "투찰을 권장하지 않습니다" in member_bid["reason"]


def test_recommend_marks_member_bid_unverifiable_without_announcement_lwlt(
    client, isolated_db, as_user
):
    """공고 하한율이 없으면 추천 API 는 금액을 지어내지 않고 unverifiable 로 남긴다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(
        isolated_db,
        method="적격심사제-관리규정외 수기심사",
        notice_no="SUPP-UNVERIFIABLE-001",
        raw_overrides={"sucsfbidLwltRate": None},
    )

    payload = _recommend(
        client,
        bid,
        overrides=_registry_overrides(base_rate=0.88, manual_non_price_score=40.0),
    ).json()

    assert payload["lower_bound_rate"] is None
    member_bid = payload["member_bid"]
    assert member_bid is not None
    assert member_bid["status"] == "unverifiable"
    assert member_bid["bid_amount"] is None
    assert member_bid["bid_rate_percent"] is None
    assert member_bid["compensation"] is None
    assert "낙찰하한율이 없어" in member_bid["reason"]


# --------------------------------------------------------------------------- #
# (d) 응답 금액은 resolve_price_compensation 결과 그대로
# --------------------------------------------------------------------------- #


def test_member_bid_amount_equals_resolve_result(client, isolated_db, as_user):
    """응답의 추천 금액·투찰률은 같은 입력으로 부른 도메인 판정과 원 단위까지 같다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="SUPP-EQUAL-001")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()
    assert payload["status"] == "success", payload
    member_bid = payload["member_bid"]
    assert member_bid is not None
    compensation = member_bid["compensation"]
    assert compensation is not None

    scenarios = [
        (row["scenario_name"], row["scenario_type"], Decimal(str(row["estimated_price"])))
        for row in compensation["scenarios"]
    ]
    base_preview = next(row for row in compensation["scenarios"] if row["scenario_type"] == "base")
    direct = resolve_price_compensation(
        pass_threshold=Decimal(payload["pass_threshold"]),
        non_price_score=Decimal(payload["non_price_score"]),
        base_rate=Decimal(str(payload["base_rate"])) / Decimal("100"),
        max_price_score=Decimal(payload["max_price_score"]),
        # score_table 은 규칙 선언값을 싣고, 실제 계산에는 요청 수정값이 우선한다.
        multiplier=Decimal(str(_registry_overrides()["multiplier"])),
        announcement_lwlt_rate=Decimal(str(payload["lower_bound_rate"])) / Decimal("100"),
        reference_pred_price=Decimal(str(base_preview["estimated_price"])),
        scenarios=scenarios,
        flat_ratio=(
            Decimal(payload["score_table"]["flat_ratio"])
            if payload["score_table"]["flat_ratio"] is not None
            else None
        ),
        flat_score=(
            Decimal(payload["score_table"]["flat_score"])
            if payload["score_table"]["flat_score"] is not None
            else None
        ),
    )
    direct_base = _base_scenario(direct)

    assert member_bid["bid_amount"] == int(direct_base.complement_bid_amount)
    assert member_bid["bid_rate_percent"] == format(
        direct_base.verified_price_ratio * Decimal("100"), "f"
    )
    assert member_bid["compensation"]["score_status"] == direct.score_status


# --------------------------------------------------------------------------- #
# (e) 정량점수 1점 상승의 단조성
# --------------------------------------------------------------------------- #


def test_bid_rate_is_monotonic_when_quant_score_rises(client, isolated_db, as_user):
    """정량점수를 1점 올리면 추천 투찰률은 내려가거나 같고, 변화량도 음수·0 이다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="SUPP-MONO-001")

    lower_score = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 20.0, "labor_plan": 9.0}),
    ).json()
    higher_score = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 20.0, "labor_plan": 10.0}),
    ).json()

    lower_rate = Decimal(lower_score["member_bid"]["bid_rate_percent"])
    higher_rate = Decimal(higher_score["member_bid"]["bid_rate_percent"])
    assert higher_rate <= lower_rate
    assert Decimal(higher_score["member_bid"]["rate_change_per_point_pp"]) <= Decimal("0")
    assert higher_score["member_bid"]["bid_amount"] != lower_score["member_bid"]["bid_amount"]


# --------------------------------------------------------------------------- #
# (f) 예상 사정률 중심과 출처
# --------------------------------------------------------------------------- #


def _seed_sajeong_stats(
    db,
    *,
    institution_name: str,
    p50_rate: str | None,
    notice: str,
) -> None:
    db.add(
        InstitutionSajeongRateStat(
            scope="institution",
            institution_name=institution_name,
            category="Servc",
            window_days=1095,
            sample_count=30,
            min_rate=Decimal("88"),
            max_rate=Decimal("96"),
            p10_rate=Decimal("89"),
            p50_rate=Decimal(p50_rate) if p50_rate is not None else None,
            p90_rate=Decimal("95"),
            rebuilt_at=utcnow(),
        )
    )
    db.commit()


def test_member_bid_center_uses_measured_p50(client, isolated_db, as_user):
    """실측 p50 이 있으면 중심 사정률과 기준 예정가격이 p50 을 따른다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(
        isolated_db,
        notice_no="SUPP-P50-001",
        dminstt_nm="사정률 실측기관",
    )
    _seed_sajeong_stats(
        isolated_db,
        institution_name="사정률 실측기관",
        p50_rate="92",
        notice="SUPP-P50-001",
    )

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()
    member_bid = payload["member_bid"]

    assert member_bid["center_rate_percent"] == "92"
    assert member_bid["center_rate_source"] == "p50"
    assert payload["rate_source"] == "measured"
    base_row = next(
        row for row in member_bid["compensation"]["scenarios"] if row["scenario_type"] == "base"
    )
    assert base_row["estimated_price"] == 460_000_000


def test_member_bid_center_falls_back_to_theoretical(client, isolated_db, as_user):
    """p50 이 없으면 중심은 이론 범위 중심 1.0 이고 출처를 이론값으로 표기한다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(
        isolated_db,
        notice_no="SUPP-P50-002",
        dminstt_nm="사정률 미실측기관",
    )
    _seed_sajeong_stats(
        isolated_db,
        institution_name="사정률 미실측기관",
        p50_rate=None,
        notice="SUPP-P50-002",
    )

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()
    member_bid = payload["member_bid"]

    assert member_bid["center_rate_percent"] == "100"
    assert member_bid["center_rate_source"] == "theoretical"
    base_row = next(
        row for row in member_bid["compensation"]["scenarios"] if row["scenario_type"] == "base"
    )
    assert base_row["estimated_price"] == 500_000_000


# --------------------------------------------------------------------------- #
# (g) 추천 응답 연결
# --------------------------------------------------------------------------- #


def test_recommend_returns_member_bid_that_changes_with_quant_score(client, isolated_db, as_user):
    """추천 응답에 member_bid 가 실리고 정량점수를 바꾸면 추천 투찰률이 바뀐다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="SUPP-WIRING-001")

    full = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 20.0, "labor_plan": 10.0}),
    ).json()
    reduced = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 20.0, "labor_plan": 9.0}),
    ).json()

    assert full["status"] == "success", full
    assert full["member_bid"]["status"] == "compensate"
    assert full["member_bid"]["bid_amount"] is not None
    assert full["member_bid"]["compensation"]["scenarios"]
    assert reduced["member_bid"]["bid_rate_percent"] != full["member_bid"]["bid_rate_percent"]


# --------------------------------------------------------------------------- #
# (h) 기존 필드 유지
# --------------------------------------------------------------------------- #


def test_existing_member_recommended_fields_are_kept(client, isolated_db, as_user):
    """새 member_bid 를 더해도 기존 member_recommended_* 필드는 그대로 남는다."""
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db, notice_no="SUPP-COMPAT-001")

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["status"] == "success", payload
    for key in (
        "member_recommended_price",
        "member_recommendation_basis",
        "member_recommended_low",
        "member_recommended_high",
        "member_recommended_error_pp",
        "member_range_clipped_by_score",
    ):
        assert key in payload
    assert payload["member_recommended_price"] is not None
    assert payload["member_recommendation_basis"] in ("ai", "raised_to_min", "lowered_to_max")


# --------------------------------------------------------------------------- #
# 화면 렌더링: 보완 투찰가가 주 표시이고 통과 불가는 비권장 문구
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rendered() -> dict[str, dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 를 사용할 수 없습니다")
    from tests.test_evaluation_scope_badge_per_notice import _function_source

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    source = "\n".join(
        _function_source(template, name)
        for name in (
            "escapeHtml",
            "scoreText",
            "memberRecommendationText",
            "renderMemberRecommendation",
        )
    )
    member_bid = {
        "status": "compensate",
        "reason": None,
        "bid_amount": 452_475_000,
        "bid_rate_percent": "90.5000",
        "center_rate_percent": "100",
        "center_rate_source": "theoretical",
        "rate_change_per_point_pp": "-0.5",
        "compensation": {
            "score_status": "compensate",
            "announcement_lwlt_rate": "89.995",
            "scenarios": [
                {
                    "scenario_name": "하단",
                    "scenario_type": "lower",
                    "estimated_price": 490_000_000,
                    "row_status": "compensate",
                    "verified_price_ratio": "0.9100",
                    "complement_bid_amount": 445_855_000,
                },
                {
                    "scenario_name": "기준",
                    "scenario_type": "base",
                    "estimated_price": 500_000_000,
                    "row_status": "compensate",
                    "verified_price_ratio": "0.9050",
                    "complement_bid_amount": 452_475_000,
                },
                {
                    "scenario_name": "상단",
                    "scenario_type": "upper",
                    "estimated_price": 510_000_000,
                    "row_status": "compensate",
                    "verified_price_ratio": "0.9000",
                    "complement_bid_amount": 458_970_000,
                },
            ],
        },
    }
    cases = {
        "member": {
            "member_bid": member_bid,
            "member_recommended_price": 452_475_000,
            "member_recommendation_basis": "ai",
            "non_price_score": "40",
        },
        "impossible": {
            "member_bid": {
                "status": "impossible",
                "reason": "필요 가격점수가 배점한도를 넘어 통과할 수 없습니다. 투찰을 권장하지 않습니다.",
                "bid_amount": None,
                "bid_rate_percent": None,
                "center_rate_percent": "100",
                "center_rate_source": "theoretical",
                "rate_change_per_point_pp": None,
                "compensation": None,
            },
            "non_price_score": "20",
        },
    }
    script = f"""
const state = {{}};
function el(id) {{
  state[id] = state[id] || {{ classes: new Set(id === '#res-member-recommendation' ? ['hidden'] : []), text: '', html: '' }};
  const node = state[id];
  const handle = {{
    toggleClass(names, on) {{ names.split(' ').forEach(n => on ? node.classes.add(n) : node.classes.delete(n)); return handle; }},
    text(value) {{ node.text = value; return handle; }},
    html(value) {{ node.html = value; return handle; }},
  }};
  return handle;
}}
const $ = el;
const amountText = value => value == null ? '-' : new Intl.NumberFormat('ko-KR').format(value);
{source}
const out = {{}};
for (const [key, data] of Object.entries({json.dumps(cases, ensure_ascii=False)})) {{
  for (const k of Object.keys(state)) delete state[k];
  renderMemberRecommendation(data, true);
  const box = state['#res-member-recommendation'];
  out[key] = {{
    hidden: box.classes.has('hidden'),
    price: (state['#res-member-price'] || {{}}).text || '',
    rate: (state['#res-member-rate'] || {{}}).text || '',
    gap: (state['#res-member-gap'] || {{}}).text || '',
    gapHidden: (state['#res-member-gap'] || {{}}).classes
      ? (state['#res-member-gap'] || {{}}).classes.has('hidden') : null,
    perPoint: (state['#res-member-per-point'] || {{}}).text || '',
    source: (state['#res-member-rate-source'] || {{}}).text || '',
    impossible: (state['#res-member-impossible'] || {{}}).text || '',
    impossibleHidden: (state['#res-member-impossible'] || {{}}).classes
      ? (state['#res-member-impossible'] || {{}}).classes.has('hidden') : null,
    scenariosHidden: (state['#res-member-scenarios'] || {{}}).classes
      ? (state['#res-member-scenarios'] || {{}}).classes.has('hidden') : null,
    rowsHtml: (state['#res-member-scenario-rows'] || {{}}).html || '',
  }};
}}
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(  # noqa: S603 - node 경로와 인자를 이 테스트가 직접 고정합니다
        [node, "-e", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_member_bid_is_primary_with_rate_gap_and_sensitivity(rendered):
    """보완 투찰가가 주 표시이고 투찰률·보완폭·1점 민감도가 함께 보인다."""
    out = rendered["member"]
    assert out["hidden"] is False
    assert out["price"] == "452,475,000"
    assert out["rate"] == "90.5000%"
    assert out["gap"] == "하한율 대비 +0.5050%p 보완"
    assert out["gapHidden"] is False
    assert out["perPoint"] == "정량점수 1점 올리면 투찰률 -0.5000%p"
    assert out["source"] == "예상 사정률 이론 범위 중심 100%"
    assert out["scenariosHidden"] is False
    assert "452,475,000" in out["rowsHtml"]


def test_impossible_member_bid_shows_guidance_instead_of_amount(rendered):
    """통과 불가면 금액 대신 투찰 비권장 문구만 보인다."""
    out = rendered["impossible"]
    assert out["hidden"] is False
    assert out["price"] == "-"
    assert out["impossibleHidden"] is False
    assert "투찰을 권장하지 않습니다" in out["impossible"]
    assert out["scenariosHidden"] is True
