"""협상 공고 과거 낙찰률 분포의 산식·캐시 회귀 테스트."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import mysql, sqlite

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services import negotiation_stats


def _detail_template() -> str:
    return Path("src/app/templates/bids/detail.html").read_text(encoding="utf-8")


def test_negotiation_template_uses_unique_distribution_id() -> None:
    template = _detail_template()

    assert template.count('id="negotiation-info"') == 1
    assert template.count('id="negotiation-distribution"') == 1
    assert "$('#negotiation-distribution').removeClass('hidden')" in template


def test_negotiation_branch_renders_distribution_before_return() -> None:
    template = _detail_template()
    branch_start = template.index("function renderNegotiation(data)")
    branch_end = template.index("function usesFallbackModel", branch_start)
    branch = template[branch_start:branch_end]

    assert "renderNegotiationDistribution(data);" in branch
    assert branch.index("renderNegotiationDistribution(data);") < branch.index("return true;")


def _add_pair(db, no: str, base: int, awarded: int, method: str, ord_: str = "000") -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category="Servc",
            base_amount=base,
            bid_ntce_dt=datetime(2026, 6, 1),
            raw_data={"sucsfbidMthdNm": method},
        )
    )
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category="Servc",
            sucsf_bid_amt=awarded,
            rl_openg_dt=datetime(2026, 6, 2),
        )
    )
    db.commit()


def test_distribution_excludes_out_of_range_and_zero_base(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "valid", 100, 95, "협상에의한계약")
    _add_pair(isolated_db, "low", 100, 49, "협상에의한계약")
    _add_pair(isolated_db, "high", 100, 111, "협상에의한계약")
    _add_pair(isolated_db, "zero", 0, 95, "협상에의한계약")

    result = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    assert result == {
        "valid_count": 1,
        "average": Decimal("95.0000"),
        "median": Decimal("95.0000"),
        "minimum": Decimal("95.0000"),
        "maximum": Decimal("95.0000"),
    }


def test_distribution_second_call_uses_cache(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "cached", 100, 90, "협상에의한계약")
    first = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    def fail_query(*args, **kwargs):
        raise AssertionError("두 번째 호출에서 DB를 조회하면 안 됩니다")

    monkeypatch.setattr(negotiation_stats, "_rows", fail_query)
    assert negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD") == first


class _CompileOnlyDB:
    def __init__(self, dialect):
        self._bind = SimpleNamespace(dialect=dialect)
        self.statement = None

    def get_bind(self):
        return self._bind

    def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: [])


def test_rows_builds_mysql_specific_sql_without_connecting_to_mysql():
    db = _CompileOnlyDB(mysql.dialect())

    assert negotiation_stats._rows(db, "STANDARD") == []

    sql = str(db.statement.compile(dialect=mysql.dialect())).lower()
    assert "lpad" in sql
    assert "json_unquote" in sql


def test_rows_builds_sqlite_specific_sql_without_connecting_to_mysql():
    db = _CompileOnlyDB(sqlite.dialect())

    assert negotiation_stats._rows(db, "STANDARD") == []

    sql = str(db.statement.compile(dialect=sqlite.dialect())).lower()
    assert "printf" in sql


def test_each_negotiation_variant_only_matches_its_own_marker(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    markers = {
        "STANDARD": "협상에의한계약",
        "SW": "협상에의한계약(SW사업)",
        "ENGINEERING": "협상에의한계약(엔지니어링)",
        "CONSTRUCTION_ENGINEERING": "협상에의한계약(건설엔지니어링)",
    }
    for index, method in enumerate(markers.values()):
        _add_pair(isolated_db, f"variant-{index}", 100, 90, method)

    for variant in markers:
        result = negotiation_stats.get_negotiation_stats(isolated_db, variant)
        assert result["valid_count"] == 1
        assert result["average"] == Decimal("90.0000")


def test_standard_does_not_swallow_marked_variants(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "standard-only", 100, 90, "협상에의한계약")
    _add_pair(isolated_db, "sw", 100, 80, "협상에의한계약(SW사업)")
    _add_pair(isolated_db, "engineering", 100, 70, "협상에의한계약(엔지니어링)")
    _add_pair(isolated_db, "construction-engineering", 100, 60, "협상에의한계약(건설엔지니어링)")

    result = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    assert result["valid_count"] == 1
    assert result["average"] == Decimal("90.0000")


def test_engineering_does_not_match_construction_engineering(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "engineering", 100, 70, "협상에의한계약(엔지니어링)")
    _add_pair(isolated_db, "construction-engineering", 100, 60, "협상에의한계약(건설엔지니어링)")

    result = negotiation_stats.get_negotiation_stats(isolated_db, "ENGINEERING")

    assert result["valid_count"] == 1
    assert result["average"] == Decimal("70.0000")


def test_negotiation_rate_boundaries_are_included(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "lower-bound", 100, 50, "협상에의한계약")
    _add_pair(isolated_db, "upper-bound", 100, 110, "협상에의한계약")

    result = negotiation_stats.get_negotiation_stats(isolated_db, "STANDARD")

    assert result == {
        "valid_count": 2,
        "average": Decimal("80.0000"),
        "median": Decimal("80.0000"),
        "minimum": Decimal("50.0000"),
        "maximum": Decimal("110.0000"),
    }


def test_empty_and_unknown_variants_return_empty_distribution(isolated_db, monkeypatch):
    store = {}
    monkeypatch.setattr(negotiation_stats.cache, "get", store.get)
    monkeypatch.setattr(
        negotiation_stats.cache, "set", lambda key, value, ttl: store.update({key: value})
    )
    _add_pair(isolated_db, "known", 100, 90, "협상에의한계약")

    for variant in ("CONSTRUCTION_ENGINEERING", "NOT_A_VARIANT"):
        result = negotiation_stats.get_negotiation_stats(isolated_db, variant)
        assert result == {
            "valid_count": 0,
            "average": None,
            "median": None,
            "minimum": None,
            "maximum": None,
        }
