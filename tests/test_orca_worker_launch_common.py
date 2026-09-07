"""Orca 워커 런처 공통 모듈(orca_worker_launch_common) 계약 검증."""

from __future__ import annotations

import io
from pathlib import Path

from scripts.orca_worker_launch_common import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    ROLE_MARKER_BUILDER,
    ROLE_MARKER_REVIEWER,
    acquire_permissions,
    append_role_notice,
    detect_role,
    format_role_marker,
    inject_role_marker,
    is_terminal_ready,
    parse_role_marker,
    resolve_notice,
    run_permission_setup_child,
    schedule_permission_setup,
    spawn_permission_setup,
)


class _FakePrepare:
    """prepare_worker_terminal 대역."""

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


def test_prepare_called_with_cli_type_model_and_launcher():
    """(1) prepare_worker_terminal 을 호출하며 cli_type, model, launcher 를 넘겨야 합니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    ok, _ = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        launcher="scripts/orca_agy_launch.py",
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 1
    call = prepare.calls[0]
    assert call["terminal"] == "term_1"
    assert call["cli_type"] == "antigravity"
    assert call["model"] == "model_a"
    assert call["launcher"] == "scripts/orca_agy_launch.py"


def test_prepare_never_forces_file_edit():
    """(2) force_file_edit 을 사용하지 않아야 합니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert prepare.calls[0]["kwargs"].get("force_file_edit") in (None, False)


def test_retries_until_ready_when_not_ready():
    """(3) 준비되지 않으면 마감까지 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {"ok": False},
            {"ok": False},
            {"ok": True, "file_edit_auto_approve": {"ok": True}},
        ]
    )

    ok, _ = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 3


def test_retries_when_top_level_ok_but_file_edit_not_ok_for_antigravity():
    """최상위 ok 가 True 더라도 file_edit_auto_approve.ok 가 False 면 성공으로 판단하지 않고 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {
                "ok": True,
                "meta": {"cli_type": "antigravity"},
                "trust_prompt": {"ok": True},
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            {
                "ok": True,
                "meta": {"cli_type": "antigravity"},
                "trust_prompt": {"ok": True},
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "enabled", "ok": True},
            },
        ]
    )

    ok, detail = acquire_permissions(
        "term_1",
        "gemini-3.8-flash-medium",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 2
    assert "준비 완료" in detail


def test_reports_failure_after_deadline_exceeded():
    """(4) 마감 초과 시 성공으로 보고하지 않고 False 를 반환해야 합니다."""
    prepare = _FakePrepare([{"ok": False}] * 20)

    ok, detail = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is False
    assert "마치지 못했습니다" in detail


def test_spawn_permission_setup_detaches_child_session(tmp_path: Path, monkeypatch):
    """(5) 자식이 start_new_session=True 로 분리되어 실행되어야 합니다."""
    monkeypatch.chdir(tmp_path)
    spawned = []

    def fake_popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        return object()

    spawn_permission_setup(
        "scripts/orca_agy_launch.py",
        "term_z",
        "gemini-3.8-flash-medium",
        popen=fake_popen,
    )

    assert len(spawned) == 1
    cmd, kwargs = spawned[0]
    assert PERMISSION_SETUP_FLAG in cmd
    assert "term_z" in cmd
    assert "gemini-3.8-flash-medium" in cmd
    assert kwargs.get("start_new_session") is True


def test_child_mode_returns_exit_code_2_on_empty_args():
    """(6) 핸들이나 모델이 비어 있으면 자식 모드가 종료 코드 2 를 반환해야 합니다."""
    err_stream = io.StringIO()
    assert (
        run_permission_setup_child([PERMISSION_SETUP_FLAG], cli_type="kimi", stderr=err_stream) == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x"], cli_type="kimi", stderr=err_stream
        )
        == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "  ", "model_a"], cli_type="kimi", stderr=err_stream
        )
        == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "   "], cli_type="kimi", stderr=err_stream
        )
        == 2
    )


def test_child_mode_returns_0_on_success_and_1_on_failure():
    """자식 모드에서 acquire_permissions 결과에 따라 0 또는 1 을 반환합니다."""
    out_stream = io.StringIO()
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "model_a"],
            cli_type="kimi",
            acquire_fn=lambda *args, **kwargs: (True, "완료"),
            stdout=out_stream,
        )
        == 0
    )

    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "model_a"],
            cli_type="kimi",
            acquire_fn=lambda *args, **kwargs: (False, "실패"),
            stdout=out_stream,
        )
        == 1
    )


