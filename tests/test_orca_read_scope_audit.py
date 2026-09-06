from __future__ import annotations

import json
from pathlib import Path

from scripts.orca_read_scope_audit import (
    SYSTEM_ALLOWLIST_CONTAINS,
    SYSTEM_ALLOWLIST_PREFIXES,
    audit_read_scope,
    extract_paths_from_text,
    is_system_path,
    main,
    parse_search_scope_allowed_globs,
    read_terminal_scrollback,
)


def _create_sample_capsule(
    tmp_path: Path,
    allowed_read: list[str] | None = None,
    allowed_globs: list[str] | None = None,
    task_id: str = "task_test123",
) -> Path:
    """테스트용 가상 Capsule 파일을 생성합니다."""
    cap_path = tmp_path / "test_capsule.yaml"
    read_lines = "\n".join(f'  - "{p}"' for p in (allowed_read or ["src/..."]))
    glob_lines = "\n".join(f'    - "{p}"' for p in (allowed_globs or []))
    content = (
        f"schema: ORCA_TASK_CAPSULE_V2\n"
        f'version: "2.1.0"\n'
        f'task_id: "{task_id}"\n'
        f"allowed_read_files:\n{read_lines}\n"
        f"search_scope:\n  mode: deny_by_default\n  allowed_globs:\n{glob_lines}\n"
    )
    cap_path.write_text(content, encoding="utf-8")
    return cap_path


def test_outside_worktree_detected(tmp_path: Path):
    """1. 워크트리 밖 절대 경로를 outside_worktree 로 잡아야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    outside_path = "/Users/kwanbum/secret_outside/data.txt"
    text = f"reading external file {outside_path} and done\n"

    code, result = audit_read_scope(
        text=text,
        capsule_path=cap,
        repo=repo,
    )

    assert code == 1
    assert result["verdict"] == "violations"
    assert outside_path in result["outside_worktree"]
    assert result["scope_excess"] == []


def test_scope_excess_detected(tmp_path: Path):
    """2. 워크트리 안이지만 허용 범위 밖 경로를 scope_excess 로 잡아야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(
        repo,
        allowed_read=["src/app.py"],
        allowed_globs=["scripts/orca_contract.py"],
    )

    unauthorized_file = "scripts/unauthorized_tool.py"
    text = f"executing {unauthorized_file} within worktree\n"

    code, result = audit_read_scope(
        text=text,
        capsule_path=cap,
        repo=repo,
    )

    assert code == 1
    assert result["verdict"] == "violations"
    assert unauthorized_file in result["scope_excess"]
    assert result["outside_worktree"] == []


def test_in_scope_allowed(tmp_path: Path):
    """3. 허용 범위 안(allowed_read_files 및 search_scope.allowed_globs) 경로는 잡지 않아야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(
        repo,
        allowed_read=["src/..."],
        allowed_globs=["scripts/orca_contract.py", "docs/analysis/*.md"],
    )

    text = (
        "Opening src/app.py\n"
        "Opening src/ml/features.py\n"
        "Reading scripts/orca_contract.py\n"
        "Inspecting docs/analysis/task_test.md\n"
    )

    code, result = audit_read_scope(
        text=text,
        capsule_path=cap,
        repo=repo,
    )

    assert code == 0
    assert result["verdict"] == "clean"
    assert result["outside_worktree"] == []
    assert result["scope_excess"] == []


def test_system_allowlist_default_and_override(tmp_path: Path):
    """4. 시스템 경로가 기본 제외되고 --no-system-allowlist 로 다시 잡혀야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    # 시스템 경로 1: 워크트리 밖 시스템 절대 경로 (/usr/bin/python)
    # 시스템 경로 2: 워크트리 안 의존성 경로 (.venv/lib/module.py)
    text = (
        "Running /usr/bin/python from virtualenv .venv/lib/site-packages/pkg.py\nRead src/app.py\n"
    )

    # 기본 상태 (시스템 경로 잡음 억제 활성화)
    code_default, result_default = audit_read_scope(
        text=text,
        capsule_path=cap,
        repo=repo,
        no_system_allowlist=False,
    )
    assert code_default == 0
    assert result_default["verdict"] == "clean"
    assert result_default["outside_worktree"] == []
    assert result_default["scope_excess"] == []

    # --no-system-allowlist 활성화 시: 모두 잡혀야 함
    code_strict, result_strict = audit_read_scope(
        text=text,
        capsule_path=cap,
        repo=repo,
        no_system_allowlist=True,
    )
    assert code_strict == 1
    assert result_strict["verdict"] == "violations"
    assert "/usr/bin/python" in result_strict["outside_worktree"]
    assert any(".venv" in p for p in result_strict["scope_excess"])


