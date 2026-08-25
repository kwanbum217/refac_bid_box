"""LLM 품질 평가 fixture 실측 하네스.

fixture 의 문항을 운영 RAG 질의 경로(`/api/v1/chatbot/query`)로 보내고, 응답을
문항별 기대 사실과 대조해 채점 가능한 raw 를 남긴다. 모델 전환은 컨테이너의
OLLAMA_MODEL 환경변수로 이루어지므로 이 스크립트는 전환을 수행하지 않고,
현재 서빙 중인 모델을 provenance 에 기록한다.

자동 채점은 다음만 판정한다.
- numeric 팩트: 응답 본문에서 기대 수치를 허용오차 안에서 찾는다 (원자 단위).
- forbidden_literals: 내부 영문 코드(Servc, Thng, Cnstwk, Frgcpt 등)가 답변에 나타나는지 대소문자 무시 검사.
- semantic_forbidden_claims: 자기모순 등 문자열 매칭으로 판정 불가한 항목은 수동 판정 대상으로 별도 집계.
- citation_required: 대괄호 인용 표기가 있는지 본다.
- expected_evidence_ids: 검색된 문서가 기대 근거를 포함하는지 본다.
- refusal_expected: 답변이 거절인지 판정하여 기대와 실제가 일치하는지 채점한다.

proposition 팩트는 문자열 일치로 판정할 수 없으므로 자동 채점하지 않고 응답을
그대로 보존한다. 사람이나 별도 판정자가 rubric 으로 채점한다.

provenance 결박:
- --expected-model 필수: 시작/종료 OLLAMA_MODEL 이 모두 이 값과 일치해야 통과.
- base_url 이 app container 의 실제 발행 포트를 가리키는지 검증 (benchmark_provenance 재사용).
- 소스 Git SHA, dirty 여부, 시작/종료 source identity, 런타임 OLLAMA_MODEL 기록.
- dirty 이면 정식 근거로 저장하지 않음 (fail-closed).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

try:
    from scripts._strict_json import dump_strict_json
except ModuleNotFoundError:  # pragma: no cover - 직접 실행 경로
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

# benchmark_provenance 에서 재사용할 함수들
try:
    from scripts.benchmark_provenance import (
        _parse_published_host_ports,
        get_git_status,
        verify_provenance_consistency,
    )
except ModuleNotFoundError:  # pragma: no cover - 직접 실행 경로
    from benchmark_provenance import (  # type: ignore[no-redef]
        _parse_published_host_ports,
        get_git_status,
        verify_provenance_consistency,
    )

DEFAULT_BASE_URL = "http://localhost:8000"
QUERY_PATH = "/api/v1/chatbot/query"
CITATION_PATTERN = re.compile(r"\[\d+\]")

# 거절 판정용 패턴 (한국어 정중 거절 표현)
REFUSAL_PATTERNS = [
    re.compile(r"제공\s*할\s*수\s*없"),
    re.compile(r"알려\s*드릴\s*수\s*없"),
    re.compile(r"확인\s*할\s*수\s*없"),
    re.compile(r"답변\s*할\s*수\s*없"),
    re.compile(r"정보\s*가\s*없"),
    re.compile(r"데이터\s*가\s*없"),
    re.compile(r"근거\s*가\s*없"),
    re.compile(r"모르겠"),
    re.compile(r"알\s*수\s*없"),
    re.compile(r"확인\s*불가"),
    re.compile(r"제공\s*불가"),
    re.compile(r"범위\s*밖"),
    re.compile(r"수집\s*되지\s*않"),
    # 2026-08-25 v2 측정에서 발견한 누락이다. gemma4 계열은 근거가 없을 때
    # "컨텍스트에 포함되어 있지 않습니다" 로 거절하는데 이 표현이 없어 정상
    # 거절이 과잉응답으로 오분류됐다. e2b 의 거절 오답이 7건으로 부풀려졌고
    # 실제로는 2건이었다.
    re.compile(r"포함\s*되어\s*있지\s*않"),
    re.compile(r"포함\s*되지\s*않"),
    re.compile(r"제공\s*되지\s*않"),
    re.compile(r"찾을\s*수\s*없"),
]


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


def is_refusal(answer: str) -> bool:
    """답변이 거절 응답인지 판정한다."""
    if not answer or not answer.strip():
        return True
    answer_lower = answer.lower()
    return any(pattern.search(answer_lower) for pattern in REFUSAL_PATTERNS)


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
                "unit": fact.get("unit"),
                "tolerance": fact.get("tolerance"),
                "found": numeric_fact_found(
                    answer, fact.get("expected_value"), fact.get("tolerance")
                ),
            }
        )

    # forbidden_literals 위반 검사 (대소문자 무시, 매칭된 리터럴과 주변 문맥 기록)
    forbidden_violations = []
    for literal in item.get("forbidden_literals") or []:
        if not literal:
            continue
        # 대소문자 무시 검색
        pattern = re.compile(re.escape(literal), re.IGNORECASE)
        matches = list(pattern.finditer(answer))
        if matches:
            for match in matches:
                start = max(0, match.start() - 40)
                end = min(len(answer), match.end() + 40)
                context = answer[start:end]
                forbidden_violations.append(
                    {
                        "literal": literal,
                        "matched_text": match.group(),
                        "position": match.start(),
                        "context": context,
                    }
                )

    # semantic_forbidden_claims 는 자동 판정하지 않고 수동 판정 대상으로만 기록
    semantic_claims = list(item.get("semantic_forbidden_claims") or [])

    expected_ids = list(item.get("expected_evidence_ids") or [])
    evidence_hit = [eid for eid in expected_ids if eid in found_ids]

    citation_ok: bool | None = None
    if item.get("citation_required"):
        citation_ok = bool(CITATION_PATTERN.search(answer))

    # refusal 채점
    refusal_expected = bool(item.get("refusal_expected"))
    actual_refusal = is_refusal(answer)
    refusal_correct = refusal_expected == actual_refusal

    return {
        "answer": answer,
        "answer_chars": len(answer),
        "numeric_facts": numeric_results,
        "numeric_all_found": all(r["found"] for r in numeric_results) if numeric_results else None,
        "forbidden_literal_violations": forbidden_violations,
        "semantic_forbidden_claims": semantic_claims,
        "expected_evidence_ids": expected_ids,
        "retrieved_evidence_ids": found_ids,
        "evidence_hit": evidence_hit,
        "evidence_recall": (len(evidence_hit) / len(expected_ids)) if expected_ids else None,
        "citation_required": bool(item.get("citation_required")),
        "citation_present": citation_ok,
        "refusal_expected": refusal_expected,
        "actual_refusal": actual_refusal,
        "refusal_correct": refusal_correct,
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


def validate_base_url_port(base_url: str, app_container: str) -> tuple[bool, str]:
    """base_url 의 포트가 app container 의 실제 발행 포트와 일치하는지 검증한다.

    benchmark_provenance.py 의 _parse_published_host_ports 를 재사용한다.
    """
    try:
        # docker inspect 로 컨테이너 포트 매핑 조회
        raw_ports = subprocess.check_output(  # nosec B603 B607
            ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", app_container],
            text=True,
            timeout=30,
        ).strip()
        published_host_ports = _parse_published_host_ports(raw_ports)

        # base_url 에서 포트 추출
        parsed = urlparse.urlparse(base_url)
        req_port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if req_port in published_host_ports:
            return True, f"base_url port {req_port} matches container published port"
        else:
            return False, (
                f"base_url port {req_port} not bound to target container '{app_container}' "
                f"(published host ports: {sorted(published_host_ports) if published_host_ports else 'none'})"
            )
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        return False, f"포트 검증 실패: {exc}"


def build_provenance(
    *,
    git_sha: str,
    git_dirty: bool | None,
    started_model: str,
    ended_model: str,
    base_url: str,
    app_container: str,
) -> dict[str, Any]:
    """provenance 메타데이터를 구성한다."""
    # 시작/종료 시점의 source identity 수집
    _, start_dirty = get_git_status()
    end_sha, end_dirty = get_git_status()

    return {
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "source_identity_start": {
            "git_sha": git_sha,
            "git_dirty": start_dirty,
        },
        "source_identity_end": {
            "git_sha": end_sha,
            "git_dirty": end_dirty,
        },
        "serving_model_start": started_model,
        "serving_model_end": ended_model,
        "serving_model_consistent": bool(started_model) and started_model == ended_model,
        "base_url": base_url,
        "app_container": app_container,
        "timestamp_start_utc": datetime.now(UTC).isoformat(),
        "timestamp_end_utc": None,  # 나중에 채움
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 품질 평가 fixture 실측 하네스")
    parser.add_argument(
        "--fixture", type=Path, default=Path("data/eval/llm_quality_fixture_v1.json")
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model-label", required=True, help="측정 대상 모델 라벨 (기록용)")
    parser.add_argument(
        "--expected-model",
        required=True,
        help="기대하는 OLLAMA_MODEL 값 (시작/종료 모두 이 값과 일치해야 통과)",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--app-container", default="refac_bid_box-app-1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="문항 수 제한 (0=전체, 시험용)")
    args = parser.parse_args(argv)

    # 시작 시점 provenance 수집
    git_sha, git_dirty = get_git_status()
    if git_sha == "unknown":
        print("경고: Git SHA 를 가져올 수 없습니다.", file=sys.stderr)
    if git_dirty is None:
        print("경고: Git dirty 상태를 확인할 수 없습니다.", file=sys.stderr)

    # base_url 포트 결박 검증
    port_ok, port_msg = validate_base_url_port(args.base_url, args.app_container)
    if not port_ok:
        print(f"오류: base_url 포트 검증 실패 - {port_msg}", file=sys.stderr)
        return 2

    # dirty 면 정식 근거 저장 거부 (fail-closed)
    if git_dirty is True:
        print(
            "오류: 소스 트리가 dirty 상태입니다. 정식 근거로 저장할 수 없습니다. 커밋 또는 스태시 후 재시도하세요.",
            file=sys.stderr,
        )
        return 3

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

    # expected-model 검증: 시작/종료 모두 expected-model 과 정확히 일치해야 통과
    model_mismatch = False
    if started_model != args.expected_model:
        print(
            f"오류: 시작 시점 OLLAMA_MODEL('{started_model}')이 --expected-model('{args.expected_model}')과 다릅니다.",
            file=sys.stderr,
        )
        model_mismatch = True
    if ended_model != args.expected_model:
        print(
            f"오류: 종료 시점 OLLAMA_MODEL('{ended_model}')이 --expected-model('{args.expected_model}')과 다릅니다.",
            file=sys.stderr,
        )
        model_mismatch = True

    provenance = build_provenance(
        git_sha=git_sha,
        git_dirty=git_dirty,
        started_model=started_model,
        ended_model=ended_model,
        base_url=args.base_url,
        app_container=args.app_container,
    )
    provenance["timestamp_end_utc"] = datetime.now(UTC).isoformat()

    # provenance 일관성 검증 (시작/종료 source identity 비교)
    try:
        verify_provenance_consistency(
            provenance["source_identity_start"], provenance["source_identity_end"], strict=True
        )
    except Exception as exc:
        print(f"오류: Provenance 일관성 검증 실패 - {exc}", file=sys.stderr)
        return 4

    payload = {
        "schema": "LLM_QUALITY_MEASURE_V2",
        "timestamp": provenance["timestamp_end_utc"],
        "model_label": args.model_label,
        "expected_model": args.expected_model,
        "serving_model_start": started_model,
        "serving_model_end": ended_model,
        "serving_model_consistent": provenance["serving_model_consistent"],
        "model_match_expected": not model_mismatch,
        "base_url_validated": port_ok,
        "fixture_path": str(args.fixture),
        "fixture_version": fixture.get("version", "unknown"),
        "repetitions": args.repetitions,
        "item_count": len(items),
        "request_failures": failures,
        "provenance": provenance,
        "results": results,
    }

    # 모델 불일치나 요청 실패가 있으면 0 이 아닌 종료 코드
    exit_code = 0
    if model_mismatch:
        exit_code = 5
    elif failures > 0:
        exit_code = 1

    # 모델 불일치면 정식 근거로 저장하지 않음 (fail-closed)
    if model_mismatch:
        print("모델 불일치로 인해 결과를 정식 근거로 저장하지 않습니다.", file=sys.stderr)
        # 임시 파일로 저장하여 디버깅 가능하게 함
        debug_output = args.output.with_suffix(".debug.json")
        debug_output.parent.mkdir(parents=True, exist_ok=True)
        debug_output.write_text(dump_strict_json(payload), encoding="utf-8")
        print(f"디버그 출력 저장: {debug_output}", file=sys.stderr)
        return exit_code

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dump_strict_json(payload), encoding="utf-8")
    print(f"\n저장 완료: {args.output} (실패 {failures}건)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
