"""
tests/test_win_interval_stats_20261125.py

용역 적격 승리 구간 분포(win_interval_stats) 재집계·조회와 사용자별 분산
추천 함수를 검증합니다.

막으려는 사고:
  - 승리 구간 정의(중앙값, 하한율 조건화)가 백테스트 보고서 2장과 다른 것
  - 최소 표본 미만 범위에 행을 만들어 조회 대체가 깨지는 것
  - 같은 사용자·공고에 매번 다른 추천가가 나오거나, 점수가 같은 사용자끼리
    같은 추천가가 겹치는 것
  - 회원 보완 투찰률 하한을 무시하는 것
  - 마이그레이션이 멱등이 아니거나 head 가 둘이 되는 것

시험은 SQLite 인메모리 DB 만 쓰고 호스트 MySQL·Redis·HTTP 에 붙지 않습니다.
기준 코드에서는 새 모듈·모델이 없으므로 각 시험이 단언 실패로 떨어집니다.
"""

from __future__ import annotations

import importlib.util
import itertools
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

import src.app.models  # noqa: F401  모든 테이블을 Base.metadata 에 등록
from src.app.core.db import Base
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.prearng_prices import BidPrearngPrice

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / "c9d0e1f2a3b4_add_win_interval_stats.py"
REVISION = "c9d0e1f2a3b4"
PREVIOUS_REVISION = "b8d9e0f1a2b3"

_counter = itertools.count(1)


def _load_service():
    """기준 코드에서는 모듈이 없으므로 단언 실패로 끝납니다."""
    spec = importlib.util.find_spec("src.app.services.win_interval_stats")
    assert spec is not None, "win_interval_stats 서비스 모듈이 없습니다."
    return importlib.import_module("src.app.services.win_interval_stats")


def _load_model():
    """기준 코드에서는 모델이 없으므로 단언 실패로 끝납니다."""
    from src.app.models import prearng_prices

    model = getattr(prearng_prices, "WinIntervalStat", None)
    assert model is not None, "WinIntervalStat 모델이 없습니다."
    return model


@pytest.fixture
def stats_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_case(
    session,
    *,
    institution: str,
    base_amount: int,
    pred_price: int,
    won_amount: int,
    lwlt_rate: str,
) -> None:
    index = next(_counter)
    notice_no = f"R26BK{index:06d}"
    opened_at = utcnow()
    session.add(
        BidAnnouncement(
            bid_ntce_no=notice_no,
            bid_ntce_ord="000",
            category="Servc",
            dminstt_nm=institution,
            raw_data={"sucsfbidLwltRate": lwlt_rate},
        )
    )
    session.add(
        BidResult(
            bid_ntce_no=notice_no,
            bid_ntce_ord="000",
            category="Servc",
            sucsf_bid_amt=won_amount,
            sucsf_bid_rate=Decimal(won_amount) / Decimal(pred_price) * 100,
            rl_openg_dt=opened_at,
        )
    )
    session.add(
        BidPrearngPrice(
            bid_ntce_no=notice_no,
            bid_ntce_ord="000",
            bid_clsfc_no="0",
            rbid_no="000",
            category="Servc",
            dminstt_nm=institution,
            bssamt=base_amount,
            plnprc=pred_price,
            sajeong_rate=Decimal(pred_price) / Decimal(base_amount) * 100,
            rl_openg_dt=opened_at,
        )
    )


# ============================================================================
# (a) 작은 합성 표본에서 x_mid 분위가 손계산과 같다
# ============================================================================