def test_url_not_treated_as_path():
    """5. http, https, file 스킴 URL 은 경로로 오인하지 않아야 합니다."""
    text = (
        "Visit https://github.com/org/repo/blob/main/src/app.py for details\n"
        "API running at http://localhost:8000/api/v1/health\n"
        "Preview link: file:///Users/kwanbum/secret.txt\n"
        "Real path: src/legit_module.py\n"
    )

    paths = extract_paths_from_text(text)
    assert "https://github.com/org/repo/blob/main/src/app.py" not in paths
    assert "http://localhost:8000/api/v1/health" not in paths
    assert "file:///Users/kwanbum/secret.txt" not in paths
    assert "/Users/kwanbum/secret.txt" not in paths
    assert "src/legit_module.py" in paths


def test_ansi_stripped_paths_extracted():
    """6. ANSI 색상 이스케이프가 섞인 텍스트에서도 정상적으로 경로를 뽑아야 합니다."""
    text = (
        "\x1b[32mtests/test_feature.py\x1b[0m:42: PASSED\n"
        "\x1b[31;1m/Users/kwanbum/another_worktree/leak.py\x1b[0m\n"
        "[\x1b[34mscripts/orca_scope_guard.py\x1b[0m]\n"
    )

    paths = extract_paths_from_text(text)
    assert "tests/test_feature.py" in paths
    assert "/Users/kwanbum/another_worktree/leak.py" in paths
    assert "scripts/orca_scope_guard.py" in paths


def test_unreadable_buffer_fails_closed_exit_2(tmp_path: Path):
    """7. 버퍼(텍스트 파일 등)를 읽지 못하면 fail-closed 로 종료 코드 2 여야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo)

    non_existent_text = tmp_path / "does_not_exist.txt"
    code = main(
        [
            "--text-file",
            str(non_existent_text),
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
        ]
    )
    assert code == 2


def test_missing_capsule_fails_closed_exit_2(tmp_path: Path):
    """Capsule 파일이 없거나 읽지 못하면 fail-closed 로 종료 코드 2 여야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    buf_file = tmp_path / "buffer.txt"
    buf_file.write_text("src/app.py\n", encoding="utf-8")

    non_existent_cap = tmp_path / "no_capsule.yaml"
    code = main(
        [
            "--text-file",
            str(buf_file),
            "--capsule",
            str(non_existent_cap),
            "--repo",
            str(repo),
        ]
    )
    assert code == 2