def test_schedule_permission_setup_warns_when_handle_absent():
    """ORCA_TERMINAL_HANDLE 이 없으면 stderr 에 경고를 남기고 False 를 반환합니다."""
    err_stream = io.StringIO()
    out_stream = io.StringIO()
    spawned = []

    res = schedule_permission_setup(
        "scripts/orca_kimi_launch.py",
        "or-free/nemotron-ultra",
        terminal="",
        spawn_fn=lambda *args: spawned.append(args),
        stderr=err_stream,
        stdout=out_stream,
    )

    assert res is False
    assert len(spawned) == 0
    assert "ORCA_TERMINAL_HANDLE" in err_stream.getvalue()


def test_schedule_permission_setup_spawns_when_handle_present():
    """ORCA_TERMINAL_HANDLE 이 존재하면 자식을 띄우고 True 를 반환합니다."""
    out_stream = io.StringIO()
    spawned = []

    res = schedule_permission_setup(
        "scripts/orca_kimi_launch.py",
        "or-free/nemotron-ultra",
        terminal="term_k",
        spawn_fn=lambda *args: spawned.append(args),
        stdout=out_stream,
    )

    assert res is True
    assert len(spawned) == 1
    assert spawned[0][1] == "term_k"
    assert spawned[0][2] == "or-free/nemotron-ultra"