def test_rebuild_computes_xmid_quantiles_by_hand(stats_session) -> None:
    service = _load_service()
    model = _load_model()
    # B=P=1000, L=88, W=900/920/940 -> s=100, r=90/92/94, x_mid=89/90/91
    for won_amount in (900, 920, 940):
        _add_case(
            stats_session,
            institution="서울특별시",
            base_amount=1000,
            pred_price=1000,
            won_amount=won_amount,
            lwlt_rate="88.000",
        )
    stats_session.commit()

    outcome = service.rebuild_win_interval_stats(
        stats_session,
        min_institution_samples=3,
        min_region_samples=3,
        min_category_samples=3,
        min_exact_samples=3,
    )

    assert outcome["institution_rows"] == 1
    row = stats_session.scalars(select(model).where(model.scope == "institution")).one()
    assert float(row.lwlt_rate) == 88.0
    assert row.sample_count == 3
    # 선형 보간: p05 = 89 + 0.1*(90-89), p95 = 90 + 0.9*(91-90)
    assert float(row.p05) == pytest.approx(89.1)
    assert float(row.p50) == pytest.approx(90.0)
    assert float(row.p95) == pytest.approx(90.9)


def test_rebuild_uses_margin_fallback_when_exact_lwlt_samples_are_short(stats_session) -> None:
    service = _load_service()
    model = _load_model()
    # L=88 두 건(m=2,4)과 L=90 한 건(m=5). L=88 은 정확 표본 2건 < 3 이므로
    # 같은 범위 전체의 마진을 L=88 에 더해 근사한다: x_mid = 88 + m/2.
    _add_case(
        stats_session,
        institution="서울특별시",
        base_amount=1000,
        pred_price=1000,
        won_amount=900,
        lwlt_rate="88.000",
    )
    _add_case(
        stats_session,
        institution="서울특별시",
        base_amount=1000,
        pred_price=1000,
        won_amount=920,
        lwlt_rate="88.000",
    )
    _add_case(
        stats_session,
        institution="서울특별시",
        base_amount=1000,
        pred_price=1000,
        won_amount=950,
        lwlt_rate="90.000",
    )
    stats_session.commit()

    service.rebuild_win_interval_stats(
        stats_session,
        min_institution_samples=3,
        min_region_samples=3,
        min_category_samples=3,
        min_exact_samples=3,
    )

    rows = {
        float(row.lwlt_rate): row
        for row in stats_session.scalars(select(model).where(model.scope == "institution"))
    }
    assert float(rows[88.0].p50) == pytest.approx(90.0)
    assert float(rows[90.0].p50) == pytest.approx(92.0)
    assert rows[88.0].sample_count == 3
    assert rows[90.0].sample_count == 3


# ============================================================================
# (b) 하한율별 분리 집계와 범위 최소 표본
# ============================================================================


def test_rebuild_separates_lwlt_and_skips_small_scopes(stats_session) -> None:
    service = _load_service()
    model = _load_model()
    for won_amount in (900, 920, 940):
        _add_case(
            stats_session,
            institution="서울특별시",
            base_amount=1000,
            pred_price=1000,
            won_amount=won_amount,
            lwlt_rate="88.000",
        )
    for won_amount in (950, 960, 970):
        _add_case(
            stats_session,
            institution="서울특별시",
            base_amount=1000,
            pred_price=1000,
            won_amount=won_amount,
            lwlt_rate="90.000",
        )
    stats_session.commit()

    outcome = service.rebuild_win_interval_stats(
        stats_session,
        min_institution_samples=7,
        min_region_samples=5,
        min_category_samples=5,
        min_exact_samples=3,
    )

    # 발주처는 6건 < 7 이라 행이 없고, 시·도(6)와 업종(6)만 하한율 2개로 나뉜다.
    assert outcome["institution_rows"] == 0
    assert outcome["region_rows"] == 2
    assert outcome["category_rows"] == 2
    region_rows = stats_session.scalars(select(model).where(model.scope == "region")).all()
    assert sorted(float(row.lwlt_rate) for row in region_rows) == [88.0, 90.0]


# ============================================================================
# (c) lookup 이 발주처 -> 시·도 -> 업종 순으로 물러난다
# ============================================================================