def test_verdict_exit_codes(tmp_path: Path):
    """8. 위반이 있으면 1, 없으면 0 으로 종료 코드가 구분되어야 합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    # 위반 없는 경우 -> 0
    clean_buf = tmp_path / "clean_buf.txt"
    clean_buf.write_text("pytest src/ml/features.py\n", encoding="utf-8")
    clean_out = tmp_path / "clean_out.json"

    code_clean = main(
        [
            "--text-file",
            str(clean_buf),
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
            "--out",
            str(clean_out),
        ]
    )
    assert code_clean == 0
    assert clean_out.exists()
    clean_data = json.loads(clean_out.read_text(encoding="utf-8"))
    assert clean_data["verdict"] == "clean"

    # 위반 있는 경우 -> 1
    bad_buf = tmp_path / "bad_buf.txt"
    bad_buf.write_text("cat /Users/other/secret.txt\n", encoding="utf-8")
    bad_out = tmp_path / "bad_out.json"

    code_bad = main(
        [
            "--text-file",
            str(bad_buf),
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
            "--out",
            str(bad_out),
        ]
    )
    assert code_bad == 1
    assert bad_out.exists()
    bad_data = json.loads(bad_out.read_text(encoding="utf-8"))
    assert bad_data["verdict"] == "violations"
    assert "/Users/other/secret.txt" in bad_data["outside_worktree"]


def test_system_allowlist_constants():
    """모듈 상수로 정의된 시스템 경로 목록을 확인합니다."""
    assert "/usr" in SYSTEM_ALLOWLIST_PREFIXES
    assert "/bin" in SYSTEM_ALLOWLIST_PREFIXES
    assert ".venv" in SYSTEM_ALLOWLIST_CONTAINS
    assert "node_modules" in SYSTEM_ALLOWLIST_CONTAINS

    assert is_system_path("/usr/local/bin/node") is True
    assert is_system_path("frontend/node_modules/react/index.js") is True
    assert is_system_path("src/ml/features.py") is False


def test_parse_search_scope_allowed_globs():
    """Capsule 의 search_scope.allowed_globs 파싱을 검증합니다."""
    yaml_text = (
        "search_scope:\n"
        "  mode: deny_by_default\n"
        "  allowed_globs:\n"
        '    - "scripts/orca_contract.py"\n'
        '    - "tests/test_*.py"\n'
    )
    globs = parse_search_scope_allowed_globs(yaml_text)
    assert globs == ["scripts/orca_contract.py", "tests/test_*.py"]

    # 빈 리스트
    empty_yaml = "search_scope:\n  allowed_globs: []\n"
    assert parse_search_scope_allowed_globs(empty_yaml) == []


def test_pagination_concatenates_all_pages(monkeypatch):
    """여러 페이지를 이어 붙여 전부 읽고 순서대로 결합하는지 검증합니다."""

    def mock_run(cmd, capture_output=True, text=True, timeout=30, check=False):
        cursor_idx = cmd.index("--cursor")
        cursor_val = int(cmd[cursor_idx + 1])
        if cursor_val == 0:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 0,
                        "nextCursor": 2,
                        "latestCursor": 5,
                        "returnedLineCount": 2,
                        "tail": ["line 0", "line 1"],
                    }
                },
            }
        elif cursor_val == 2:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 0,
                        "nextCursor": 4,
                        "latestCursor": 5,
                        "returnedLineCount": 2,
                        "tail": ["line 2", "line 3"],
                    }
                },
            }
        elif cursor_val == 4:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 0,
                        "nextCursor": 5,
                        "latestCursor": 5,
                        "returnedLineCount": 1,
                        "tail": ["line 4"],
                    }
                },
            }
        else:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 0,
                        "nextCursor": 5,
                        "latestCursor": 5,
                        "returnedLineCount": 0,
                        "tail": [],
                    }
                },
            }

        class MockCompletedProcess:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return MockCompletedProcess()

    monkeypatch.setattr("scripts.orca_read_scope_audit.subprocess.run", mock_run)

    res = read_terminal_scrollback("term_mock")
    assert res is not None
    text, evidence = res
    assert text == "line 0\nline 1\nline 2\nline 3\nline 4"
    assert evidence["lines_read"] == 5
    assert evidence["oldest_cursor"] == 0
    assert evidence["latest_cursor"] == 5
    assert evidence["complete"] is True


def test_pagination_stops_when_cursor_does_not_advance(monkeypatch):
    """nextCursor 가 전진하지 않으면 즉시 멈추는지 검증합니다."""
    calls = []

    def mock_run(cmd, capture_output=True, text=True, timeout=30, check=False):
        calls.append(cmd)
        payload = {
            "ok": True,
            "result": {
                "terminal": {
                    "oldestCursor": 0,
                    "nextCursor": 0,
                    "latestCursor": 10,
                    "returnedLineCount": 2,
                    "tail": ["item 1", "item 2"],
                }
            },
        }

        class MockCompletedProcess:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return MockCompletedProcess()

    monkeypatch.setattr("scripts.orca_read_scope_audit.subprocess.run", mock_run)

    res = read_terminal_scrollback("term_mock")
    assert res is not None
    _text, evidence = res
    assert len(calls) == 1
    assert evidence["lines_read"] == 2
    assert evidence["complete"] is True


def test_pagination_respects_max_pages_ceiling(monkeypatch):
    """반복 상한(max_pages)을 넘지 않고 종료하는지 검증합니다."""
    calls = []

    def mock_run(cmd, capture_output=True, text=True, timeout=30, check=False):
        calls.append(cmd)
        cursor_idx = cmd.index("--cursor")
        cursor_val = int(cmd[cursor_idx + 1])
        payload = {
            "ok": True,
            "result": {
                "terminal": {
                    "oldestCursor": 0,
                    "nextCursor": cursor_val + 1,
                    "latestCursor": 99999,
                    "returnedLineCount": 1,
                    "tail": [f"line {cursor_val}"],
                }
            },
        }

        class MockCompletedProcess:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return MockCompletedProcess()

    monkeypatch.setattr("scripts.orca_read_scope_audit.subprocess.run", mock_run)

    res = read_terminal_scrollback("term_mock", max_pages=5)
    assert res is not None
    assert len(calls) == 5
    _text, evidence = res
    assert evidence["lines_read"] == 5


def test_dropped_lines_sets_complete_false(tmp_path: Path, monkeypatch, capsys):
    """oldestCursor 가 0 보다 크면 evidence.complete 가 False 로 기록되고 출력에 명시되는지 검증합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    def mock_run(cmd, capture_output=True, text=True, timeout=30, check=False):
        cursor_idx = cmd.index("--cursor")
        cursor_val = int(cmd[cursor_idx + 1])
        if cursor_val == 0:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 150,
                        "nextCursor": 160,
                        "latestCursor": 200,
                        "returnedLineCount": 1,
                        "tail": ["src/app.py"],
                    }
                },
            }
        else:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 150,
                        "nextCursor": 160,
                        "latestCursor": 200,
                        "returnedLineCount": 0,
                        "tail": [],
                    }
                },
            }

        class MockCompletedProcess:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return MockCompletedProcess()

    monkeypatch.setattr("scripts.orca_read_scope_audit.subprocess.run", mock_run)

    out_file = tmp_path / "dropped_out.json"
    code = main(
        [
            "--terminal",
            "term_dropped",
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
            "--out",
            str(out_file),
        ]
    )

    assert code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["verdict"] == "clean"
    assert data["evidence"]["complete"] is False
    assert data["evidence"]["oldest_cursor"] == 150
    assert data["evidence"]["lines_read"] == 1

    captured = capsys.readouterr()
    assert "[증거] 불완전" in captured.out
    assert "oldest_cursor=150" in captured.out


