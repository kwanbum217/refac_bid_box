"""Meilisearch bid_records 순위 규칙(sort 우선)과 읽기 전용 측정 스크립트 검증.

- configure_index 가 rankingRules 를 words, sort, typo, proximity, attribute, exactness
  순서로 보내는지 확인합니다.
- 같은 설정 본문의 나머지 값이 변경 전 main 과 같은지 고정값으로 확인합니다.
- 측정 스크립트가 설정 변경 HTTP 메서드와 /settings 경로를 호출하지 않는지 가짜 전송으로
  확인하고, 표준출력 실행에서 비밀값을 내보내지 않는지 확인합니다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from src.app.services.search_index import (
    INDEX_MAX_TOTAL_HITS,
    RANKING_RULES,
    MeiliSearchClient,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "measure_meili_ranking.py"

EXPECTED_RANKING_RULES = ["words", "sort", "typo", "proximity", "attribute", "exactness"]
EXPECTED_SEARCHABLE = [
    "bid_ntce_nm",
    "bid_ntce_no",
    "dminstt_nm",
    "ntce_instt_nm",
    "bidwinnr_nm",
]
EXPECTED_FILTERABLE = [
    "dataset",
    "category",
    "qualification_analyzable",
    "is_cancelled",
    "region_codes",
    "participation_region_codes",
    "license_codes",
    "sucsf_bid_rate",
]
EXPECTED_SORTABLE = [
    "bid_ntce_dt",
    "bid_clse_dt",
    "base_amount",
    "rl_openg_dt",
    "sucsf_bid_amt",
    "sucsf_bid_rate",
    "region_rank",
    "source_id",
]


@pytest.fixture(scope="module")
def probe() -> Any:
    spec = importlib.util.spec_from_file_location("measure_meili_ranking_probe", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Recorder:
    def __init__(self, payloads: list[dict[str, Any]] | None = None):
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.payloads = payloads or []
        self.index = 0

    def __call__(self, method: str, url: str, **kwargs: Any) -> Mock:
        self.calls.append((method, url, kwargs))
        payload = (
            self.payloads[self.index]
            if self.index < len(self.payloads)
            else {
                "processingTimeMs": 7,
                "estimatedTotalHits": 123,
                "hits": [{"source_id": 1}, {"source_id": 2}],
            }
        )
        self.index += 1
        response = Mock()
        response.content = json.dumps(payload).encode()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response


def _install(
    monkeypatch: pytest.MonkeyPatch, payloads: list[dict[str, Any]] | None = None
) -> _Recorder:
    recorder = _Recorder(payloads)
    monkeypatch.setattr(httpx, "request", recorder)
    return recorder


# --------------------------------------------------------------------------- #
# (a) rankingRules 순서
# --------------------------------------------------------------------------- #


def test_ranking_rules_constant_places_sort_right_after_words():
    assert RANKING_RULES == EXPECTED_RANKING_RULES
    assert RANKING_RULES.index("sort") == RANKING_RULES.index("words") + 1


def test_configure_index_sends_ranking_rules_with_sort_after_words(monkeypatch):
    recorder = _install(monkeypatch)

    MeiliSearchClient(base_url="http://search", master_key="test-key").configure_index()

    settings_payload = recorder.calls[-1][2]["json"]
    assert settings_payload["rankingRules"] == EXPECTED_RANKING_RULES


# --------------------------------------------------------------------------- #
# (b) rankingRules 외 설정 값은 변경 전과 동일
# --------------------------------------------------------------------------- #


def test_configure_index_keeps_all_other_settings_unchanged(monkeypatch):
    recorder = _install(monkeypatch)

    MeiliSearchClient(base_url="http://search", master_key="test-key").configure_index()

    method, url, kwargs = recorder.calls[-1]
    assert method == "PATCH"
    assert url == "http://search/indexes/bid_records/settings"
    settings_payload = kwargs["json"]
    assert set(settings_payload) == {
        "rankingRules",
        "searchableAttributes",
        "filterableAttributes",
        "sortableAttributes",
        "pagination",
    }
    assert settings_payload["searchableAttributes"] == EXPECTED_SEARCHABLE
    assert settings_payload["filterableAttributes"] == EXPECTED_FILTERABLE
    assert settings_payload["sortableAttributes"] == EXPECTED_SORTABLE
    assert settings_payload["pagination"] == {"maxTotalHits": INDEX_MAX_TOTAL_HITS}


# --------------------------------------------------------------------------- #
# (c) 측정 스크립트는 읽기 전용이며 표준출력 실행에서 비밀값을 내보내지 않음
# --------------------------------------------------------------------------- #


def test_probe_sends_only_search_posts(probe, monkeypatch):
    recorder = _install(monkeypatch)
    client = MeiliSearchClient(base_url="http://search", master_key="test-key")

    report = probe.build_report(client, rounds=3)

    assert len(report["results"]) == len(probe.QUERY_BUNDLE) * len(probe.TARGETS)
    assert {method for method, _, _ in recorder.calls} == {"POST"}
    assert {url for _, url, _ in recorder.calls} == {"http://search/indexes/bid_records/search"}
    for _, url, kwargs in recorder.calls:
        assert "/settings" not in url
        body = kwargs["json"]
        assert body["sort"]
        assert body["filter"]
        assert body["attributesToRetrieve"] == ["source_id"]


def test_probe_reports_rounds_median_max_and_top_ids(probe, monkeypatch):
    payloads = [
        {
            "processingTimeMs": elapsed,
            "estimatedTotalHits": 99,
            "hits": [{"source_id": index} for index in range(7)],
        }
        for elapsed in (9, 1, 5)
    ]
    _install(monkeypatch, payloads)
    client = MeiliSearchClient(base_url="http://search", master_key="test-key")

    report = probe.build_report(
        client,
        queries=("정보화",),
        targets=probe.TARGETS[:1],
        rounds=3,
    )

    result = report["results"][0]
    assert [sample["processingTimeMs"] for sample in result["rounds"]] == [9, 1, 5]
    assert result["median_ms"] == 5
    assert result["max_ms"] == 9
    assert result["estimated_total_hits"] == 99
    assert result["top_ids"] == ["0", "1", "2", "3", "4"]


def test_probe_covers_two_filter_and_sort_targets(probe):
    report = probe.build_report(_NoCallClient(), queries=(), rounds=1)
    targets = {target["name"]: target for target in report["targets"]}

    assert targets["result_servc"]["filter"] == 'dataset = "result" AND category = "Servc"'
    assert targets["result_servc"]["sort"] == ["rl_openg_dt:desc", "source_id:desc"]
    assert targets["announcement_servc"]["filter"] == (
        'dataset = "announcement" AND category = "Servc" AND is_cancelled != true'
    )
    assert targets["announcement_servc"]["sort"] == ["bid_ntce_dt:desc", "source_id:desc"]


class _NoCallClient:
    def _request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("검색어가 없으면 전송이 없어야 합니다.")


def test_probe_stdout_has_machine_readable_json_without_secret(probe, monkeypatch, capsys):
    _install(monkeypatch)
    monkeypatch.setattr(
        probe,
        "load_client",
        lambda: MeiliSearchClient(base_url="http://search", master_key="super-secret-key"),
    )

    assert probe.main([]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["index_uid"] == "bid_records"
    assert report["expected_ranking_rules_from_code"] == EXPECTED_RANKING_RULES
    assert "super-secret-key" not in captured.out
    assert captured.err == ""
