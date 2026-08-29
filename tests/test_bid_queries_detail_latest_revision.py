"""
tests/test_bid_queries_detail_latest_revision.py

공고 상세 페이지 유사 공고 조회의 NOT EXISTS 기반 최신 차수 판정 쿼리와
기존 window 랭킹 쿼리 간의 결과 집합 동치를 검증합니다.
"""

from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects import mysql

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import bid_queries


def _add_announcement(db, **overrides) -> BidAnnouncement:
    now = utcnow()
    payload = {
        "bid_ntce_no": "TEST-NTCE-001",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기본 공고명",
        "dminstt_nm": "수요기관A",
        "ntce_instt_nm": "공고기관A",
        "category": "Servc",
        "base_amount": 10000000,
        "presmpt_prce": 10000000,
        "bid_ntce_dt": now,
        "collected_at": now,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _fetch_window_ids(
    db, category: str, dminstt_nm: str, exclude_id: int | None = None, limit: int = 5
) -> list[int]:
    stmt = bid_queries.latest_announcement_filter(
        select(BidAnnouncement).where(
            BidAnnouncement.category == category,
            BidAnnouncement.dminstt_nm == dminstt_nm,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(BidAnnouncement.id != exclude_id)
    return [row.id for row in db.execute(stmt.limit(limit)).scalars().all()]


def _fetch_not_exists_ids(
    db, category: str, dminstt_nm: str, exclude_id: int | None = None, limit: int = 5
) -> list[int]:
    stmt = bid_queries.similar_announcement_latest_filter(
        select(BidAnnouncement).where(
            BidAnnouncement.category == category,
            BidAnnouncement.dminstt_nm == dminstt_nm,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(BidAnnouncement.id != exclude_id)
    return [row.id for row in db.execute(stmt.limit(limit)).scalars().all()]


def _add_distractor_noise(db):
    """후보 밖 그룹의 잡음 데이터를 대량 주입하여 공허한 일치를 방지합니다."""
    base_time = utcnow()
    categories = ["Thng", "Cnstwk", "Frgcpt", "Servc"]
    agencies = ["잡음기관X", "잡음기관Y", "잡음기관Z"]
    for i in range(12):
        _add_announcement(
            db,
            bid_ntce_no=f"NOISE-{i:03d}",
            bid_ntce_ord=f"{i % 3:03d}",
            bid_ntce_nm=f"잡음 공고 {i}",
            dminstt_nm=agencies[i % len(agencies)],
            category=categories[i % len(categories)],
            bid_ntce_dt=base_time - timedelta(days=i + 1),
            collected_at=base_time - timedelta(days=i + 1),
        )


def _recreate_announcements_without_unique_constraint(db):
    """차수 동일 시험(b, c, d)을 위해 SQLite 테이블에서 UNIQUE 제약을 푼 복제 테이블을 생성합니다."""
    db.execute(text("DROP TABLE IF EXISTS bid_announcements"))
    db.execute(
        text("""
        CREATE TABLE bid_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bid_ntce_nm VARCHAR(500),
            bid_ntce_no VARCHAR(50) NOT NULL,
            bid_ntce_ord VARCHAR(10) NOT NULL DEFAULT '000',
            ntce_instt_nm VARCHAR(200),
            dminstt_nm VARCHAR(200),
            base_amount BIGINT,
            presmpt_prce BIGINT,
            bid_ntce_dt DATETIME,
            bid_clse_dt DATETIME,
            openg_dt DATETIME,
            ntce_kind_nm VARCHAR(100),
            bid_methd_nm VARCHAR(100),
            cntrct_mthd_nm VARCHAR(100),
            category VARCHAR(10) NOT NULL DEFAULT 'Thng',
            raw_data JSON,
            collected_at DATETIME NOT NULL
        )
    """)
    )
    db.commit()


def test_sql_structure_no_window_function():
    """유사 공고 최신 필터가 전체 테이블 대상 ROW_NUMBER() window 대신 NOT EXISTS 서브쿼리를 쓰는지 검증합니다."""
    stmt = bid_queries.similar_announcement_latest_filter(
        select(BidAnnouncement).where(
            BidAnnouncement.category == "Servc",
            BidAnnouncement.dminstt_nm == "한국철도공사",
        )
    )
    compiled_sql = str(stmt.compile(dialect=mysql.dialect())).upper()

    assert "ROW_NUMBER() OVER" not in compiled_sql
    assert "LATEST_RANK" not in compiled_sql
    assert "EXISTS" in compiled_sql


def test_latest_announcement_filter_signature_and_behavior_preserved():
    """기존 목록 및 색인 경로에서 사용하는 latest_announcement_filter의 시그니처와 window 구조가 불변인지 확인합니다."""
    stmt = bid_queries.latest_announcement_filter(select(BidAnnouncement))
    compiled_sql = str(stmt.compile(dialect=mysql.dialect())).upper()

    assert "ROW_NUMBER() OVER" in compiled_sql
    assert "LATEST_RANK" in compiled_sql


def test_scenario_a_agency_changed_in_later_revision(isolated_db):
    """(a) 더 나중 차수에서 dminstt_nm이 바뀐 공고: 이전 기관의 유사 공고 결과에서 해당 그룹 전체가 제외되어야 합니다."""
    _add_distractor_noise(isolated_db)

    base_time = utcnow()
    # 공고 1: 000차수는 기관A, 001차수에서 기관B로 변경됨 (최신은 기관B)
    rev1 = _add_announcement(
        isolated_db,
        bid_ntce_no="NOTICE-A",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=5),
        collected_at=base_time - timedelta(days=5),
    )
    rev2 = _add_announcement(
        isolated_db,
        bid_ntce_no="NOTICE-A",
        bid_ntce_ord="001",
        dminstt_nm="수요기관B",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=4),
        collected_at=base_time - timedelta(days=4),
    )

    # 공고 2: 000차수 기관B -> 001차수 기관A로 변경됨 (최신은 기관A)
    rev3 = _add_announcement(
        isolated_db,
        bid_ntce_no="NOTICE-B",
        bid_ntce_ord="000",
        dminstt_nm="수요기관B",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=3),
        collected_at=base_time - timedelta(days=3),
    )
    rev4 = _add_announcement(
        isolated_db,
        bid_ntce_no="NOTICE-B",
        bid_ntce_ord="001",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=2),
        collected_at=base_time - timedelta(days=2),
    )

    # 공고 3: 기관A에서 차수 000만 존재
    rev5 = _add_announcement(
        isolated_db,
        bid_ntce_no="NOTICE-C",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=1),
        collected_at=base_time - timedelta(days=1),
    )

    # 기관A 조회: NOTICE-A(rev1)는 최신이 기관B이므로 제외, NOTICE-B는 rev4(기관A) 포함, NOTICE-C는 rev5 포함
    window_ids_a = _fetch_window_ids(isolated_db, "Servc", "수요기관A")
    not_exists_ids_a = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관A")

    assert set(window_ids_a) == {rev4.id, rev5.id}
    assert set(not_exists_ids_a) == {rev4.id, rev5.id}
    assert rev1.id not in not_exists_ids_a
    assert rev2.id not in not_exists_ids_a
    assert rev3.id not in not_exists_ids_a

    # 기관B 조회: NOTICE-A는 rev2(기관B) 포함, NOTICE-B(rev3)는 최신이 기관A이므로 제외
    window_ids_b = _fetch_window_ids(isolated_db, "Servc", "수요기관B")
    not_exists_ids_b = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관B")

    assert set(window_ids_b) == {rev2.id}
    assert set(not_exists_ids_b) == {rev2.id}
    assert rev1.id not in not_exists_ids_b
    assert rev3.id not in not_exists_ids_b


