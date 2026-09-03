#!/usr/bin/env python3
"""
scripts/orca_run_reviewer.py

Level 2 독립 리뷰어를 일회성으로 실행하고 보고 계약을 검증하여 판정 블록을 출력합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        char_len,
        load_capsule,
        truncate,
    )
    from scripts.orca_model_router import provider_for_model
    from scripts.validate_review_report import evaluate, parse_checklist
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        char_len,
        load_capsule,
        truncate,
    )
    from scripts.orca_model_router import provider_for_model
    from scripts.validate_review_report import evaluate, parse_checklist

DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_MODEL_TIMEOUT = 600
DEFAULT_GIT_TIMEOUT = 10
# 2026-08-31 실측: 최근 Wave G/H Task diff 5건의 문자 수 = 5,066 / 9,153 / 23,916 / 24,232 / 38,401.
# 최대 38,401 자를 약 30 % 여유로 넘긴 50,000 자를 기본 상한으로 한다.
DEFAULT_MAX_DIFF_CHARS = 50000
DEFAULT_MAX_CHARS = 1500
SUPPORTED_REVIEWER_PROVIDERS: frozenset[str] = frozenset({"gemini", "claude", "cerebras", "qwen"})


class ReviewerToolError(Exception):
    """리뷰어 도구 자체 오류 (Capsule 누락, git 실패, 타임아웃, 모델 실패 등)."""


def run_command_safe(
    cmd: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[int, str, str, bool]:
    """subprocess 명령을 실행하고 (returncode, stdout, stderr, timed_out) 을 반환합니다."""
    try:
        proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return -1, stdout, stderr, True
    except FileNotFoundError as exc:
        raise ReviewerToolError(f"실행 파일을 찾을 수 없음 ({cmd[0]}): {exc}") from exc
    except Exception as exc:
        raise ReviewerToolError(f"명령 실행 실패 ({' '.join(cmd)}): {exc}") from exc


def get_git_diff_and_files(
    repo: Path,
    base: str,
    branch: str,
    paths: list[str] | None = None,
    timeout: int = DEFAULT_GIT_TIMEOUT,
) -> tuple[list[str], str]:
    """git diff 로 변경 파일 목록과 diff 본문을 조회합니다."""
    path_args = ["--", *paths] if paths else []

    # 1. changed_files
    diff_name_cmd = ["git", "diff", "--name-only", f"{base}...{branch}", *path_args]
    code, stdout, stderr, timed_out = run_command_safe(diff_name_cmd, repo, timeout)
    if timed_out:
        raise ReviewerToolError(f"git diff 파일 목록 조회 타임아웃 ({timeout}초)")
    if code != 0:
        raise ReviewerToolError(
            f"git diff 파일 목록 조회 실패 (종료 코드 {code}): {stderr.strip()}"
        )

    changed_files = [line.strip() for line in stdout.splitlines() if line.strip()]

    # 2. diff 본문
    diff_cmd = ["git", "diff", f"{base}...{branch}", *path_args]
    code, stdout, stderr, timed_out = run_command_safe(diff_cmd, repo, timeout)
    if timed_out:
        raise ReviewerToolError(f"git diff 본문 조회 타임아웃 ({timeout}초)")
    if code != 0:
        raise ReviewerToolError(f"git diff 본문 조회 실패 (종료 코드 {code}): {stderr.strip()}")

    return changed_files, stdout


def _extract_capsule_context(capsule_text: str) -> dict[str, str]:
    """Capsule 에서 Reviewer 판단에 필요한 핵심 필드를 raw 블록 텍스트로 추출합니다.

    objective, acceptance, ground_truth, allowed_write_files 만 compact 하게 추출합니다.
    PyYAML 을 사용하지 않고 최상위 키의 들여쓰기 블록을 그대로 반환합니다.
    """
    target_keys = ("objective", "acceptance", "ground_truth", "allowed_write_files")
    context: dict[str, str] = {}
    lines = capsule_text.splitlines()
    total = len(lines)

    for key in target_keys:
        start_idx = -1
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}:\s*", line):
                start_idx = i
                break
        if start_idx == -1:
            continue

        end_idx = total
        for j in range(start_idx + 1, total):
            raw = lines[j]
            if raw and not raw[0].isspace() and not raw.startswith("#"):
                end_idx = j
                break

        block = "\n".join(lines[start_idx:end_idx]).strip()
        if block:
            context[key] = block

    return context


def build_prompt(
    checklist: list[dict[str, str]],
    changed_files: list[str],
    diff_text: str,
    diff_truncated: bool = False,
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
    capsule_context: dict[str, Any] | None = None,
) -> str:
    """리뷰어에게 전달할 프롬프트를 조립합니다."""
    checklist_lines: list[str] = []
    for item in checklist:
        c_id = item.get("id", "")
        q = item.get("question", "")
        d = item.get("defect_when", "")
        h = item.get("how", "")
        entry = f"- ID: {c_id}\n  질문: {q}\n  결함 조건(defect_when): {d}"
        if h:
            entry += f"\n  검증 방법(how): {h}"
        checklist_lines.append(entry)

    checklist_formatted = "\n".join(checklist_lines)
    files_formatted = (
        "\n".join(f"- {f}" for f in changed_files) if changed_files else "(변경 파일 없음)"
    )

    diff_header = ""
    if diff_truncated:
        diff_header = f"\n[주의: diff 본문이 최대 허용 크기({max_diff_chars}자)를 초과하여 뒷부분이 절단되었습니다.]\n"

    context_section = ""
    if capsule_context:
        ctx_parts: list[str] = []
        for key in ("objective", "acceptance", "ground_truth", "allowed_write_files"):
            val = capsule_context.get(key, "")
            if val:
                ctx_parts.append(val)
        if ctx_parts:
            context_section = "\n=== Task 컨텍스트 ===\n" + "\n\n".join(ctx_parts) + "\n"

    prompt = f"""당신은 refac_bid_box 프로젝트의 독립 코드 리뷰어(Level 2 Reviewer)입니다.
