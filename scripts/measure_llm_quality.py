"""LLM 품질 평가 fixture 실측 하네스.

fixture 의 문항을 운영 RAG 질의 경로(`/api/v1/chatbot/query`)로 보내고, 응답을
문항별 기대 사실과 대조해 채점 가능한 raw 를 남긴다. 모델 전환은 컨테이너의
OLLAMA_MODEL 환경변수로 이루어지므로 이 스크립트는 전환을 수행하지 않고,
현재 서빙 중인 모델을 provenance 에 기록한다.

자동 채점은 다음만 판정한다.
- numeric 팩트: 응답 본문에서 기대 수치를 허용오차 안에서 찾는다.
- must_not_claim: 금지 진술 문자열이 응답에 나타나는지 본다.
- citation_required: 대괄호 인용 표기가 있는지 본다.
- expected_evidence_ids: 검색된 문서가 기대 근거를 포함하는지 본다.

proposition 팩트는 문자열 일치로 판정할 수 없으므로 자동 채점하지 않고 응답을
그대로 보존한다. 사람이나 별도 판정자가 rubric 으로 채점한다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    from scripts._strict_json import dump_strict_json
except ModuleNotFoundError:  # pragma: no cover - 직접 실행 경로
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

DEFAULT_BASE_URL = "http://localhost:8000"
QUERY_PATH = "/api/v1/chatbot/query"
CITATION_PATTERN = re.compile(r"\[\d+\]")


def send_query(base_url: str, question: str, timeout_sec: float) -> dict[str, Any]:
    """운영 RAG 질의 경로로 질문을 보내고 응답과 소요 시간을 반환한다."""
    body = json.dumps({"query": question}).encode("utf-8")
    req = urlrequest.Request(  # nosec B310
        f"{base_url}{QUERY_PATH}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": True, "elapsed_ms": elapsed_ms, "payload": payload}
    except (urlerror.URLError, TimeoutError, OSError, ValueError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc)}


def normalize_number_text(text: str) -> str:
    """숫자 비교를 위해 자릿수 구분 쉼표만 제거한다."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def numeric_fact_found(answer: str, expected_value: str, tolerance: float | None) -> bool:
    """응답 본문에서 기대 수치를 허용오차 안에서 찾는다."""
    try:
        target = float(str(expected_value).replace(",", ""))
    except (TypeError, ValueError):
        return False
    tol = float(tolerance) if tolerance is not None else 0.0
    for token in re.findall(r"-?\d+(?:\.\d+)?", normalize_number_text(answer)):
        try:
            value = float(token)
        except ValueError:
            continue
        if abs(value - target) <= tol:
            return True
    return False


def retrieved_ids(payload: dict[str, Any]) -> list[str]:
    """응답의 retrieved_docs 에서 KB 문서 식별자를 추출한다.

    검색 응답의 metadata.id 는 정수(10015927)이고 ChromaDB 문서 id 는
    `bid_10015927` 형태이므로 접두를 붙여 fixture 의 근거 id 와 같은 공간에서
    비교한다.
    """
    ids: list[str] = []
    for doc in payload.get("retrieved_docs") or []:
        if not isinstance(doc, dict):
            continue
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        raw = doc.get("id") or (meta.get("id") if meta else None)
        if isinstance(raw, int):
            ids.append(f"bid_{raw}")
        elif isinstance(raw, str) and raw:
            ids.append(raw if raw.startswith("bid_") else f"bid_{raw}")
    return ids


def score_item(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """자동 판정 가능한 항목만 채점한다."""
    answer = str(payload.get("response") or "")
    found_ids = retrieved_ids(payload)

    numeric_results = []
    for fact in item.get("expected_facts") or []:
        if fact.get("fact_type") != "numeric":
            continue
        numeric_results.append(
            {
                "statement": fact.get("statement"),
                "expected_value": fact.get("expected_value"),
                "tolerance": fact.get("tolerance"),
                "found": numeric_fact_found(
                    answer, fact.get("expected_value"), fact.get("tolerance")
                ),
            }
        )

    violated = [
        claim
        for claim in item.get("must_not_claim") or []
        if isinstance(claim, str) and claim and claim in answer
    ]

    expected_ids = list(item.get("expected_evidence_ids") or [])
    evidence_hit = [eid for eid in expected_ids if eid in found_ids]

    citation_ok: bool | None = None
    if item.get("citation_required"):
        citation_ok = bool(CITATION_PATTERN.search(answer))

    return {
        "answer": answer,
        "answer_chars": len(answer),
        "numeric_facts": numeric_results,
        "numeric_all_found": all(r["found"] for r in numeric_results) if numeric_results else None,
        "must_not_claim_violations": violated,
        "expected_evidence_ids": expected_ids,
        "retrieved_evidence_ids": found_ids,
        "evidence_hit": evidence_hit,
        "evidence_recall": (len(evidence_hit) / len(expected_ids)) if expected_ids else None,
        "citation_required": bool(item.get("citation_required")),
        "citation_present": citation_ok,
        "refusal_expected": bool(item.get("refusal_expected")),
    }


def serving_model(container: str) -> str:
    """서빙 컨테이너의 OLLAMA_MODEL 을 읽는다.

    API 는 모델명을 노출하지 않으므로 컨테이너 환경변수를 정본으로 쓴다.
    읽지 못하면 빈 문자열을 돌려주고, 호출 측이 측정을 무효로 판정한다.
    """
    try:
        out = subprocess.check_output(  # nosec B603 B607
            ["docker", "exec", container, "printenv", "OLLAMA_MODEL"],
            text=True,
            timeout=30,
        ).strip()
        return out
    except (subprocess.SubprocessError, OSError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 품질 평가 fixture 실측 하네스")
    parser.add_argument(
        "--fixture", type=Path, default=Path("data/eval/llm_quality_fixture_v1.json")
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model-label", required=True, help="측정 대상 모델 라벨 (기록용)")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--app-container", default="refac_bid_box-app-1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="문항 수 제한 (0=전체, 시험용)")
    args = parser.parse_args(argv)

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    items = fixture["items"] if isinstance(fixture, dict) and "items" in fixture else fixture
    if args.limit:
        items = items[: args.limit]

    started_model = serving_model(args.app_container)
    results: list[dict[str, Any]] = []
    failures = 0

    for item in items:
        for rep in range(1, args.repetitions + 1):
            outcome = send_query(args.base_url, item["question"], args.timeout_sec)
            record: dict[str, Any] = {
                "id": item["id"],
                "repetition": rep,
                "context_sufficient": bool(item.get("context_sufficient")),
                "elapsed_ms": round(outcome["elapsed_ms"], 3),
                "ok": outcome["ok"],
            }
            if outcome["ok"]:
                record.update(score_item(item, outcome["payload"]))
            else:
                record["error"] = outcome.get("error")
                failures += 1
            results.append(record)
            print(
                f"{item['id']} r{rep} ok={outcome['ok']} {outcome['elapsed_ms']:.0f}ms",
                flush=True,
            )

    ended_model = serving_model(args.app_container)
    payload = {
        "schema": "LLM_QUALITY_MEASURE_V1",
        "timestamp": datetime.now(UTC).isoformat(),
        "model_label": args.model_label,
        "serving_model_start": started_model,
        "serving_model_end": ended_model,
        "serving_model_consistent": bool(started_model) and started_model == ended_model,
        "fixture_path": str(args.fixture),
        "repetitions": args.repetitions,
        "item_count": len(items),
        "request_failures": failures,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dump_strict_json(payload), encoding="utf-8")
    print(f"\n저장 완료: {args.output} (실패 {failures}건)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