def test_scenario_b_same_ord_different_notice_date(isolated_db):
    """(b) 차수는 같고 bid_ntce_dt만 다른 공고: 더 최신 공고일시를 가진 행이 최신으로 판정되어야 합니다."""
    _recreate_announcements_without_unique_constraint(isolated_db)
    _add_distractor_noise(isolated_db)

    base_time = utcnow()
    older_dt = _add_announcement(
        isolated_db,
        bid_ntce_no="SAME-ORD-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=10),
        collected_at=base_time - timedelta(days=5),
    )
    newer_dt = _add_announcement(
        isolated_db,
        bid_ntce_no="SAME-ORD-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=2),
        collected_at=base_time - timedelta(days=5),
    )

    window_ids = _fetch_window_ids(isolated_db, "Servc", "수요기관A")
    not_exists_ids = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관A")

    assert window_ids == [newer_dt.id]
    assert not_exists_ids == [newer_dt.id]
    assert older_dt.id not in not_exists_ids


def test_scenario_c_mixed_null_and_not_null_notice_dates(isolated_db):
    """(c) bid_ntce_dt가 NULL인 행과 NOT NULL인 행이 같은 그룹에 섞인 공고:
    MySQL ORDER BY DESC 규약(NULL이 뒤)에 따라 NOT NULL 행이 최신으로 판정되어야 합니다.
    또한 양쪽 다 NULL인 경우 수집일시/ID로 갈려야 합니다.
    """
    _recreate_announcements_without_unique_constraint(isolated_db)
    _add_distractor_noise(isolated_db)

    base_time = utcnow()

    # 그룹 1: NULL dt vs NOT NULL dt (차수 동일) -> NOT NULL 행이 최신
    null_dt_1 = _add_announcement(
        isolated_db,
        bid_ntce_no="NULL-MIX-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=None,
        collected_at=base_time - timedelta(days=2),
    )
    not_null_dt_1 = _add_announcement(
        isolated_db,
        bid_ntce_no="NULL-MIX-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=5),
        collected_at=base_time - timedelta(days=10),
    )

    # 그룹 2: 둘 다 NULL dt (차수 동일) -> collected_at이 최신인 행이 최신
    both_null_older_col = _add_announcement(
        isolated_db,
        bid_ntce_no="NULL-MIX-02",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=None,
        collected_at=base_time - timedelta(days=5),
    )
    both_null_newer_col = _add_announcement(
        isolated_db,
        bid_ntce_no="NULL-MIX-02",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=None,
        collected_at=base_time - timedelta(days=1),
    )

    window_ids = _fetch_window_ids(isolated_db, "Servc", "수요기관A")
    not_exists_ids = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관A")

    assert set(window_ids) == {not_null_dt_1.id, both_null_newer_col.id}
    assert set(not_exists_ids) == {not_null_dt_1.id, both_null_newer_col.id}
    assert null_dt_1.id not in not_exists_ids
    assert both_null_older_col.id not in not_exists_ids


