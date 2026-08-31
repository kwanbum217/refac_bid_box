"""
tests/test_render_analysis_metrics.py

render_analysis_metrics.py 의 자동화 검사 (6건).

픽스처 파일:
  tests/fixtures/analysis_metrics/sample_benchmark.json  - 원시 JSON
  tests/fixtures/analysis_metrics/sample_doc.md          - 마커가 든 문서

테스트는 data/benchmarks 실제 파일에 의존하지 않는다.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# 헬퍼: 스크립트 경로
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render_analysis_metrics.py"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "analysis_metrics"
FIXTURE_JSON = FIXTURE_DIR / "sample_benchmark.json"
FIXTURE_DOC = FIXTURE_DIR / "sample_doc.md"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - 테스트 스크립트, 고정 인자 목록으로만 호출합니다
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# 테스트 1: 픽스처 JSON 에서 표가 기대대로 생성된다
# ---------------------------------------------------------------------------


def test_generate_table_from_fixture() -> None:
    """(1) 픽스처 JSON 에서 표가 기대대로 생성된다."""
    result = run_script(
        "generate",
        "--json",
        str(FIXTURE_JSON),
        "--keys",
        "summary_cold.total_ms.p99_ms,summary_cold.sql_ms.max_ms",
    )
    assert result.returncode == 0, f"generate 실패: {result.stderr}"
    stdout = result.stdout
    assert "METRICS_BEGIN" in stdout
    assert "METRICS_END" in stdout
    assert "summary_cold.total_ms.p99_ms" in stdout
    assert "summary_cold.sql_ms.max_ms" in stdout
    # 값 확인
    assert "69195.04" in stdout
    assert "97087.81" in stdout


# ---------------------------------------------------------------------------
# 테스트 2: 문서 수치를 한 글자 바꾸면 verify 가 종료 코드 1 로 실패하고 차이 값 출력
# ---------------------------------------------------------------------------


def test_verify_detects_modified_value(tmp_path: Path) -> None:
    """(2) 문서의 수치를 한 글자 바꾸면 verify 가 종료 코드 1 로 실패하고 차이 값이 출력된다."""
    # 문서에서 69195.04 -> 69195.05 로 한 글자 변조
    original_doc = FIXTURE_DOC.read_text(encoding="utf-8")

    tampered_doc = original_doc.replace("69195.04", "69195.05", 1)
    assert "69195.05" in tampered_doc, "변조 실패"

    tampered_path = tmp_path / "tampered.md"
    tampered_path.write_text(tampered_doc, encoding="utf-8")

    # 변조 문서의 JSON 경로가 FIXTURE_JSON 을 절대 경로로 가리키도록 재작성
    # (픽스처 문서는 상대 경로를 쓰는데, tmp_path 에서 실행하면 경로가 틀릴 수 있음)
    fixed_doc = tampered_doc.replace(
        "json=tests/fixtures/analysis_metrics/sample_benchmark.json",
        f"json={FIXTURE_JSON}",
    )
    tampered_path.write_text(fixed_doc, encoding="utf-8")

    result = run_script("verify", "--doc", str(tampered_path))
    assert result.returncode == 1, (
        f"수치 불일치를 감지하지 못했거나 잘못된 종료 코드 {result.returncode}:\n{result.stdout}"
    )
    # 차이 값이 출력에 나와야 함
    assert "69195" in result.stdout or "불일치" in result.stdout, (
        f"차이 값이 출력에 없음:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 테스트 3: 원시 JSON 이 사라지면 종료 코드 2 로 실패
# ---------------------------------------------------------------------------


def test_verify_missing_json_exits_2(tmp_path: Path) -> None:
    """(3) 원시 JSON 이 사라지면 verify 가 종료 코드 2 로 실패한다."""
    missing_json = tmp_path / "nonexistent.json"
    fake_hash = "a" * 64

    doc_content = textwrap.dedent(f"""\
        # 테스트 문서

        <!-- METRICS_BEGIN json={missing_json} hash={fake_hash} -->
        | 지표 | 값 |
        | --- | ---: |
        | `summary_cold.total_ms.p99_ms` | 100 |
        <!-- METRICS_END -->
    """)
    doc_path = tmp_path / "test.md"
    doc_path.write_text(doc_content, encoding="utf-8")

    result = run_script("verify", "--doc", str(doc_path))
    assert result.returncode == 2, (
        f"JSON 부재를 코드 2 로 처리하지 않음 (실제: {result.returncode}):\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 테스트 4: 지정한 키 경로가 없으면 종료 코드 2 로 실패
# ---------------------------------------------------------------------------


def test_generate_missing_key_exits_2(tmp_path: Path) -> None:
    """(4) 지정한 키 경로가 없으면 generate 가 종료 코드 2 로 실패한다."""
    result = run_script(
        "generate",
        "--json",
        str(FIXTURE_JSON),
        "--keys",
        "nonexistent.key.path",
    )
    assert result.returncode == 2, (
        f"키 부재를 코드 2 로 처리하지 않음 (실제: {result.returncode}):\n{result.stderr}"
    )


def test_verify_missing_key_in_json_exits_2(tmp_path: Path) -> None:
    """(4b) verify 중 JSON 에 키가 없으면 종료 코드 2 로 실패한다."""
    json_hash = hashlib.sha256(FIXTURE_JSON.read_bytes()).hexdigest()

    doc_content = textwrap.dedent(f"""\
        # 테스트 문서

        <!-- METRICS_BEGIN json={FIXTURE_JSON} hash={json_hash} -->
        | 지표 | 값 |
        | --- | ---: |
        | `nonexistent.key.path` | 999 |
        <!-- METRICS_END -->
    """)
    doc_path = tmp_path / "test.md"
    doc_path.write_text(doc_content, encoding="utf-8")

    result = run_script("verify", "--doc", str(doc_path))
    assert result.returncode == 2, (
        f"키 부재를 코드 2 로 처리하지 않음 (실제: {result.returncode}):\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 테스트 5: 마커가 없는 문서는 통과한다
# ---------------------------------------------------------------------------


def test_verify_no_marker_passes(tmp_path: Path) -> None:
    """(5) 마커가 없는 문서는 verify 가 통과한다 (종료 코드 0)."""
    doc_content = textwrap.dedent("""\
        # 마커 없는 문서

        이 문서에는 METRICS_BEGIN 마커가 없다.

        | 지표 | 값 |
        | --- | ---: |
        | 수동 기재 | 999 |
    """)
    doc_path = tmp_path / "no_marker.md"
    doc_path.write_text(doc_content, encoding="utf-8")

    result = run_script("verify", "--doc", str(doc_path))
    assert result.returncode == 0, (
        f"마커 없는 문서가 실패 처리됨 (코드 {result.returncode}):\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 테스트 6: 원시 JSON 의 값이 바뀌면 해시 불일치가 보고된다
# ---------------------------------------------------------------------------


def test_verify_detects_hash_mismatch(tmp_path: Path) -> None:
    """(6) 원시 JSON 의 값이 바뀌면 해시 불일치가 보고된다."""
    # 수정된 JSON 파일 생성
    import json

    original_data = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    modified_data = dict(original_data)
    modified_data["_extra_field"] = "modified"
    modified_json = tmp_path / "modified.json"
    modified_json.write_text(json.dumps(modified_data, indent=2), encoding="utf-8")

    # 원래 JSON 해시를 마커에 기록 (수정 전 해시)
    old_hash = hashlib.sha256(FIXTURE_JSON.read_bytes()).hexdigest()

    doc_content = textwrap.dedent(f"""\
        # 테스트 문서

        <!-- METRICS_BEGIN json={modified_json} hash={old_hash} -->
        | 지표 | 값 |
        | --- | ---: |
        | `summary_cold.total_ms.p99_ms` | 69195.04 |
        <!-- METRICS_END -->
    """)
    doc_path = tmp_path / "hash_test.md"
    doc_path.write_text(doc_content, encoding="utf-8")

    result = run_script("verify", "--doc", str(doc_path))
    # 해시 불일치 -> 종료 코드 1 (수치는 일치하더라도 해시 변경은 보고해야 함)
    assert result.returncode == 1, (
        f"해시 불일치를 감지하지 못했거나 잘못된 종료 코드 {result.returncode}:\n{result.stdout}"
    )
    assert "해시 불일치" in result.stdout or "hash" in result.stdout.lower(), (
        f"해시 불일치 메시지가 출력에 없음:\n{result.stdout}"
    )
