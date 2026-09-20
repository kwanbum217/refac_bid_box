"""
tests/test_bid_result_serialization_batch.py

낙찰 목록 및 홈 화면 직렬화의 공고 조회 일괄 처리(N+1 방지) 검증.
- 20행 직렬화 시 공고 조회 쿼리 수가 행 수에 비례하지 않고 일괄(1회)로 수행됨을 검증.
- 차수 정규화(선행 0 제거)로만 매칭되는 공고의 일괄 경로와 단건 경로 동등성 검증.
- 공고 부재 시 sucsf_bid_rate 폴백 동등성 검증.
- 혼합 배치(완전일치, 정규화일치, 공고부재) 전체 필드 1:1 일치 검증.
- 홈 화면(recent_results) 및 낙찰결과 목록 API 연동 검증.
"""

from decimal import Decimal

from sqlalchemy import event

from src.app.api.v1.bids import _serialize_result, _serialize_results
from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    BidAnnouncement,
    BidResult,
    preload_matching_announcements,
)
from src.app.services.bid_queries import get_result_detail


class QueryCounter:
    """SQLAlchemy 쿼리 실행 횟수 계측기."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self.queries: list[str] = []

    def __enter__(self):
        self.count = 0
        self.queries.clear()
        event.listen(self.engine, "before_cursor_execute", self._callback)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        event.remove(self.engine, "before_cursor_execute", self._callback)

    def _callback(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.queries.append(statement)


def _create_announcement(db, **overrides) -> BidAnnouncement:
    defaults = {
        "bid_ntce_no": "20240100001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "테스트 공고",
        "dminstt_nm": "테스트 수요기관",
        "ntce_instt_nm": "테스트 공고기관",
        "category": "Servc",
        "base_amount": 100_000_000,
        "presmpt_prce": 90_000_000,
        "bid_ntce_dt": utcnow(),
        "raw_data": None,
    }
    defaults.update(overrides)
    ann = BidAnnouncement(**defaults)
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def _create_result(db, **overrides) -> BidResult:
    defaults = {
        "bid_ntce_no": "20240100001",
        "bid_ntce_ord": "00",
        "bid_ntce_nm": "테스트 공고",
        "bidwinnr_nm": "낙찰업체",
        "sucsf_bid_amt": 88_000_000,
        "sucsf_bid_rate": Decimal("88.0000"),
        "rl_openg_dt": utcnow(),
        "dminstt_nm": "테스트 수요기관",
        "category": "Servc",
        "raw_data": None,
    }
    defaults.update(overrides)
    res = BidResult(**defaults)
    db.add(res)
    db.commit()
    db.refresh(res)
    return res


def test_batch_query_count_does_not_scale_with_rows(isolated_db):
    """20행 직렬화 시 공고 조회가 행 수(20회)에 비례하지 않고 일괄(1회)로 수행되는지 검증."""
    # 20개 공고 및 낙찰 결과 생성
    for i in range(20):
        _create_announcement(
            isolated_db,
            bid_ntce_no=f"202401{i:05d}",
            bid_ntce_ord="000",
            category="Servc",
            base_amount=100_000_000,
        )
        _create_result(
            isolated_db,
            bid_ntce_no=f"202401{i:05d}",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=88_000_000,
            sucsf_bid_rate=Decimal("88.0000"),
        )

    engine = isolated_db.get_bind()

    # 단건 경로 질의 횟수 측정 (비교군: 행마다 공고 쿼리 발생)
    results_for_single = isolated_db.query(BidResult).order_by(BidResult.id).limit(20).all()
    with QueryCounter(engine) as single_counter:
        for row in results_for_single:
            _serialize_result(isolated_db, row)
    # 단건 경로는 행마다 최소 1~2개 쿼리 실행 (20행이면 20회 이상)
    assert single_counter.count >= 20

    # 일괄 경로 질의 횟수 측정 (캐시 속성 제거 후 일괄 직렬화)
    isolated_db.expire_all()
    results_for_batch = isolated_db.query(BidResult).order_by(BidResult.id).limit(20).all()
    for row in results_for_batch:
        if hasattr(row, "_matching_announcement_cache"):
            delattr(row, "_matching_announcement_cache")

    with QueryCounter(engine) as batch_counter:
        serialized = _serialize_results(isolated_db, results_for_batch)

    # 일괄 경로는 공고 조회 쿼리가 정확히 1회만 발생해야 함
    assert batch_counter.count == 1
    assert len(serialized) == 20
    # 계산된 낙찰률 검증 (88,000,000 / 100,000,000 * 100 = 88.0)
    for item in serialized:
        assert item["display_winning_rate"] == 88.0


def test_batch_vs_single_equivalence_exact_match(isolated_db):
    """차수가 완전히 일치하는 경우 일괄 경로와 단건 경로가 동일한 공고를 고르고 동일한 결과를 내는지 검증."""
    ann = _create_announcement(
        isolated_db,
        bid_ntce_no="EXACT-001",
        bid_ntce_ord="00",
        category="Thng",
        base_amount=200_000_000,
    )
    res = _create_result(
        isolated_db,
        bid_ntce_no="EXACT-001",
        bid_ntce_ord="00",
        category="Thng",
        sucsf_bid_amt=170_000_000,
        sucsf_bid_rate=Decimal("85.0000"),
    )

    # 1. 단건 경로 직접 호출 및 직렬화
    matched_single = res.matching_announcement(isolated_db)
    single_dict = _serialize_result(isolated_db, res)

    # 2. 캐시 속성 제거 후 일괄 경로 실행
    if hasattr(res, "_matching_announcement_cache"):
        delattr(res, "_matching_announcement_cache")

    preload_matching_announcements(isolated_db, [res])
    matched_batch = res.matching_announcement(isolated_db)
    batch_dict = _serialize_result(isolated_db, res)

    assert matched_single is not None
    assert matched_batch is not None
    assert matched_single.id == ann.id
    assert matched_batch.id == ann.id
    assert matched_batch.id == matched_single.id

    # 모든 필드 1:1 일치 확인
    assert batch_dict == single_dict
    assert batch_dict["display_winning_rate"] == 85.0


def test_batch_vs_single_equivalence_normalized_ord(isolated_db):
    """차수 선행 0 차이로만 매칭되는 경우 일괄 경로와 단건 경로가 동일한 공고를 고르는지 검증."""
    test_cases = [
        ("NORM-01", "00", "000", "Servc", 100_000_000, 89_000_000),  # 2자리 vs 3자리 0
        ("NORM-02", "01", "001", "Servc", 50_000_000, 45_000_000),  # 01 vs 001
        ("NORM-03", "0", "000", "Cnstwk", 300_000_000, 270_000_000),  # 0 vs 000
        ("NORM-04", "02", "02", "Frgcpt", 80_000_000, 72_000_000),  # 02 vs 02
    ]

    for no, res_ord, ann_ord, cat, base, awarded in test_cases:
        ann = _create_announcement(
            isolated_db,
            bid_ntce_no=no,
            bid_ntce_ord=ann_ord,
            category=cat,
            base_amount=base,
        )
        res = _create_result(
            isolated_db,
            bid_ntce_no=no,
            bid_ntce_ord=res_ord,
            category=cat,
            sucsf_bid_amt=awarded,
            sucsf_bid_rate=Decimal("80.0000"),
        )

        # 단건 경로
        matched_single = res.matching_announcement(isolated_db)
        single_dict = _serialize_result(isolated_db, res)

        # 캐시 제거 후 일괄 경로
        if hasattr(res, "_matching_announcement_cache"):
            delattr(res, "_matching_announcement_cache")

        preload_matching_announcements(isolated_db, [res])
        matched_batch = res.matching_announcement(isolated_db)
        batch_dict = _serialize_result(isolated_db, res)

        assert matched_single is not None, f"단건 경로 매칭 실패: {no}"
        assert matched_batch is not None, f"배치 경로 매칭 실패: {no}"
        assert matched_single.id == ann.id
        assert matched_batch.id == ann.id
        assert matched_batch.id == matched_single.id
        assert batch_dict == single_dict


def test_batch_vs_single_equivalence_missing_announcement(isolated_db):
    """공고가 존재하지 않는 낙찰 행은 종전대로 sucsf_bid_rate 로 떨어지는지 검증."""
    # 1. 아예 공고가 없는 경우
    res_none = _create_result(
        isolated_db,
        bid_ntce_no="NO-ANN-001",
        bid_ntce_ord="00",
        category="Servc",
        sucsf_bid_rate=Decimal("87.6543"),
    )

    # 2. 공고번호는 같으나 카테고리가 다른 경우
    _create_announcement(
        isolated_db,
        bid_ntce_no="DIFF-CAT-001",
        bid_ntce_ord="000",
        category="Thng",  # 공고는 Thng
    )
    res_cat = _create_result(
        isolated_db,
        bid_ntce_no="DIFF-CAT-001",
        bid_ntce_ord="00",
        category="Servc",  # 낙찰은 Servc
        sucsf_bid_rate=Decimal("82.1234"),
    )

    # 3. 공고번호와 카테고리는 같으나 차수가 전혀 매칭되지 않는 경우 (05 vs 000)
    _create_announcement(
        isolated_db,
        bid_ntce_no="DIFF-ORD-001",
        bid_ntce_ord="000",
        category="Servc",
    )
    res_ord = _create_result(
        isolated_db,
        bid_ntce_no="DIFF-ORD-001",
        bid_ntce_ord="05",
        category="Servc",
        sucsf_bid_rate=Decimal("91.0000"),
    )

    rows = [res_none, res_cat, res_ord]

    # 각 행에 대해 단건 결과 기록
    single_dicts = []
    for r in rows:
        assert r.matching_announcement(isolated_db) is None
        single_dicts.append(_serialize_result(isolated_db, r))

    # 캐시 제거 후 일괄 처리
    for r in rows:
        if hasattr(r, "_matching_announcement_cache"):
            delattr(r, "_matching_announcement_cache")

    batch_dicts = _serialize_results(isolated_db, rows)

    for r, b_dict, s_dict in zip(rows, batch_dicts, single_dicts, strict=True):
        assert r.matching_announcement(isolated_db) is None
        assert b_dict["display_winning_rate"] == float(r.sucsf_bid_rate)
        assert s_dict["display_winning_rate"] == float(r.sucsf_bid_rate)
        assert b_dict == s_dict


def test_mixed_batch_exact_dictionary_match(isolated_db):
    """완전일치, 정규화일치, 공고부재가 섞인 배치에서 모든 필드가 단건과 1:1 일치하는지 검증."""
    # 공고 2건 등록
    _create_announcement(
        isolated_db,
        bid_ntce_no="MIX-01",
        bid_ntce_ord="00",
        category="Servc",
        base_amount=100_000_000,
    )
    _create_announcement(
        isolated_db,
        bid_ntce_no="MIX-02",
        bid_ntce_ord="001",
        category="Servc",
        base_amount=200_000_000,
    )

    test_specs = [
        # (bid_ntce_no, ord, cat, amt, rate)
        ("MIX-01", "00", "Servc", 85_000_000, Decimal("85.0000")),  # 완전 일치
        ("MIX-02", "01", "Servc", 180_000_000, Decimal("90.0000")),  # 정규화 일치 (01 vs 001)
        ("MIX-03", "00", "Servc", 50_000_000, Decimal("95.0000")),  # 공고 부재
    ]

    rows = []
    for no, ord_val, cat, amt, rate in test_specs:
        res = _create_result(
            isolated_db,
            bid_ntce_no=no,
            bid_ntce_ord=ord_val,
            category=cat,
            sucsf_bid_amt=amt,
            sucsf_bid_rate=rate,
        )
        rows.append(res)

    # 1. 단건 직렬화 결과 수집
    single_serialized = [_serialize_result(isolated_db, r) for r in rows]

    # 2. 캐시 속성 제거
    for r in rows:
        if hasattr(r, "_matching_announcement_cache"):
            delattr(r, "_matching_announcement_cache")

    # 3. 일괄 직렬화 결과 수집
    batch_serialized = _serialize_results(isolated_db, rows)

    assert len(batch_serialized) == len(single_serialized) == 3
    for b_item, s_item in zip(batch_serialized, single_serialized, strict=True):
        assert b_item == s_item


def test_home_endpoint_uses_batch_serialization(client, isolated_db):
    """홈 화면 API (/api/v1/bids/home) 호출 시 recent_results 가 정상 직렬화되는지 검증."""
    _create_announcement(
        isolated_db,
        bid_ntce_no="HOME-01",
        bid_ntce_ord="000",
        category="Servc",
        base_amount=100_000_000,
    )
    _create_result(
        isolated_db,
        bid_ntce_no="HOME-01",
        bid_ntce_ord="00",
        category="Servc",
        sucsf_bid_amt=92_000_000,
        sucsf_bid_rate=Decimal("92.0000"),
    )

    resp = client.get("/api/v1/bids/home")
    assert resp.status_code == 200
    data = resp.json()

    assert "recent_results" in data
    assert len(data["recent_results"]) >= 1
    home_item = data["recent_results"][0]
    assert home_item["bid_ntce_no"] == "HOME-01"
    assert home_item["display_winning_rate"] == 92.0


def test_results_list_endpoint_integration(client, isolated_db):
    """낙찰 목록 API (/api/v1/bids/results) 호출 시 일괄 조회가 정상 동작하는지 검증."""
    for i in range(5):
        _create_announcement(
            isolated_db,
            bid_ntce_no=f"LIST-ANN-{i}",
            bid_ntce_ord="000",
            category="Servc",
            base_amount=100_000_000,
        )
        _create_result(
            isolated_db,
            bid_ntce_no=f"LIST-ANN-{i}",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=85_000_000,
            sucsf_bid_rate=Decimal("85.0000"),
        )

    resp = client.get("/api/v1/bids/results")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) >= 5
    for item in data["results"][:5]:
        assert item["display_winning_rate"] == 85.0


def test_preload_idempotent_and_empty(isolated_db):
    """preload_matching_announcements 가 빈 목록이나 중복 호출에도 안전하게 동작하는지 검증."""
    # 1. 빈 목록
    preload_matching_announcements(isolated_db, [])

    # 2. None 원소 방어
    preload_matching_announcements(isolated_db, [None])  # type: ignore[list-item]

    # 3. 중복 호출 시 재질의 안 함
    res = _create_result(isolated_db, bid_ntce_no="IDEMP-01")
    engine = isolated_db.get_bind()

    # 1회차 프리로드
    preload_matching_announcements(isolated_db, [res])
    assert hasattr(res, "_matching_announcement_cache")

    # 2회차 프리로드 (이미 캐시가 있으므로 쿼리 0회)
    with QueryCounter(engine) as counter:
        preload_matching_announcements(isolated_db, [res])
    assert counter.count == 0

    # 4. BidResult 클래스 메서드 호출 동등성
    BidResult.preload_matching_announcements(isolated_db, [res])


def test_get_result_detail_preloads_announcements_and_prevents_n_plus_one(isolated_db):
    """get_result_detail 호출 시 본건과 관련 낙찰의 공고가 일괄 선채움되어 N+1 쿼리가 방지됨을 검증."""
    # 본건 공고 및 낙찰 생성
    target_ann = _create_announcement(
        isolated_db,
        bid_ntce_no="DETAIL-TARGET-001",
        bid_ntce_ord="000",
        dminstt_nm="한국도로공사",
        category="Servc",
        base_amount=100_000_000,
    )
    target_res = _create_result(
        isolated_db,
        bid_ntce_no="DETAIL-TARGET-001",
        bid_ntce_ord="00",
        dminstt_nm="한국도로공사",
        category="Servc",
        sucsf_bid_amt=88_000_000,
        sucsf_bid_rate=Decimal("88.0000"),
    )

    # 동일 기관/카테고리의 관련 낙찰 및 공고 5건 생성
    for i in range(5):
        _create_announcement(
            isolated_db,
            bid_ntce_no=f"DETAIL-REL-{i:03d}",
            bid_ntce_ord="000",
            dminstt_nm="한국도로공사",
            category="Servc",
            base_amount=100_000_000,
        )
        _create_result(
            isolated_db,
            bid_ntce_no=f"DETAIL-REL-{i:03d}",
            bid_ntce_ord="00",
            dminstt_nm="한국도로공사",
            category="Servc",
            sucsf_bid_amt=90_000_000 + i * 1_000_000,
            sucsf_bid_rate=Decimal(f"{90 + i}.0000"),
        )

    isolated_db.expire_all()
    engine = isolated_db.get_bind()

    # get_result_detail 실행 시 쿼리 계측:
    # 1. db.get(BidResult, pk) (1회)
    # 2. related_results 조회 (1회)
    # 3. preload_matching_announcements 일괄 IN 쿼리 (1회)
    # 4. display_winning_rate 루프 내부에서는 캐시를 사용하므로 추가 공고 쿼리 0회
    # 총 쿼리는 3회만 발생해야 함 (선채움이 없었다면 본건 1회 + 관련 5회 = 최소 8회 이상 발생)
    with QueryCounter(engine) as counter:
        detail = get_result_detail(isolated_db, target_res.id)

    assert detail is not None
    assert set(detail.keys()) == {"result", "related_results", "raw_json"}
    assert detail["result"].id == target_res.id
    assert len(detail["related_results"]) == 5

    # 공고 조회 쿼리가 루프 순회에 비례하지 않고 정확히 3회(본건 1 + 관련 1 + 선채움 1)로 한정됨을 검증
    assert counter.count == 3

    # 본건 및 관련 낙찰 5건 모두에 _matching_announcement_cache 가 적재되었음을 검증
    assert hasattr(detail["result"], "_matching_announcement_cache")
    assert detail["result"]._matching_announcement_cache is not None
    assert detail["result"]._matching_announcement_cache.id == target_ann.id
    assert detail["result"].resolved_winning_rate == Decimal("88.0000")

    for row in detail["related_results"]:
        assert hasattr(row, "_matching_announcement_cache")
        assert row._matching_announcement_cache is not None
        assert row.resolved_winning_rate is not None

    # 선채움 캐시 적중 검증:
    # detail 반환 객체들에 대해 display_winning_rate 를 재호출해도 SQL 쿼리가 0회 발생함을 확인
    with QueryCounter(engine) as zero_counter:
        detail["result"].display_winning_rate(isolated_db)
        for row in detail["related_results"]:
            row.display_winning_rate(isolated_db)
    assert zero_counter.count == 0