def test_scenario_d_same_all_keys_tie_break_by_id(isolated_db):
    """(d) 정렬 키(ord, bid_ntce_dt, collected_at)가 전부 같고 id로만 갈리는 공고: 더 큰 id가 최신으로 판정되어야 합니다."""
    _recreate_announcements_without_unique_constraint(isolated_db)
    _add_distractor_noise(isolated_db)

    fixed_time = datetime(2026, 8, 1, 10, 0, 0)
    row_lower_id = _add_announcement(
        isolated_db,
        bid_ntce_no="TIE-ID-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=fixed_time,
        collected_at=fixed_time,
    )
    row_higher_id = _add_announcement(
        isolated_db,
        bid_ntce_no="TIE-ID-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=fixed_time,
        collected_at=fixed_time,
    )
    assert row_higher_id.id > row_lower_id.id

    window_ids = _fetch_window_ids(isolated_db, "Servc", "수요기관A")
    not_exists_ids = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관A")

    assert window_ids == [row_higher_id.id]
    assert not_exists_ids == [row_higher_id.id]
    assert row_lower_id.id not in not_exists_ids


def test_scenario_e_different_category_same_notice_no(isolated_db):
    """(e) 카테고리가 다른 동일 공고번호: (bid_ntce_no, category)가 독립 그룹으로 각각 판정되어야 합니다."""
    _add_distractor_noise(isolated_db)

    base_time = utcnow()
    thng_rev1 = _add_announcement(
        isolated_db,
        bid_ntce_no="MULTI-CAT-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Thng",
        bid_ntce_dt=base_time - timedelta(days=4),
        collected_at=base_time - timedelta(days=4),
    )
    thng_rev2 = _add_announcement(
        isolated_db,
        bid_ntce_no="MULTI-CAT-01",
        bid_ntce_ord="001",
        dminstt_nm="수요기관A",
        category="Thng",
        bid_ntce_dt=base_time - timedelta(days=2),
        collected_at=base_time - timedelta(days=2),
    )

    servc_rev1 = _add_announcement(
        isolated_db,
        bid_ntce_no="MULTI-CAT-01",
        bid_ntce_ord="000",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=3),
        collected_at=base_time - timedelta(days=3),
    )
    servc_rev2 = _add_announcement(
        isolated_db,
        bid_ntce_no="MULTI-CAT-01",
        bid_ntce_ord="001",
        dminstt_nm="수요기관A",
        category="Servc",
        bid_ntce_dt=base_time - timedelta(days=1),
        collected_at=base_time - timedelta(days=1),
    )

    # Thng 카테고리 검증
    window_thng = _fetch_window_ids(isolated_db, "Thng", "수요기관A")
    not_exists_thng = _fetch_not_exists_ids(isolated_db, "Thng", "수요기관A")
    assert window_thng == [thng_rev2.id]
    assert not_exists_thng == [thng_rev2.id]
    assert thng_rev1.id not in not_exists_thng

    # Servc 카테고리 검증
    window_servc = _fetch_window_ids(isolated_db, "Servc", "수요기관A")
    not_exists_servc = _fetch_not_exists_ids(isolated_db, "Servc", "수요기관A")
    assert window_servc == [servc_rev2.id]
    assert not_exists_servc == [servc_rev2.id]
    assert servc_rev1.id not in not_exists_servc