제공된 git diff 와 변경 파일 목록을 면밀히 검토하고, 아래 review_checklist 의 모든 항목에 대해 엄격하게 평가하십시오.

=== 검토 대상 변경 파일 목록 ===
{files_formatted}

=== 검토 대상 Git Diff ==={diff_header}
{diff_text}
{context_section}
=== 검토 체크리스트 (review_checklist) ===
{checklist_formatted}

=== 반환 형식 및 필수 계약 규칙 ===
1. 반드시 순수한 JSON 객체(ORCA_REVIEW_DONE_V2)만 출력하십시오. 마크다운 코드펜스(```json)나 앞뒤 부가 설명 텍스트를 절대 붙이지 마십시오.
2. `checklist_results` 배열에 위 체크리스트의 모든 ID에 대한 검토 결과를 빠짐없이 포함하십시오.
3. 각 `checklist_results` 항목은 반드시 다음 필드를 포함해야 합니다:
   - `id`: 체크리스트 항목 ID (예: "C1")
   - `answer`: "yes" 또는 "no" (체크리스트 질문에 대한 답변)
   - `evidence`: 판단 근거 (구체적인 파일 경로:줄번호 또는 분석 내용)
4. 중요 결함 규칙:
   - 각 항목의 `answer` 가 해당 항목의 `defect_when` 과 일치하면 결함(Defect)으로 판정됩니다.
   - 결함으로 판정된 모든 항목의 ID(예: "C1")는 반드시 `blocking_issues` 배열에 포함되어야 합니다.
5. `verdict` 규칙:
   - 결함이 0건이고 모든 체크리스트를 통과했으면 "pass"
   - 결함이 1건 이상 존재하면 "fail"
6. 아래 JSON 구조를 준수하십시오:
{{
  "schema": "ORCA_REVIEW_DONE_V2",
  "version": "2.1.0",
  "verdict": "pass",
  "checklist_results": [
    {{
      "id": "C1",
      "answer": "no",
      "evidence": "src/foo.py:42 - 해당 규칙 위반 없음 확인"
    }}
  ],
  "blocking_issues": [],
  "unverified_claims": [],
  "missing_tests": []
}}
"""
    return prompt.strip()


def build_model_command(
    model: str,
    prompt: str,
    timeout: int = DEFAULT_MODEL_TIMEOUT,
) -> list[str]:
    """모델 ID 와 프롬프트, 타임아웃으로부터 실행할 CLI 명령어 인자 배열을 생성합니다.

    - gemini, claude, cerebras: agy CLI 사용
      ['agy', '--model', model, '--print', prompt, '--print-timeout', f'{timeout}s']
    - qwen: qwen CLI 단발 실행 (-p) 사용
      ['qwen', '-m', model, '-p', prompt]
    - 지원하지 않는 provider 또는 판정 불가 모델: ReviewerToolError 발생
    """
    try:
        provider = provider_for_model(model, strict=True)
    except Exception as exc:
        raise ReviewerToolError(
            f"모델 ID 에서 제공자를 판정할 수 없습니다 (모델: {model!r}): {exc}"
        ) from exc

    if provider not in SUPPORTED_REVIEWER_PROVIDERS:
        supported_list = ", ".join(sorted(SUPPORTED_REVIEWER_PROVIDERS))
        raise ReviewerToolError(
            f"리뷰어로 지원하지 않는 제공자입니다 (모델: {model!r}, 판정된 제공자: {provider!r}, "
            f"지원 제공자 목록: {supported_list})"
        )

    if provider in ("gemini", "claude", "cerebras"):
        return [
            "agy",
            "--model",
            model,
            "--print",
            prompt,
            "--print-timeout",
            f"{timeout}s",
        ]
    if provider == "qwen":
        return [
            "qwen",
            "-m",
            model,
            "-p",
            prompt,
        ]

    raise ReviewerToolError(f"처리되지 않은 제공자입니다 (모델: {model!r}, 제공자: {provider!r})")


build_cli_command = build_model_command


def run_model(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_MODEL_TIMEOUT,
) -> tuple[int, str, str]:
    """일회성 모델 호출을 subprocess 로 실행합니다.

    반환값: (returncode, stdout, stderr)
    """
    try:
        cmd = build_model_command(model=model, prompt=prompt, timeout=timeout)
    except Exception as exc:
        return -2, "", f"모델 명령 생성 실패: {exc}"

    cli_name = cmd[0] if cmd else "unknown"
    try:
        proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return -1, stdout, stderr
    except FileNotFoundError as exc:
        return -2, "", f"실행 파일을 찾을 수 없음 ({cli_name}): {exc}"
    except Exception as exc:
        return -2, "", f"모델 실행 예외: {exc}"


def extract_json_from_response(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    """모델 응답에서 첫 번째 완전한 JSON 객체를 추출합니다.

    json.JSONDecoder().raw_decode 를 사용하여 다중 객체, 앞뒤 설명 텍스트,
    마크다운 코드펜스 내의 첫 완전한 JSON 객체를 안전하게 파싱합니다.
    성공 시 (dict, ""), 실패 시 (None, 에러사유).
    """
    if not raw_text or not raw_text.strip():
        return None, "응답 텍스트가 비어 있음"

    if "{" not in raw_text:
        return None, "응답에서 JSON 객체 중괄호({...})를 찾을 수 없음"

    decoder = json.JSONDecoder()
    start_idx = 0
    last_err: Exception | None = None

    while True:
        pos = raw_text.find("{", start_idx)
        if pos == -1:
            break
        try:
            obj, _ = decoder.raw_decode(raw_text, pos)
            if isinstance(obj, dict):
                return obj, ""
        except json.JSONDecodeError as exc:
            last_err = exc
        start_idx = pos + 1

    return None, f"JSON 디코딩 실패: {last_err or '유효한 JSON 객체를 파싱할 수 없음'}"


def format_human_verdict(
    model: str,
    checklist_count: int,
    results_count: int,
    defect_ids: list[str],
    blocking_count: int,
    declared_verdict: str,
    effective_verdict: str,
    violations: list[str],
    diff_truncated: bool,
    out_path: Path,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """사람이 읽을 판정 블록 텍스트를 구성하고 max_chars 상한을 적용합니다."""
    diff_status = "절단됨 (상한 초과)" if diff_truncated else "정상 (전체 포함)"
    verdict_summary = (
        "통과 (pass)" if (not violations and effective_verdict == "pass") else "반려/위반 (fail)"
    )

    header_lines = [
        "=" * 60,
        "Orca Level 2 Reviewer 판정 결과",
        "=" * 60,
        f"사용 모델:          {model}",
        f"체크리스트 항목 수: {checklist_count}",
        f"보고된 항목 수:     {results_count}",
        f"결함 확인 항목:     {', '.join(defect_ids) if defect_ids else '없음'}",
        f"blocking_issues:    {blocking_count}건",
        f"선언 verdict:       {declared_verdict or '(없음)'}",
        f"실효 verdict:       {effective_verdict or '(없음)'}",
        f"Diff 절단 여부:     {diff_status}",
        f"리뷰 보고 경로:     {out_path}",
        "-" * 60,
    ]

    footer_lines = [
        "-" * 60,
        f"최종 판정: {verdict_summary}",
    ]

    fixed_text = "\n".join(header_lines) + "\n" + "\n".join(footer_lines)
    fixed_len = char_len(fixed_text)

    violation_lines: list[str] = []
    if not violations:
        violation_lines.append("계약 위반: 0건 (계약 만족)")
    else:
        v_header = f"계약 위반 ({len(violations)}건):"
        violation_lines.append(v_header)
        rem = max_chars - fixed_len - char_len(v_header) - 2
        for i, v in enumerate(violations):
            item_line = f"  * {v}"
            omitted = len(violations) - (i + 1)
            omission_line = f"  * ... 외 {omitted}건 생략" if omitted > 0 else ""
            needed = char_len(item_line) + 1 + (char_len(omission_line) + 1 if omission_line else 0)
            if rem >= needed:
                violation_lines.append(item_line)
                rem -= char_len(item_line) + 1
            else:
                actual_omitted = len(violations) - i
                if actual_omitted > 0:
                    violation_lines.append(f"  * ... 외 {actual_omitted}건 생략")
                break

    all_lines = header_lines + violation_lines + footer_lines
    full_text = "\n".join(all_lines)
    return truncate(full_text, max_chars)


def run_reviewer(
    capsule: str | Path,
    out: str | Path,
    diff_base: str = "main",
    diff_branch: str = "HEAD",
    repo: str | Path = ".",
    paths: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_MODEL_TIMEOUT,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
    dry_run: bool = False,
    as_json: bool = False,
    allow_truncated_diff: bool = False,
    model_runner: Callable[[str, str, int], tuple[int, str, str]] = run_model,
) -> tuple[int, str]:
    """리뷰어 전체 파이프라인을 실행하고 (exit_code, output_text) 를 반환합니다.

    diff 가 상한을 넘어 절단되면 리뷰어가 변경의 일부를 보지 못한 것이므로
    기본적으로 통과시키지 않습니다. 절단된 채로 판정을 받아들이려면
    allow_truncated_diff 를 켜야 합니다.
    """
    repo_path = Path(repo).resolve()
    capsule_path = Path(capsule).resolve()
    out_path = Path(out).resolve()

    # 1. Capsule 읽기 및 checklist 검증
    if not capsule_path.exists():
        err_msg = f"Capsule 파일 없음: {capsule_path}"
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    try:
        capsule_text = load_capsule(capsule_path)
    except Exception as exc:
        err_msg = f"Capsule 읽기 실패: {exc}"
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    checklist = parse_checklist(capsule_text)
    if not checklist:
        err_msg = (
            f"Capsule({capsule_path})에서 review_checklist 를 찾을 수 없거나 항목이 0개입니다. "
            "체크리스트 없는 리뷰는 계약 조건을 판정할 수 없습니다."
        )
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    capsule_context = _extract_capsule_context(capsule_text)

    # 2. git diff 및 변경 파일 조회
    try:
        changed_files, diff_raw = get_git_diff_and_files(
            repo=repo_path,
            base=diff_base,
            branch=diff_branch,
            paths=paths,
            timeout=DEFAULT_GIT_TIMEOUT,
        )
    except ReviewerToolError as exc:
        err_msg = str(exc)
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    # 경로 필터로 좁힌 결과가 빈 diff 인 경우 종료 코드 2 로 거부 (규약 72)
    if paths and not diff_raw.strip():
        err_msg = f"--paths({', '.join(paths)})로 지정된 경로에 변경 사항(diff)이 없습니다."
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    # 3. diff 본문 상한 검사 및 절단
    diff_truncated = False
    if char_len(diff_raw) > max_diff_chars:
        diff_truncated = True
        diff_text = truncate(diff_raw, max_diff_chars)
    else:
        diff_text = diff_raw

    # 4. 프롬프트 조립
    prompt = build_prompt(
        checklist=checklist,
        changed_files=changed_files,
        diff_text=diff_text,
        diff_truncated=diff_truncated,
        max_diff_chars=max_diff_chars,
        capsule_context=capsule_context,
    )

    # 5. dry-run 처리
    if dry_run:
        if as_json:
            dry_data = {
                "dry_run": True,
                "prompt": prompt,
                "char_count": char_len(prompt),
                "model": model,
                "checklist_count": len(checklist),
                "changed_files_count": len(changed_files),
                "diff_truncated": diff_truncated,
            }
            return 0, json.dumps(dry_data, ensure_ascii=False, indent=2)
        human_dry = (
            f"=== [Dry-run] 조립된 리뷰어 프롬프트 ===\n"
            f"{prompt}\n"
            f"========================================\n"
            f"[Dry-run 완료] 프롬프트 문자 수: {char_len(prompt)}자 (모델 호출 생략)"
        )
        return 0, human_dry

    # 6. 모델 일회성 호출
    returncode, stdout, stderr = model_runner(prompt, model, timeout)
    if returncode == -1:
        err_msg = f"모델 호출 타임아웃 ({timeout}초 초과)"
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"
    if returncode != 0:
        err_msg = f"모델 호출 실패 (종료 코드 {returncode}): {stderr.strip()}"
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    # 7. JSON 추출 및 파싱 실패 시 1회 재시도
    report_data, extract_err = extract_json_from_response(stdout)
    if report_data is None:
        # 파싱 실패 시 동일 프롬프트로 정확히 1회 재시도
        retry_code, retry_stdout, retry_stderr = model_runner(prompt, model, timeout)
        if retry_code == 0:
            stdout = retry_stdout
            report_data, extract_err = extract_json_from_response(stdout)
        else:
            stdout = retry_stdout if retry_stdout else stdout
            if retry_code == -1:
                extract_err = f"재시도 모델 호출 타임아웃 ({timeout}초 초과)"
            else:
                extract_err = (
                    f"재시도 모델 호출 실패 (종료 코드 {retry_code}): {retry_stderr.strip()}"
                )

    if report_data is None:
        raw_path = Path(str(out_path) + ".raw")
        try:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(stdout, encoding="utf-8")
        except Exception as write_raw_exc:
            sys.stderr.write(f"경고: raw 파일 쓰기 실패 ({raw_path}): {write_raw_exc}\n")

        reports_dir = repo_path / ".orca" / "reports"
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            ts_raw_path = reports_dir / f"{out_path.stem}_{ts}.raw"
            ts_raw_path.write_text(stdout, encoding="utf-8")
        except Exception as write_reports_exc:
            sys.stderr.write(f"경고: reports raw 파일 쓰기 실패: {write_reports_exc}\n")

        err_msg = f"모델 응답 JSON 파싱 실패 ({extract_err}). 원문을 {raw_path} 에 저장했습니다."
        if as_json:
            return 2, json.dumps(
                {"error": err_msg, "raw_path": str(raw_path), "exit_code": 2},
                ensure_ascii=False,
                indent=2,
            )
        return 2, f"오류: {err_msg}"

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        err_msg = f"리뷰 보고서 파일 쓰기 실패 ({out_path}): {exc}"
        if as_json:
            return 2, json.dumps({"error": err_msg, "exit_code": 2}, ensure_ascii=False, indent=2)
        return 2, f"오류: {err_msg}"

    # 8. validate_review_report 로 계약 평가
    eval_res = evaluate(checklist, report_data)
    violations = eval_res.get("violations", [])
    declared_verdict = eval_res.get("declared_verdict", "")
    effective_verdict = eval_res.get("effective_verdict", "")
    defect_ids = eval_res.get("defect_ids", [])
    blocking_count = eval_res.get("blocking_count", 0)
    checklist_count = eval_res.get("checklist_count", len(checklist))
    results_count = eval_res.get("results_count", 0)
    ok = eval_res.get("ok", False)

    # 9. 종료 코드 결정: 계약 만족(ok)이고 실효 verdict 가 "pass" 면 0, 아니면 1.
    # 절단된 diff 로 내린 pass 는 못 본 부분에 대한 판정이 아니므로 통과로
    # 취급하지 않습니다. 큰 변경을 그대로 판정하려면 --allow-truncated-diff
    # 로 명시해야 합니다.
    truncation_blocks = diff_truncated and not allow_truncated_diff
    exit_code = 0 if (ok and effective_verdict == "pass" and not truncation_blocks) else 1
    if truncation_blocks:
        violations = [
            *violations,
            f"diff 가 상한({max_diff_chars}자)을 넘어 절단되어 리뷰 범위가 불완전합니다.",
        ]

    # 10. 결과 출력 포맷팅
    if as_json:
        result_json = {
            "model": model,
            "checklist_count": checklist_count,
            "results_count": results_count,
            "defect_ids": defect_ids,
            "blocking_count": blocking_count,
            "declared_verdict": declared_verdict,
            "effective_verdict": effective_verdict,
            "violations": violations,
            "ok": ok,
            "diff_truncated": diff_truncated,
            "out_path": str(out_path),
            "exit_code": exit_code,
        }
        return exit_code, json.dumps(result_json, ensure_ascii=False, indent=2)

    human_output = format_human_verdict(
        model=model,
        checklist_count=checklist_count,
        results_count=results_count,
        defect_ids=defect_ids,
        blocking_count=blocking_count,
        declared_verdict=declared_verdict,
        effective_verdict=effective_verdict,
        violations=violations,
        diff_truncated=diff_truncated,
        out_path=out_path,
        max_chars=max_chars,
    )
    return exit_code, human_output


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="Orca Level 2 Reviewer 독립 실행 도구",
    )
    parser.add_argument(
        "--capsule", required=True, help="review_checklist 를 담은 리뷰어 Capsule YAML 경로"
    )
    parser.add_argument("--diff-base", default="main", help="비교 기준 git ref (기본: main)")
    parser.add_argument("--diff-branch", default="HEAD", help="검증 대상 git ref (기본: HEAD)")
    parser.add_argument("--repo", default=".", help="저장소 루트 경로 (기본: 현재 디렉터리)")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="검토 대상 경로 필터 목록 (공백으로 여러 경로 지정 가능)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"사용할 모델 ID (기본: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_MODEL_TIMEOUT,
        help=f"모델 호출 타임아웃 초 (기본: {DEFAULT_MODEL_TIMEOUT})",
    )
    parser.add_argument("--out", required=True, help="리뷰 보고 JSON 을 저장할 경로")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"사람 출력 최대 문자 수 상한 (기본: {DEFAULT_MAX_CHARS})",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=DEFAULT_MAX_DIFF_CHARS,
        help=(
            f"diff 본문 최대 허용 문자 수 (기본: {DEFAULT_MAX_DIFF_CHARS}, "
            f"실측 최대 38,401 자를 약 30 % 여유로 넘긴 값)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    parser.add_argument(
        "--allow-truncated-diff",
        action="store_true",
        help="diff 가 절단되어도 리뷰어 판정을 그대로 받아들임",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="모델을 호출하지 않고 조립된 프롬프트와 문자 수만 출력",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    args = _parse_args(argv)
    code, output = run_reviewer(
        capsule=args.capsule,
        out=args.out,
        diff_base=args.diff_base,
        diff_branch=args.diff_branch,
        repo=args.repo,
        paths=args.paths,
        model=args.model,
        timeout=args.timeout,
        max_chars=args.max_chars,
        max_diff_chars=args.max_diff_chars,
        allow_truncated_diff=args.allow_truncated_diff,
        dry_run=args.dry_run,
        as_json=args.json,
    )
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