def test_lookup_falls_back_institution_region_category(stats_session) -> None:
    service = _load_service()
    for _ in range(30):
        _add_case(
            stats_session,
            institution="서울특별시",
            base_amount=1000,
            pred_price=1000,
            won_amount=900,
            lwlt_rate="88.000",
        )
    for name in ("경기도 수원시", "경기도 성남시"):
        for _ in range(25):
            _add_case(
                stats_session,
                institution=name,
                base_amount=1000,
                pred_price=1000,
                won_amount=900,
                lwlt_rate="88.000",
            )
    for _ in range(10):
        _add_case(
            stats_session,
            institution="부산광역시",
            base_amount=1000,
            pred_price=1000,
            won_amount=900,
            lwlt_rate="88.000",
        )
    stats_session.commit()
    service.rebuild_win_interval_stats(stats_session)

    institution = service.lookup_win_interval_quantiles(
        stats_session, "서울특별시", Decimal("88.000")
    )
    assert institution is not None
    assert institution["scope"] == "institution"
    assert institution["sample_count"] == 30
    assert len(institution["quantiles"]) == 19

    region = service.lookup_win_interval_quantiles(
        stats_session, "경기도 수원시", Decimal("88.000")
    )
    assert region is not None
    assert region["scope"] == "region"
    assert region["institution_name"] == "경기도"
    assert region["sample_count"] == 50

    category = service.lookup_win_interval_quantiles(stats_session, "부산광역시", Decimal("88.000"))
    assert category is not None
    assert category["scope"] == "category"
    assert category["institution_name"] == ""
    assert category["sample_count"] == 90

    assert (
        service.lookup_win_interval_quantiles(stats_session, "서울특별시", Decimal("90.000"))
        is None
    )


# ============================================================================
# (d) 같은 키는 같은 값, 다른 사용자는 밴드 안에서 고르게 퍼진다
# ============================================================================


def test_user_dispersed_bid_is_deterministic_and_spreads_users() -> None:
    service = _load_service()
    quantiles = [Decimal("80.0") + Decimal("0.2") * index for index in range(19)]
    arguments = {
        "base_amount": Decimal("10000000000"),
        "quantiles": quantiles,
        "member_floor_rate": Decimal("80.0"),
        "center_sajeong_rate": Decimal("100.0"),
    }

    first = service.user_dispersed_bid(user_key="user-1", notice_key="notice-1", **arguments)
    second = service.user_dispersed_bid(user_key="user-1", notice_key="notice-1", **arguments)
    assert first == second
    assert first.source == "interval"
    assert first.clipped is False

    results = [
        service.user_dispersed_bid(user_key=f"user-{index}", notice_key="notice-1", **arguments)
        for index in range(100)
    ]
    quantiles_chosen = sorted(float(result.quantile) for result in results)
    assert all(0.25 <= value <= 0.75 for value in quantiles_chosen)
    assert quantiles_chosen[0] < 0.30
    assert quantiles_chosen[-1] > 0.70
    bands = ((0.25, 0.375), (0.375, 0.5), (0.5, 0.625), (0.625, 0.7500001))
    counts = [sum(1 for value in quantiles_chosen if low <= value < high) for low, high in bands]
    assert all(count >= 10 for count in counts), counts

    amounts = {result.amount for result in results}
    assert len(amounts) >= 90


# ============================================================================
# (e) 회원 하한 클립
# ============================================================================


def test_user_dispersed_bid_clips_to_member_floor() -> None:
    service = _load_service()
    quantiles = [Decimal("80.0") + Decimal("0.1") * index for index in range(19)]

    result = service.user_dispersed_bid(
        base_amount=Decimal("1000000"),
        quantiles=quantiles,
        member_floor_rate=Decimal("90.0"),
        center_sajeong_rate=Decimal("100.0"),
        user_key="user-1",
        notice_key="notice-1",
    )

    assert result.clipped is True
    assert result.bid_rate < Decimal("90")
    assert result.amount == 900000


# ============================================================================
# (f) 분포가 없으면 현행 단일 추천과 같은 하한 금액
# ============================================================================