def test_is_terminal_ready_rules():
    """CLI 별 준비 완료 판정 규칙을 검증합니다."""
    # Antigravity: file_edit_auto_approve.ok 가 True 여야 함
    assert (
        is_terminal_ready(
            {"ok": True, "file_edit_auto_approve": {"ok": True}},
            cli_type="antigravity",
        )
        is True
    )
    assert (
        is_terminal_ready(
            {"ok": True, "file_edit_auto_approve": {"ok": False}},
            cli_type="antigravity",
        )
        is False
    )
    assert (
        is_terminal_ready(
            {"ok": True},
            cli_type="antigravity",
        )
        is False
    )

    # Kimi / Qwen: auto_approve_watcher.ok 가 True 이고 trust_prompt 가 still_present 가 아니면 준비 완료
    assert (
        is_terminal_ready(
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "trust_prompt": {"status": "not_present", "ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            cli_type="kimi",
        )
        is True
    )
    assert (
        is_terminal_ready(
            {
                "ok": False,
                "auto_approve_watcher": {"ok": False},
            },
            cli_type="kimi",
        )
        is False
    )


def test_detect_role_identifies_reviewer_indicators():
    """ORCA_REVIEW_DONE_V2 나 review_done.json 또는 role: reviewer 가 있으면 reviewer 로 판정합니다."""
    assert (
        detect_role("return_contract: ORCA_REVIEW_DONE_V2\nreport_path: review_done.json")
        == "reviewer"
    )
    assert detect_role("review_done.json 보고서를 작성하십시오.") == "reviewer"
    assert detect_role("role: reviewer") == "reviewer"
    assert detect_role('role: "reviewer"') == "reviewer"


def test_detect_role_identifies_builder():
    """ORCA_WORKER_DONE_V2 가 있거나 리뷰어 표지가 없으면 builder 로 판정합니다."""
    assert (
        detect_role("return_contract: ORCA_WORKER_DONE_V2\nreport_path: worker_done.json")
        == "builder"
    )


def test_detect_role_fails_closed_to_builder():
    """역할 표지가 없는 텍스트나 빈 문자열은 fail-closed 원칙에 따라 builder 로 판정합니다."""
    assert detect_role("일반 빌드 작업 지시문입니다.") == "builder"
    assert detect_role("") == "builder"
    assert detect_role("   \n\t") == "builder"


def test_reviewer_notice_contract_content():
    """리뷰어 고지문은 커밋 금지, git add 금지, review_done.json 커밋 금지, 보고서+전송 완료를 명시해야 합니다."""
    assert "커밋" in REVIEWER_NOTICE
    assert "git add" in REVIEWER_NOTICE
    assert "review_done.json" in REVIEWER_NOTICE
    assert "worker_done" in REVIEWER_NOTICE


def test_resolve_notice_with_auto():
    """role='auto' 일 때 지시문 분석 결과에 따라 올바른 고지문을 반환합니다."""
    assert resolve_notice("auto", "review_done.json 작성") == REVIEWER_NOTICE
    assert resolve_notice("auto", "worker_done.json 작성") == COMMIT_NOTICE
    assert resolve_notice("auto", "알 수 없는 작업") == COMMIT_NOTICE


def test_resolve_notice_role_override():
    """role='reviewer' 또는 role='builder' 로 명시적 강제 시 지시문 내용과 무관하게 지정된 고지문을 반환합니다."""
    # 빌더 지시문이지만 role='reviewer' 로 강제
    assert resolve_notice("reviewer", "ORCA_WORKER_DONE_V2") == REVIEWER_NOTICE
    # 리뷰어 지시문이지만 role='builder' 로 강제
    assert resolve_notice("builder", "ORCA_REVIEW_DONE_V2") == COMMIT_NOTICE


def test_append_role_notice_respects_no_commit_notice():
    """no_commit_notice=True 이면 역할이나 지시문과 무관하게 어떤 고지문도 붙이지 않습니다."""
    reviewer_prompt = "review_done.json 검토 지시"
    builder_prompt = "코드 수정 지시"

    assert (
        append_role_notice(reviewer_prompt, role="auto", no_commit_notice=True) == reviewer_prompt
    )
    assert append_role_notice(builder_prompt, role="auto", no_commit_notice=True) == builder_prompt
    assert (
        append_role_notice(reviewer_prompt, role="reviewer", no_commit_notice=True)
        == reviewer_prompt
    )
    assert (
        append_role_notice(builder_prompt, role="builder", no_commit_notice=True) == builder_prompt
    )


def test_append_role_notice_appends_correct_notice():
    """no_commit_notice=False 일 때 적절한 고지문이 prompt 뒤에 추가됩니다."""
    reviewer_prompt = "review_done.json 검토 지시"
    res_reviewer = append_role_notice(reviewer_prompt, role="auto", no_commit_notice=False)
    assert res_reviewer.startswith(reviewer_prompt)
    assert REVIEWER_NOTICE in res_reviewer
    assert COMMIT_NOTICE not in res_reviewer

    builder_prompt = "코드 수정 지시"
    res_builder = append_role_notice(builder_prompt, role="auto", no_commit_notice=False)
    assert res_builder.startswith(builder_prompt)
    assert COMMIT_NOTICE in res_builder
    assert REVIEWER_NOTICE not in res_builder


def test_format_role_marker():
    """format_role_marker 는 builder 와 reviewer 역할을 규격화된 한 줄 표지로 생성합니다."""
    assert format_role_marker("reviewer") == ROLE_MARKER_REVIEWER
    assert format_role_marker("builder") == ROLE_MARKER_BUILDER
    assert format_role_marker("REVIEWER") == ROLE_MARKER_REVIEWER
    assert format_role_marker("BUILDER") == ROLE_MARKER_BUILDER
    # 알 수 없는 역할이나 빈 문자열은 builder 로 정규화
    assert format_role_marker("unknown") == ROLE_MARKER_BUILDER
    assert format_role_marker("") == ROLE_MARKER_BUILDER
    assert format_role_marker(None) == ROLE_MARKER_BUILDER


def test_parse_role_marker():
    """parse_role_marker 는 독립된 한 줄의 역할 표지를 감지합니다."""
    assert parse_role_marker(ROLE_MARKER_REVIEWER) == "reviewer"
    assert parse_role_marker(ROLE_MARKER_BUILDER) == "builder"
    assert parse_role_marker("  [ORCA_ROLE: reviewer]  ") == "reviewer"
    assert parse_role_marker("ORCA_ROLE: reviewer") == "reviewer"
    assert parse_role_marker("ORCA_ROLE: builder") == "builder"
    assert parse_role_marker("[ORCA_ROLE: Reviewer]") == "reviewer"

    # 여러 줄 텍스트에서 독립된 줄 감지
    multiline = "첫 줄\n[ORCA_ROLE: reviewer]\n마지막 줄"
    assert parse_role_marker(multiline) == "reviewer"

    # 문장 내에 섞인 경우 독립된 줄이 아니므로 None
    assert parse_role_marker("이 문장은 [ORCA_ROLE: reviewer] 가 포함됨") is None
    assert parse_role_marker("ORCA_ROLE: reviewer is not a line") is None
    assert parse_role_marker("일반 텍스트") is None
    assert parse_role_marker("") is None


def test_inject_role_marker():
    """inject_role_marker 는 preamble 맨 앞에 표지를 추가하고 이미 있으면 교체합니다."""
    original = "작업 지시문 본문"
    injected = inject_role_marker(original, "reviewer")
    assert injected.startswith(ROLE_MARKER_REVIEWER + "\n\n")
    assert original in injected

    # 이미 표지가 있는 경우 교체
    replaced = inject_role_marker(injected, "builder")
    assert replaced.startswith(ROLE_MARKER_BUILDER + "\n\n")
    assert ROLE_MARKER_REVIEWER not in replaced
    assert original in replaced


def test_detect_role_prioritizes_role_marker_over_content():
    """detect_role 은 본문 내용보다 역할 표지를 최우선 근거로 삼습니다."""
    # 1. AK2 실제 리뷰어 재현 케이스: 본문에 ORCA_REVIEW_DONE_V2 나 review_done.json 이 없어도 표지가 reviewer 면 reviewer
    real_reviewer_prompt = (
        f"{ROLE_MARKER_REVIEWER}\n\n"
        "You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n"
        "=== TASK ===\n"
        "빌더 산출물에 대한 독립 코드 리뷰를 수행한다. "
        "정본 사양(Capsule): 현재 작업 디렉터리의 .orca/capsules/task_ak2_review/capsule.yaml."
    )
    assert detect_role(real_reviewer_prompt) == "reviewer"

    # 2. 빌더가 review_done.json 이나 ORCA_REVIEW_DONE_V2 를 다루더라도 표지가 builder 면 builder 로 판정
    builder_working_on_review = (
        f"{ROLE_MARKER_BUILDER}\n\n"
        "작업 내용: review_done.json 생성 모듈 및 ORCA_REVIEW_DONE_V2 계약 수정"
    )
    assert detect_role(builder_working_on_review) == "builder"


def test_detect_role_four_paths():
    """detect_role 의 네 경로(리뷰어 표지, 빌더 표지, 표지 없는 옛 형태, 확정 불가)를 단언합니다."""
    # 경로 1: 리뷰어 표지
    assert detect_role(f"{ROLE_MARKER_REVIEWER}\n일반 본문") == "reviewer"

    # 경로 2: 빌더 표지
    assert detect_role(f"{ROLE_MARKER_BUILDER}\n일반 본문") == "builder"

    # 경로 3: 표지 없는 옛 형태 (하위 호환)
    assert detect_role("계약: ORCA_REVIEW_DONE_V2") == "reviewer"
    assert detect_role("산출물: review_done.json") == "reviewer"
    assert detect_role('role: "reviewer"') == "reviewer"
    assert detect_role("role: reviewer") == "reviewer"

    # 경로 4: 표지 없는 옛 형태 확정 불가 (fail-closed to builder)
    assert detect_role("일반 빌드 작업 지시문") == "builder"
    assert detect_role("") == "builder"


def test_resolve_notice_with_real_preamble_scenarios():
    """실제 preamble 형태에서 resolve_notice 및 append_role_notice 가 올바르게 동작합니다."""
    # 리뷰어 preamble: REVIEWER_NOTICE 가 붙고 COMMIT_NOTICE 는 붙지 않음
    rev_preamble = f"{ROLE_MARKER_REVIEWER}\n\n=== TASK ===\n리뷰 수행"
    assert resolve_notice("auto", rev_preamble) == REVIEWER_NOTICE
    appended_rev = append_role_notice(rev_preamble, role="auto")
    assert REVIEWER_NOTICE in appended_rev
    assert COMMIT_NOTICE not in appended_rev

    # 빌더 preamble: COMMIT_NOTICE 가 붙고 REVIEWER_NOTICE 는 붙지 않음
    bld_preamble = f"{ROLE_MARKER_BUILDER}\n\n=== TASK ===\n코드 구현"
    assert resolve_notice("auto", bld_preamble) == COMMIT_NOTICE
    appended_bld = append_role_notice(bld_preamble, role="auto")
    assert COMMIT_NOTICE in appended_bld
    assert REVIEWER_NOTICE not in appended_bld

    # --role 플래그 강제 시 표지보다 우선
    assert resolve_notice("builder", rev_preamble) == COMMIT_NOTICE
    assert resolve_notice("reviewer", bld_preamble) == REVIEWER_NOTICE

    # --no-commit-notice 지정 시 어떤 고지문도 붙지 않음
    assert append_role_notice(rev_preamble, role="auto", no_commit_notice=True) == rev_preamble
    assert append_role_notice(bld_preamble, role="auto", no_commit_notice=True) == bld_preamble
