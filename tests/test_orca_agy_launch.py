"""Antigravity 런처의 대기/기동 계약을 검증합니다."""

from __future__ import annotations

import functools
import io
import threading
from pathlib import Path

import pytest

from scripts import orca_worker_launch_common as common
from scripts.orca_agy_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    acquire_permissions,
    build_command,
    main,
    spawn_permission_setup,
    wait_for_preamble,
)


@pytest.fixture(autouse=True)
def _guard_agy_permission_setup(monkeypatch):
    """Antigravity 런처 테스트가 실제 분리 프로세스를 띄우지 않도록 안전망을 제공합니다."""
    import subprocess

    from scripts import orca_agy_launch as mod

    orig_spawn = mod.spawn_permission_setup
    _SENTINEL = object()

    def safe_spawn(terminal: str, model: str, *, popen=_SENTINEL) -> None:
        if popen is _SENTINEL or popen is subprocess.Popen:
            return None
        return orig_spawn(terminal, model, popen=popen)

    monkeypatch.setattr(mod, "spawn_permission_setup", safe_spawn)


def test_wait_returns_content_once_written(tmp_path: Path):
    # 고유명 preamble_*.txt 로 대기한다. 고정명 preamble.txt 로 대기하면
    # 폴링 루프 경계에서 옛 형태 격리 파손 거부와 경합해 드물게
    # ValueError 로 실패한다. 고유명은 소비 경로가 하나로 확정된다.
    target = tmp_path / "preamble_u1wait.txt"
    waiter_ready = threading.Event()
    outcome: dict = {}

    def waiter():
        waiter_ready.set()
        outcome["text"] = wait_for_preamble(target, timeout_sec=20.0, poll_sec=0.05)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()

    # 대기자가 폴링에 들어갔음을 확인한 뒤에야 내용을 쓴다.
    # 고정 sleep 추측이 아니다.
    assert waiter_ready.wait(timeout=20.0)
    target.write_text("지시문 본문", encoding="utf-8")

    t.join(timeout=20.0)
    assert not t.is_alive()
    assert outcome["text"] == "지시문 본문"
    assert not target.exists()


def test_agy_main_consumes_and_deletes_unique_preamble(tmp_path: Path, monkeypatch):
    """Antigravity main 실행 시 고유 preamble_*.txt 파일을 읽고 소비 후 삭제해야 합니다."""
    from scripts import orca_agy_launch as mod

    target = tmp_path / "preamble_run_unique_agy.txt"
    target.write_text("에이지와이 고유 지시문", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--no-commit-notice",
            ]
        )
    assert exc.value.code == 0
    assert not target.exists(), "런처 기동 후 preamble 파일이 삭제되어야 합니다"
    prompt = captured["cmd"][-1]
    assert prompt == "에이지와이 고유 지시문"


def test_empty_file_is_not_accepted(tmp_path: Path):
    """비어 있는 파일을 지시문으로 읽으면 워커가 빈 지시로 기동합니다."""
    target = tmp_path / "preamble.txt"
    target.write_text("   \n", encoding="utf-8")

    with pytest.raises(TimeoutError):
        wait_for_preamble(target, timeout_sec=0.3, poll_sec=0.05)


def test_missing_file_times_out(tmp_path: Path):
    with pytest.raises(TimeoutError):
        wait_for_preamble(tmp_path / "absent.txt", timeout_sec=0.3, poll_sec=0.05)


def test_build_command_passes_prompt_as_agy_argument():
    """-i 인자 경로여야 합니다. 스플래시 멈춤을 피하려면 지시문을 인자로 줘야 합니다."""
    cmd = build_command("gemini-3.8-flash-medium", "본문")
    assert cmd == [
        "agy",
        "--model",
        "gemini-3.8-flash-medium",
        "--mode",
        "accept-edits",
        "-i",
        "본문",
    ]