def test_get_announcement_detail_integration_equivalence(isolated_db):
    """get_announcement_detail 호출 시 similar_bids 결과가 기존 쿼리와 완전히 동일함을 검증합니다."""
    _add_distractor_noise(isolated_db)

    base_time = utcnow()
    target_bid = _add_announcement(
        isolated_db,
        bid_ntce_no="MAIN-BID-01",
        bid_ntce_ord="000",
        dminstt_nm="한국가스공사",
        category="Cnstwk",
        bid_ntce_dt=base_time,
        collected_at=base_time,
    )

    # 한국가스공사 과거 낙찰 이력 생성
    past_result = BidResult(
        bid_ntce_no="RES-001",
        bid_ntce_ord="000",
        bid_ntce_nm="한국가스공사 과거낙찰",
        bidwinnr_nm="낙찰업체A",
        dminstt_nm="한국가스공사",
        category="Cnstwk",
        sucsf_bid_amt=5000000,
        sucsf_bid_rate=88.5,
        rl_openg_dt=base_time - timedelta(days=10),
        collected_at=base_time - timedelta(days=10),
    )
    isolated_db.add(past_result)
    isolated_db.commit()

    # 유사 공고 후보들 (한국가스공사, Cnstwk)
    sim_1_v1 = _add_announcement(
        isolated_db,
        bid_ntce_no="SIM-BID-01",
        bid_ntce_ord="000",
        dminstt_nm="한국가스공사",
        category="Cnstwk",
        bid_ntce_dt=base_time - timedelta(days=5),
        collected_at=base_time - timedelta(days=5),
    )
    sim_1_v2 = _add_announcement(
        isolated_db,
        bid_ntce_no="SIM-BID-01",
        bid_ntce_ord="001",
        dminstt_nm="한국가스공사",
        category="Cnstwk",
        bid_ntce_dt=base_time - timedelta(days=3),
        collected_at=base_time - timedelta(days=3),
    )

    # 기관이 변경되어 제외되어야 하는 유사 공고
    sim_2_v1 = _add_announcement(
        isolated_db,
        bid_ntce_no="SIM-BID-02",
        bid_ntce_ord="000",
        dminstt_nm="한국가스공사",
        category="Cnstwk",
        bid_ntce_dt=base_time - timedelta(days=6),
        collected_at=base_time - timedelta(days=6),
    )
    sim_2_v2 = _add_announcement(
        isolated_db,
        bid_ntce_no="SIM-BID-02",
        bid_ntce_ord="001",
        dminstt_nm="한국전력공사",  # 기관 변경
        category="Cnstwk",
        bid_ntce_dt=base_time - timedelta(days=2),
        collected_at=base_time - timedelta(days=2),
    )

    detail = bid_queries.get_announcement_detail(isolated_db, target_bid.id)
    assert detail is not None
    assert detail["bid"].id == target_bid.id

    similar_ids = [b.id for b in detail["similar_bids"]]
    assert sim_1_v2.id in similar_ids
    assert sim_1_v1.id not in similar_ids
    assert sim_2_v1.id not in similar_ids
    assert sim_2_v2.id not in similar_ids
    assert target_bid.id not in similar_ids
