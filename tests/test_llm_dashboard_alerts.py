"""tests/test_llm_dashboard_alerts.py

RAG LLM 관측성 대시보드(llm_generation.json) 및 Prometheus 알람 규칙 검증.
- Grafana 대시보드 JSON 파싱, 스키마 버전, datasource uid 정합성
- 4대 RAG LLM 지표(rag_llm_ttft_ms, rag_llm_generation_ms, rag_llm_tokens, rag_llm_requests) Prometheus 변환명 참조 단언
- backend·model 별 패널(TTFT P50/P95, 생성 시간 P95, 초당 요청 수·오류율, 입출력 토큰 증가율) 구성 단언
- prometheus_rules.yml YAML 파싱 및 3대 LLM 알람 규칙(오류율, TTFT P95, 트래픽 단절) 임계값/지속시간 단언
- 기존 SLO 알람 규칙 무결성 보존 단언
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = PROJECT_ROOT / "docker" / "grafana" / "dashboards" / "llm_generation.json"
RULES_PATH = PROJECT_ROOT / "docker" / "prometheus_rules.yml"

# Prometheus 변환 표준 지표 명칭
PROM_TTFT_BUCKET = "rag_llm_ttft_ms_milliseconds_bucket"
PROM_GEN_BUCKET = "rag_llm_generation_ms_milliseconds_bucket"
PROM_REQUESTS_TOTAL = "rag_llm_requests_total"
PROM_TOKENS_TOTAL = "rag_llm_tokens_total"


def _load_dashboard() -> dict:
    assert DASHBOARD_PATH.is_file(), f"대시보드 파일이 없습니다: {DASHBOARD_PATH}"
    with DASHBOARD_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _load_rules() -> dict:
    assert RULES_PATH.is_file(), f"규칙 파일이 없습니다: {RULES_PATH}"
    with RULES_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_llm_dashboard_json_structure_and_datasource():
    """대시보드 JSON 기본 구조, 스키마 버전, datasource uid 가 기존 표준과 일치하는지 검증합니다."""
    data = _load_dashboard()
    assert data.get("schemaVersion") == 39
    assert data.get("uid") == "bidbox-llm-generation"
    assert "RAG LLM" in data.get("title", "") or "LLM generation" in data.get("title", "")

    panels = data.get("panels", [])
    assert len(panels) >= 4, "최소 4개 이상의 패널이 필요합니다."

    for panel in panels:
        ds = panel.get("datasource", {})
        assert ds.get("type") == "prometheus", "패널 datasource 타입은 prometheus 여야 합니다."
        assert ds.get("uid") == "prometheus", "패널 datasource uid 는 prometheus 여야 합니다."


def test_llm_dashboard_references_all_four_metrics():
    """대시보드가 4대 RAG LLM Prometheus 변환 메트릭을 모두 참조하는지 검증합니다."""
    data = _load_dashboard()
    all_exprs = [
        target.get("expr", "")
        for panel in data.get("panels", [])
        for target in panel.get("targets", [])
    ]
    joined_exprs = "\n".join(all_exprs)

    assert PROM_TTFT_BUCKET in joined_exprs, f"{PROM_TTFT_BUCKET} 가 대시보드에 참조되어야 합니다."
    assert PROM_GEN_BUCKET in joined_exprs, f"{PROM_GEN_BUCKET} 가 대시보드에 참조되어야 합니다."
    assert PROM_REQUESTS_TOTAL in joined_exprs, (
        f"{PROM_REQUESTS_TOTAL} 가 대시보드에 참조되어야 합니다."
    )
    assert PROM_TOKENS_TOTAL in joined_exprs, (
        f"{PROM_TOKENS_TOTAL} 가 대시보드에 참조되어야 합니다."
    )


def test_llm_dashboard_panel_metrics_and_quantiles():
    """대시보드가 backend·model 별 TTFT P50/P95, 생성 시간 P95, 요청 수, 오류율, 토큰 증가율을 포함하는지 검증합니다."""
    data = _load_dashboard()
    panels = data.get("panels", [])

    all_targets = [target for panel in panels for target in panel.get("targets", [])]
    exprs = [t.get("expr", "") for t in all_targets]

    # 1. TTFT P95 및 P50
    has_ttft_p95 = any(PROM_TTFT_BUCKET in e and "0.95" in e for e in exprs)
    has_ttft_p50 = any(PROM_TTFT_BUCKET in e and "0.5" in e for e in exprs)
    assert has_ttft_p95, "TTFT P95 PromQL 이 있어야 합니다."
    assert has_ttft_p50, "TTFT P50 PromQL 이 있어야 합니다."

    # 2. 생성 시간 P95
    has_gen_p95 = any(PROM_GEN_BUCKET in e and "0.95" in e for e in exprs)
    assert has_gen_p95, "생성 시간 P95 PromQL 이 있어야 합니다."

    # 3. 요청 수 및 오류율
    has_requests = any(PROM_REQUESTS_TOTAL in e for e in exprs)
    has_error_rate = any(PROM_REQUESTS_TOTAL in e and 'outcome="error"' in e for e in exprs)
    assert has_requests, "초당 요청 수 PromQL 이 있어야 합니다."
    assert has_error_rate, "오류율 PromQL 이 있어야 합니다."

    # 4. 입력·출력 토큰 증가율
    has_tokens = any(PROM_TOKENS_TOTAL in e and "direction" in e for e in exprs)
    assert has_tokens, "토큰 증가율 PromQL 이 있어야 합니다."


def test_prometheus_rules_parses_and_preserves_existing():
    """prometheus_rules.yml 이 파싱되고 기존 SLO 알람 규칙이 보존되어 있는지 검증합니다."""
    rules_data = _load_rules()
    groups = rules_data.get("groups", [])
    assert len(groups) >= 1

    rule_names = {
        rule.get("alert") for group in groups for rule in group.get("rules", []) if "alert" in rule
    }

    # 기존 알람 규칙 보존 확인
    for existing_alert in (
        "PredictHttpP95High",
        "PredictHttpErrorRateHigh",
        "ChatStreamHttpP95High",
        "OtelCollectorDown",
    ):
        assert existing_alert in rule_names, f"기존 알람 규칙 '{existing_alert}' 이 누락되었습니다."


def test_prometheus_rules_contains_three_llm_alerts_with_thresholds():
    """3대 RAG LLM 알람 규칙(오류율, TTFT P95, 트래픽 단절)과 임계값 및 지속시간이 계약대로 존재하는지 단언합니다."""
    rules_data = _load_rules()
    rules_by_name = {
        rule.get("alert"): rule
        for group in rules_data.get("groups", [])
        for rule in group.get("rules", [])
        if "alert" in rule
    }

    # (a) LLM 오류율 5분간 10% 초과
    assert "RagLlmErrorRateHigh" in rules_by_name
    err_rule = rules_by_name["RagLlmErrorRateHigh"]
    assert err_rule.get("for") == "5m", "오류율 지속 시간은 5m 여야 합니다."
    assert "0.1" in err_rule.get("expr", ""), "오류율 임계값은 10%(0.1) 여야 합니다."
    assert PROM_REQUESTS_TOTAL in err_rule.get("expr", "")
    assert 'outcome="error"' in err_rule.get("expr", "")

    # (b) TTFT P95 10분간 3초(3000ms) 초과
    assert "RagLlmTtftP95High" in rules_by_name
    ttft_rule = rules_by_name["RagLlmTtftP95High"]
    assert ttft_rule.get("for") == "10m", "TTFT 알람 지속 시간은 10m 여야 합니다."
    assert "3000" in ttft_rule.get("expr", ""), "TTFT 임계값은 3초(3000ms) 여야 합니다."
    assert "0.95" in ttft_rule.get("expr", ""), "TTFT quantile 은 0.95 여야 합니다."
    assert PROM_TTFT_BUCKET in ttft_rule.get("expr", "")

    # (c) 15분간 LLM 요청 0건이면서 RAG HTTP 요청 발생
    assert "RagLlmRequestsZeroWithHttpTraffic" in rules_by_name
    traffic_rule = rules_by_name["RagLlmRequestsZeroWithHttpTraffic"]
    assert traffic_rule.get("for") == "15m", "트래픽 단절 지속 시간은 15m 여야 합니다."
    expr = traffic_rule.get("expr", "")
    assert PROM_REQUESTS_TOTAL in expr
    assert "== 0" in expr
    assert "http_server_request_count_total" in expr
    assert "/chatbot/chat/stream" in expr