def test_mid_pagination_failure_fails_closed_exit_2(tmp_path: Path, monkeypatch, capsys):
    """중간 페이지 읽기 실패 시 부분 결과로 통과시키지 않고 종료 코드 2 로 실패하는지 검증합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    def mock_run(cmd, capture_output=True, text=True, timeout=30, check=False):
        cursor_idx = cmd.index("--cursor")
        cursor_val = int(cmd[cursor_idx + 1])
        if cursor_val == 0:
            payload = {
                "ok": True,
                "result": {
                    "terminal": {
                        "oldestCursor": 0,
                        "nextCursor": 10,
                        "latestCursor": 20,
                        "returnedLineCount": 1,
                        "tail": ["src/app.py"],
                    }
                },
            }

            class MockSuccess:
                returncode = 0
                stdout = json.dumps(payload)
                stderr = ""

            return MockSuccess()
        else:

            class MockFailure:
                returncode = 1
                stdout = "Internal error"
                stderr = "Terminal connection dropped"

            return MockFailure()

    monkeypatch.setattr("scripts.orca_read_scope_audit.subprocess.run", mock_run)

    out_file = tmp_path / "failure_out.json"
    code = main(
        [
            "--terminal",
            "term_fail",
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
            "--out",
            str(out_file),
        ]
    )

    assert code == 2
    assert not out_file.exists()
    captured = capsys.readouterr()
    assert "오류: 터미널 버퍼를 읽지 못했습니다" in captured.err


def test_text_file_path_complete_true(tmp_path: Path, capsys):
    """--text-file 경로는 페이지네이션 없이 그대로 동작하고 evidence.complete 가 참인지 검증합니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cap = _create_sample_capsule(repo, allowed_read=["src/..."])

    buf_file = tmp_path / "text_buffer.txt"
    buf_file.write_text("src/app.py\nsrc/ml/features.py\n", encoding="utf-8")
    out_file = tmp_path / "text_file_out.json"

    code = main(
        [
            "--text-file",
            str(buf_file),
            "--capsule",
            str(cap),
            "--repo",
            str(repo),
            "--out",
            str(out_file),
        ]
    )

    assert code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["verdict"] == "clean"
    assert data["evidence"]["complete"] is True
    assert data["evidence"]["oldest_cursor"] == 0
    assert data["evidence"]["lines_read"] == 2

    captured = capsys.readouterr()
    assert "[증거] 완전" in captured.out
