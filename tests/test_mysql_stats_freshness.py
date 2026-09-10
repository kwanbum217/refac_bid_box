"""scripts/check_mysql_stats_freshness.py 에 대한 단위 테스트.

실제 DB 없이 조회 결과를 주입해 판정 로직만 고정한다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from scripts.check_mysql_stats_freshness import (
    DEFAULT_MAX_DRIFT_PCT,
    DEFAULT_MAX_STALE_DAYS,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_STALE,
    build_payload,
    compute_age_days,
    compute_drift_pct,
    evaluate_table,
    main,
    parse_expected_rows,
)

NOW = datetime(2026, 9, 11, 12, 0, 0)


def test_편차율_계산이_정확하다() -> None:
    assert compute_drift_pct(2295025, 5504119) == pytest.approx(58.3, abs=0.1)
    assert compute_drift_pct(6377745, 5504119) == pytest.approx(15.9, abs=0.1)
    assert compute_drift_pct(100, 100) == pytest.approx(0.0)
    assert compute_drift_pct(100, None) is None
    assert compute_drift_pct(100, 0) is None


def test_경과일_계산이_정확하다() -> None:
    assert compute_age_days(
        datetime(2026, 9, 1, 4, 7, 23), datetime(2026, 9, 11, 4, 7, 23)
    ) == pytest.approx(10.0)
    assert compute_age_days(NOW, NOW) == pytest.approx(0.0)


def test_기준행수_지정_파싱이_정확하다() -> None:
    assert parse_expected_rows("bid_results=3431580,bid_announcements=5504119") == {
        "bid_results": 3431580,
        "bid_announcements": 5504119,
    }
    with pytest.raises(ValueError):
        parse_expected_rows("bid_results")
    with pytest.raises(ValueError):
        parse_expected_rows("bid_results=abc")
    with pytest.raises(ValueError):
        parse_expected_rows("bid_results=-1")


def test_임계_이내는_정상이다() -> None:
    item = evaluate_table(
        "bid_results", 3388123, NOW, 3431580, NOW, DEFAULT_MAX_DRIFT_PCT, DEFAULT_MAX_STALE_DAYS
    )
    assert item["status"] == "OK"
    assert item["stale"] is False
    assert item["drift_pct"] == pytest.approx(1.3, abs=0.1)


def test_편차_초과는_임계위반이다() -> None:
    item = evaluate_table(
        "bid_announcements",
        2295025,
        NOW,
        5504119,
        NOW,
        DEFAULT_MAX_DRIFT_PCT,
        DEFAULT_MAX_STALE_DAYS,
    )
    assert item["status"] == "STALE"
    assert item["stale"] is True
    assert "편차" in item["reason"]


def test_경과일_초과는_임계위반이다() -> None:
    item = evaluate_table(
        "bid_results",
        3388123,
        datetime(2026, 9, 1, 4, 7, 23),
        None,
        NOW,
        DEFAULT_MAX_DRIFT_PCT,
        DEFAULT_MAX_STALE_DAYS,
    )
    assert item["status"] == "STALE"
    assert item["drift_pct"] is None
    assert "경과" in item["reason"]


def test_통계행이_없으면_정상으로_보지_않는다() -> None:
    item = evaluate_table(
        "bid_new", None, None, None, NOW, DEFAULT_MAX_DRIFT_PCT, DEFAULT_MAX_STALE_DAYS
    )
    assert item["status"] == "MISSING"
    assert item["stale"] is True


def test_갱신시각만_NULL이어도_정상으로_보지_않는다() -> None:
    item = evaluate_table(
        "bid_announcements",
        5_504_119,
        None,
        5_504_119,
        NOW,
        DEFAULT_MAX_DRIFT_PCT,
        DEFAULT_MAX_STALE_DAYS,
    )
    assert item["status"] == "MISSING"
    assert item["stale"] is True


def test_정상_종료코드는_0이다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.check_mysql_stats_freshness as checker

    monkeypatch.setattr(
        checker,
        "fetch_stats",
        lambda tables: (NOW, dict.fromkeys(tables, (100, NOW))),
    )
    assert main(["--tables", "bid_results", "--expected-rows", "bid_results=100"]) == EXIT_OK
    assert "OK" in capsys.readouterr().out


def test_임계초과_종료코드는_1이다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.check_mysql_stats_freshness as checker

    monkeypatch.setattr(
        checker,
        "fetch_stats",
        lambda tables: (NOW, dict.fromkeys(tables, (10, NOW))),
    )
    assert main(["--tables", "bid_results", "--expected-rows", "bid_results=100"]) == EXIT_STALE
    assert "STALE" in capsys.readouterr().out


def test_도구오류_종료코드는_2이다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.check_mysql_stats_freshness as checker

    assert main(["--tables", "bid_results", "--expected-rows", "형식오류"]) == EXIT_ERROR
    capsys.readouterr()

    def broken_fetch(tables: list[str]) -> tuple[datetime, dict[str, tuple[int, datetime | None]]]:
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(checker, "fetch_stats", broken_fetch)
    assert main(["--tables", "bid_results"]) == EXIT_ERROR


def test_json_출력은_기계판독_가능하다(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.check_mysql_stats_freshness as checker

    monkeypatch.setattr(
        checker,
        "fetch_stats",
        lambda tables: (NOW, dict.fromkeys(tables, (10, NOW))),
    )
    assert (
        main(["--tables", "bid_results", "--expected-rows", "bid_results=100", "--json"])
        == EXIT_STALE
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == EXIT_STALE
    assert payload["stale"] is True
    assert payload["thresholds"]["max_drift_pct"] == DEFAULT_MAX_DRIFT_PCT
    assert payload["thresholds"]["max_stale_days"] == DEFAULT_MAX_STALE_DAYS
    assert payload["tables"][0]["table"] == "bid_results"


def test_페이로드_구조가_고정된다() -> None:
    payload = build_payload([], DEFAULT_MAX_DRIFT_PCT, DEFAULT_MAX_STALE_DAYS, EXIT_OK)
    assert payload == {
        "thresholds": {
            "max_drift_pct": DEFAULT_MAX_DRIFT_PCT,
            "max_stale_days": DEFAULT_MAX_STALE_DAYS,
        },
        "tables": [],
        "stale": False,
        "exit_code": EXIT_OK,
    }