def test_user_dispersed_bid_without_quantiles_falls_back_to_floor() -> None:
    service = _load_service()
    base_amount = Decimal("1000001")
    member_floor_rate = Decimal("88.5")
    center_sajeong_rate = Decimal("99.0")

    result = service.user_dispersed_bid(
        base_amount=base_amount,
        quantiles=None,
        member_floor_rate=member_floor_rate,
        center_sajeong_rate=center_sajeong_rate,
        user_key="user-1",
        notice_key="notice-1",
    )

    exact = base_amount * member_floor_rate * center_sajeong_rate / Decimal("10000")
    assert result.amount == int(exact.to_integral_value(rounding=ROUND_CEILING))
    assert result.amount == 876151
    assert result.source == "fallback"
    assert result.clipped is False
    assert result.quantile == Decimal("0.5")


# ============================================================================
# 갱신 경로: 사정률 재집계 뒤에 승리 구간 재집계를 이어서 실행한다
# ============================================================================


class _FakeSession:
    def close(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_refresh_thread_rebuilds_win_interval_after_sajeong(monkeypatch) -> None:
    from src.tasks import scheduled_tasks

    calls: list[str] = []
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(scheduled_tasks, "link_prearng_dminstt", lambda session: 1)

    def _sajeong(session):
        calls.append("sajeong")
        return {"rows": 1}

    def _win_interval(session):
        calls.append("win_interval")
        return {"rows": 2}

    monkeypatch.setattr(scheduled_tasks, "rebuild_institution_sajeong_rate_stats", _sajeong)
    monkeypatch.setattr(scheduled_tasks, "rebuild_win_interval_stats", _win_interval, raising=False)

    outcome = scheduled_tasks._refresh_institution_sajeong_stats_thread()

    assert calls == ["sajeong", "win_interval"]
    assert outcome["stats_rebuilt"] == {"rows": 1}
    assert outcome["win_interval_rebuilt"] == {"rows": 2}


def test_refresh_thread_keeps_sajeong_result_when_win_interval_fails(monkeypatch) -> None:
    from src.tasks import scheduled_tasks

    called: list[bool] = []
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(scheduled_tasks, "link_prearng_dminstt", lambda session: 1)
    monkeypatch.setattr(
        scheduled_tasks,
        "rebuild_institution_sajeong_rate_stats",
        lambda session: {"rows": 1},
    )

    def _fail(session):
        called.append(True)
        raise RuntimeError("승리 구간 재집계 실패")

    monkeypatch.setattr(scheduled_tasks, "rebuild_win_interval_stats", _fail, raising=False)

    outcome = scheduled_tasks._refresh_institution_sajeong_stats_thread()

    assert called == [True]
    assert outcome["stats_rebuilt"] == {"rows": 1}
    assert "win_interval_rebuilt" not in outcome


# ============================================================================
# 모델·마이그레이션
# ============================================================================


def test_model_unique_key_and_collation() -> None:
    model = _load_model()
    constraints = [
        constraint
        for constraint in model.__table__.constraints
        if constraint.name == "uq_win_interval_stats"
    ]
    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == [
        "scope",
        "institution_name",
        "category",
        "lwlt_rate",
        "window_days",
    ]
    ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
    assert "utf8mb4_unicode_ci" in ddl
    assert "lwlt_rate" in ddl
    assert "p05" in ddl
    assert "p95" in ddl


def test_migration_is_idempotent_and_has_single_head() -> None:
    assert MIGRATION_PATH.exists(), "승리 구간 통계 마이그레이션이 없습니다."
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    assert list(script.get_heads()) == [REVISION]

    spec = importlib.util.spec_from_file_location("win_interval_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == REVISION
    assert module.down_revision == PREVIOUS_REVISION

    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                module.upgrade()
                module.upgrade()
                assert "win_interval_stats" in inspect(connection).get_table_names()
                module.downgrade()
                module.downgrade()
                assert "win_interval_stats" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'mysql_collate="utf8mb4_unicode_ci"' in source