def test_build_command_supports_different_model_ids():
    """추론 수준이 모델 ID 에 포함되므로 어떤 ID 든 그대로 전달돼야 합니다."""
    high = build_command("claude-sonnet-4-6", "지시")
    assert high == [
        "agy",
        "--model",
        "claude-sonnet-4-6",
        "--mode",
        "accept-edits",
        "-i",
        "지시",
    ]


def test_build_command_includes_accept_edits_mode_at_startup():
    """--mode accept-edits 가 시작 인자에 없으면 첫 편집 전에 승인 대화창이 뜹니다."""
    cmd = build_command("gemini-3.8-flash-medium", "본문")
    assert "--mode" in cmd
    idx = cmd.index("--mode")
    assert cmd[idx + 1] == "accept-edits"


def test_build_command_never_includes_dangerously_skip_permissions():
    """--dangerously-skip-permissions 는 범위 밖 명령까지 승인하므로 절대 쓰면 안 됩니다."""
    for model in ("gemini-3.8-flash-medium", "claude-sonnet-4-6"):
        cmd = build_command(model, "임의 지시")
        assert "--dangerously-skip-permissions" not in cmd


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_commit_notice_is_appended_when_enabled(tmp_path: Path, monkeypatch, capsys):
    """기본값에서는 preamble 뒤에 커밋 고지문이 붙어야 합니다."""
    from scripts import orca_agy_launch as mod

    target = tmp_path / "preamble.txt"
    target.write_text("원래 지시문", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd0"] = cmd0
        captured["cmd"] = list(cmd)
        captured["env"] = env
        # execvpe 가 성공했다고 가정하고 호출자 main 으로 돌아가게 하려면
        # 예외를 던지지 않고 호출자가 return 0 줄에 도달하지 못하게 막아야 합니다.
        # main 은 execvpe 이후 어떤 일도 하지 않으므로 그냥 raise 로 끊습니다.
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert prompt.startswith("원래 지시문")
    assert COMMIT_NOTICE.strip() in prompt


def test_commit_notice_omitted_when_disabled(tmp_path: Path, monkeypatch):
    target = tmp_path / "preamble.txt"
    target.write_text("원래 지시문", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    from scripts import orca_agy_launch as mod

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--no-commit-notice",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert prompt == "원래 지시문"
    assert COMMIT_NOTICE.strip() not in prompt


def test_reviewer_notice_is_appended_for_reviewer_preamble(tmp_path: Path, monkeypatch):
    """리뷰어 지시문(ORCA_REVIEW_DONE_V2)인 경우 커밋 강제 고지문 대신 리뷰어 고지문이 붙어야 합니다."""
    target = tmp_path / "preamble.txt"
    target.write_text("계약: ORCA_REVIEW_DONE_V2\n산출물: review_done.json", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    from scripts import orca_agy_launch as mod

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert REVIEWER_NOTICE.strip() in prompt
    assert COMMIT_NOTICE.strip() not in prompt


def test_reviewer_notice_omitted_when_no_commit_notice_given(tmp_path: Path, monkeypatch):
    """리뷰어 지시문이더라도 --no-commit-notice 지정 시 어떤 고지문도 붙지 않아야 합니다."""
    target = tmp_path / "preamble.txt"
    target.write_text("계약: ORCA_REVIEW_DONE_V2\n산출물: review_done.json", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    from scripts import orca_agy_launch as mod

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--no-commit-notice",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert prompt == "계약: ORCA_REVIEW_DONE_V2\n산출물: review_done.json"
    assert REVIEWER_NOTICE.strip() not in prompt
    assert COMMIT_NOTICE.strip() not in prompt


def test_role_flag_overrides_automatic_detection(tmp_path: Path, monkeypatch):
    """--role 인자로 자동 판정을 덮어쓸 수 있어야 합니다."""
    target = tmp_path / "preamble.txt"
    # 본문은 빌더 표지이지만 --role reviewer 로 지정
    target.write_text("일반 빌드 작업", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    from scripts import orca_agy_launch as mod

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--role",
                "reviewer",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert REVIEWER_NOTICE.strip() in prompt
    assert COMMIT_NOTICE.strip() not in prompt

    # 반대로 리뷰어 본문이지만 --role builder 로 지정
    target.write_text("계약: ORCA_REVIEW_DONE_V2", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--role",
                "builder",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert COMMIT_NOTICE.strip() in prompt
    assert REVIEWER_NOTICE.strip() not in prompt


def test_main_returns_nonzero_when_preamble_times_out(tmp_path: Path, capsys):
    target = tmp_path / "preamble.txt"
    # 파일을 만들지 않음 → 시간 초과
    from scripts import orca_agy_launch as mod

    code = mod.main(
        [
            "--model",
            "gemini-3.8-flash-medium",
            "--preamble",
            str(target),
            "--timeout-sec",
            "0.2",
        ]
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "preamble" in err


class _FakePrepare:
    """prepare_worker_terminal 대역.

    실제 함수는 orca terminal 을 호출하므로 테스트에서 쓸 수 없습니다.
    """

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, terminal, cli_type=None, model=None, launcher=None, **kwargs):
        self.calls.append(
            {
                "terminal": terminal,
                "cli_type": cli_type,
                "model": model,
                "launcher": launcher,
                "kwargs": kwargs,
            }
        )
        return self.results.pop(0) if self.results else {"ok": False, "detail": "후보 소진"}


def test_acquire_permissions_records_cli_metadata():
    """cli_type 을 넘기지 않으면 CLI 판정이 fail-closed 로 막혀 모드를 못 잡습니다.

    2026-08-31 에 감시기 헬퍼만 직접 불러 메타데이터가 비었고, 워커가 파일 편집
    대화창에 그대로 갇혔습니다.
    """
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    ok, _ = acquire_permissions(
        "term_x", "gemini-3.8-flash-high", delay_sec=0, sleep=lambda _: None, prepare=prepare
    )

    assert ok is True
    assert len(prepare.calls) == 1
    call = prepare.calls[0]
    assert call["cli_type"] == "antigravity"
    assert call["model"] == "gemini-3.8-flash-high"
    assert call["launcher"], "런처 경로를 기록하지 않았습니다"


def test_acquire_permissions_never_forces_mode_transition():
    """force_file_edit 은 스피너 화면에서도 키를 보내 plan 으로 밀어 넣습니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    acquire_permissions(
        "term_x", "gemini-3.8-flash-high", delay_sec=0, sleep=lambda _: None, prepare=prepare
    )

    assert prepare.calls[0]["kwargs"].get("force_file_edit") in (None, False)


def test_acquire_permissions_retries_while_not_ready():
    """생성 중에는 모드가 unknown 이라 준비가 실패합니다. 포기하면 안 됩니다."""
    prepare = _FakePrepare(
        [{"ok": False}, {"ok": False}, {"ok": True, "file_edit_auto_approve": {"ok": True}}]
    )

    ok, _ = acquire_permissions(
        "term_x",
        "gemini-3.8-flash-high",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 3


def test_acquire_permissions_retries_when_top_level_ok_but_file_edit_fails():
    """최상위 ok 가 True 더라도 file_edit_auto_approve.ok 가 False 면 성공으로 처리하지 않고 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "enabled", "ok": True},
            },
        ]
    )

    ok, _ = acquire_permissions(
        "term_x",
        "gemini-3.8-flash-high",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 2


def test_acquire_permissions_reports_failure_after_deadline():
    """확보하지 못했는데 성공으로 보고하면 승인 중단이 조용히 남습니다."""
    prepare = _FakePrepare([{"ok": False}] * 50)

    ok, detail = acquire_permissions(
        "term_x",
        "gemini-3.8-flash-high",
        delay_sec=0,
        deadline_sec=0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is False
    assert "마치지 못했습니다" in detail


def test_launcher_schedules_permission_setup(tmp_path: Path, monkeypatch):
    """런처가 exec 전에 준비 자식을 띄우지 않으면 4단계가 통째로 빠집니다."""
    monkeypatch.chdir(tmp_path)
    spawned = []

    def fake_popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        return object()

    spawn_permission_setup("term_y", "gemini-3.8-flash-high", popen=fake_popen)

    assert len(spawned) == 1
    cmd, kwargs = spawned[0]
    assert PERMISSION_SETUP_FLAG in cmd
    assert "term_y" in cmd
    assert "gemini-3.8-flash-high" in cmd, "자식이 모델을 몰라 메타데이터를 못 남깁니다"
    assert kwargs["start_new_session"] is True, "부모가 exec 되면 자식이 같이 죽습니다"


def test_permission_setup_child_requires_handle_and_model():
    """핸들이나 모델 없이 자식 모드를 부르면 조용히 통과시키면 안 됩니다."""
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_y"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "   ", "model"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_y", "  "]) == 2


def test_main_warns_when_terminal_handle_missing(tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / "preamble.txt"
    target.write_text("지시문", encoding="utf-8")
    from scripts import orca_agy_launch as mod

    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)

    def fake_execvpe(cmd0, cmd, env):
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)

    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "ORCA_TERMINAL_HANDLE" in err


def test_permission_setup_child_accepts_common_keywords():
    """자식 모드가 acquire_fn 에 cli_type 과 launcher 를 넘겨도 죽지 않아야 합니다.

    2026-08-31 에 이 계약이 깨져 있었습니다. common.run_permission_setup_child 는
    항상 두 값을 키워드로 전달하는데 런처의 래퍼가 그것을 받지 않아 자식이
    TypeError 로 즉시 죽었습니다. 부모는 이미 exec 로 사라진 뒤라 실패가 화면에
    남지 않았고, 승인 자동화가 통째로 동작하지 않은 채 워커가 대화창에 갇혔습니다.
    """
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])
    acquire = functools.partial(
        acquire_permissions,
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    code = common.run_permission_setup_child(
        [PERMISSION_SETUP_FLAG, "term_x", "claude-sonnet-4-6"],
        cli_type="antigravity",
        launcher="scripts/orca_agy_launch.py",
        acquire_fn=acquire,
        stderr=io.StringIO(),
        stdout=io.StringIO(),
    )

    assert code == 0
    assert prepare.calls[0]["cli_type"] == "antigravity"


def test_acquire_permissions_forwards_given_cli_type():
    """호출자가 cli_type 을 지정하면 그대로 prepare 에 전달돼야 합니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    acquire_permissions(
        "term_x",
        "claude-sonnet-4-6",
        cli_type="antigravity",
        launcher="scripts/orca_agy_launch.py",
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    call = prepare.calls[0]
    assert call["cli_type"] == "antigravity"
    assert call["launcher"] == "scripts/orca_agy_launch.py"


def test_main_never_calls_popen_for_permission_setup(tmp_path: Path, monkeypatch):
    """main 실행 시 ORCA_TERMINAL_HANDLE 이 설정되어 있어도 subprocess.Popen 이 절대 호출되지 않아야 합니다."""
    from scripts import orca_agy_launch as mod

    target = tmp_path / "preamble.txt"
    target.write_text("회귀 검증 지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_REGRESSION_PROBE_AGY")

    def fake_execvpe(cmd0, cmd, env):
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)

    popen_called = []

    def tracking_popen(*args, **kwargs):
        popen_called.append((args, kwargs))
        raise RuntimeError(
            "subprocess.Popen 이 호출되었습니다! 실제 프로세스 생성이 차단되지 않았습니다."
        )

    monkeypatch.setattr("subprocess.Popen", tracking_popen)

    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.8-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    assert len(popen_called) == 0, "subprocess.Popen 이 호출되었습니다"
