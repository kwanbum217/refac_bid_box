"""산식 카드용 일반용역 별표 메타 엔드포인트 계약 테스트.

규칙 값의 유일한 정본은 src/app/services/evaluation_rules.py 이며, 본 테스트는
GET /api/v1/evaluations/rules 가 그 상수를 값을 만들지 않고 문자열로 직렬화하는지,
범위 안내(scope_note)가 기관별·지역별 산식 부재를 밝히는지, 공고 식별자를 주면
매칭된 별표를 matched_rule 로 돌려주는지를 확인합니다.

실물 DB 는 쓰지 않고 conftest 의 isolated_db (SQLite 인메모리) 위에서 동작합니다.
규칙은 공개 정보라 이 엔드포인트는 인증을 요구하지 않습니다.
"""

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.services.evaluation_rules import POST_20260727_RULES
from src.app.services.evaluation_scoring import format_decimal_plain

RULES_URL = "/api/v1/evaluations/rules"

# 규칙 표 여섯 열과 식별자 필드. 응답 항목은 이 키들을 모두 가져야 합니다.
META_KEYS = {
    "rule_id",
    "service_type",
    "table_name",
    "description",
    "effective_date",
    "source",
    "base_rate",
    "lwlt_rate",
}
DISPLAY_KEYS = ("table_name", "service_type", "base_rate", "lwlt_rate", "effective_date", "source")

# 시설분야용역 5억원 미만. 현행(제2026-390호) 벌의 1번 별표이며 개정 전후가 같은 객체입니다.
FACILITY_METHOD = "시설분야용역 적격심사 추정가격 5억원 미만"
FACILITY_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"


def _create_bid(
    db,
    *,
    category: str = "Servc",
    method_name: str = FACILITY_METHOD,
    bid_ntce_dt: str = "2026-09-30",
) -> BidAnnouncement:
    bid = BidAnnouncement(
        bid_ntce_nm="별표 메타 엔드포인트 테스트 공고",
        bid_ntce_no="EVAL-RULES-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=500_000_000,
        presmpt_prce=500_000_000,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category=category,
        raw_data={
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidMthdNm": method_name,
            "sucsfbidLwltRate": "89.995",
            "srvceDivNm": "일반용역",
            "bidNtceDt": bid_ntce_dt,
        },
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def test_rules_endpoint_returns_fourteen_rows_without_auth(client):
    """인증 없이 호출해도 현행 별표 14종과 여섯 열 값을 돌려준다."""
    response = client.get(RULES_URL)

    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["matched_rule"] is None
    rules = payload["rules"]
    assert len(rules) == 14
    assert len(POST_20260727_RULES) == 14

    for row in rules:
        assert set(row) == META_KEYS
        for key in DISPLAY_KEYS:
            assert isinstance(row[key], str), (key, row)
            assert row[key].strip() != "", (key, row)
        # 기준비율·낙찰하한율은 float 가 아니라 지수 표기 없는 문자열이어야 한다.
        assert isinstance(row["base_rate"], str)
        assert isinstance(row["lwlt_rate"], str)
        assert "e" not in row["base_rate"].lower()
        assert "e" not in row["lwlt_rate"].lower()


def test_rules_values_come_from_registry_single_source(client):
    """응답 값은 evaluation_rules.py 상수를 그대로 직렬화한 것이어야 한다."""
    rules = client.get(RULES_URL).json()["rules"]

    expected = [
        {
            "rule_id": rule.rule_id,
            "service_type": rule.service_type,
            "table_name": rule.table_name,
            "description": rule.description,
            "effective_date": rule.effective_date,
            "source": rule.source,
            "base_rate": format_decimal_plain(rule.base_rate),
            "lwlt_rate": format_decimal_plain(rule.lwlt_rate),
        }
        for rule in POST_20260727_RULES
    ]

    assert rules == expected
    # 대표값을 직접 대조해 반올림 오차가 없음을 고정한다.
    first = rules[0]
    assert first["rule_id"] == "SERVC_QUAL_POST_20260526_ATTACH_01"
    assert first["base_rate"] == "0.93"
    assert first["lwlt_rate"] == "89.995"


def test_scope_note_states_agency_and_region_formula_absent(client):
    """scope_note 가 기관별·지역별 산식 부재와 14종 범위를 명시한다."""
    note = client.get(RULES_URL).json()["scope_note"]

    assert isinstance(note, str)
    for token in ("기관별", "지역별", "없습니다", "14종"):
        assert token in note, (token, note)


def test_bid_id_returns_matched_rule(client, isolated_db):
    """공고 식별자를 주면 그 공고에 매칭된 별표를 matched_rule 로 함께 돌려준다."""
    bid = _create_bid(isolated_db)

    payload = client.get(RULES_URL, params={"bid_id": bid.id}).json()

    assert payload["matched_rule"] is not None
    assert payload["matched_rule"]["rule_id"] == FACILITY_RULE_ID
    assert payload["matched_rule"]["base_rate"] == "0.93"
    # 목록은 그대로 14종 전체다.
    assert len(payload["rules"]) == 14


def test_bid_id_without_match_returns_null_and_list_only(client, isolated_db):
    """용역이 아니어서 별표를 매칭하지 못하면 matched_rule 은 null 이고 목록만 온다."""
    bid = _create_bid(isolated_db, category="Thng")

    payload = client.get(RULES_URL, params={"bid_id": bid.id}).json()

    assert payload["matched_rule"] is None
    assert len(payload["rules"]) == 14


def test_unknown_bid_id_returns_404(client):
    """존재하지 않는 공고 식별자는 404 로 알린다."""
    response = client.get(RULES_URL, params={"bid_id": 999_999})

    assert response.status_code == 404
