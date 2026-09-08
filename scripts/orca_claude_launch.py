"""Claude Code 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Claude Code CLI 를 Orca 워커로 씁니다. 터미널을 런처를 명령으로 지정해 먼저 만들고,
런처는 preamble 파일이 나타날 때까지 기다렸다가 claude 를 기동합니다.

대화형 모드는 claude [prompt] 위치 인자로 기동하며 os.execvpe 로 제어권을 넘깁니다.
--one-shot 을 주면 -p 단발 실행으로 바뀌며, subprocess.run 으로 완주시킨 뒤
대화형 셸로 이어받아 터미널 창을 유지합니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_claude_launch.py --model claude-3-7-sonnet-20250219"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - 코디네이터가 만든 고정 인자 목록으로만 claude 를 호출합니다
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import orca_worker_launch_common as common  # noqa: E402

PERMISSION_SETUP_FLAG = common.PERMISSION_SETUP_FLAG
DEFAULT_PREAMBLE = common.DEFAULT_PREAMBLE
DEFAULT_SHELL = "/bin/bash"
COMMIT_NOTICE = common.COMMIT_NOTICE
REVIEWER_NOTICE = common.REVIEWER_NOTICE

wait_for_preamble = common.wait_for_preamble


def build_command(
    model: str,
    prompt: str,
    *,
    one_shot: bool = False,
    permission_mode: str | None = None,
) -> list[str]:
    """claude 기동 명령 배열을 조립합니다.

    대화형은 claude [prompt] 위치 인자이고 단발은 -p 입니다. 모델은 --model 입니다.
    권한 모드 인자(--permission-mode)는 기본으로 붙이지 않으며
    명시적으로 요청될 때만 포함합니다.
    """
    cmd = ["claude", "--model", model]
    if permission_mode:
        cmd.extend(["--permission-mode", permission_mode])
    if one_shot:
        cmd.extend(["-p", prompt])
    else:
        cmd.append(prompt)
    return cmd


def build_completion_message(exit_code: int, model: str) -> str:
    """claude 종료 후 터미널에 남길 완료 안내 문구를 조립합니다."""
    return f"\n---\nClaude 작업 완료 (종료 코드: {exit_code})\n---\n"


def resolve_shell(env: dict[str, str]) -> str:
    return env.get("SHELL") or DEFAULT_SHELL


def run_claude(cmd: list[str], env: dict[str, str]) -> int:
    """claude 를 자식 프로세스로 실행하고 표준 입출력은 터미널에 그대로 둡니다."""
    completed = subprocess.run(cmd, env=env)  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
    return completed.returncode


def open_interactive_shell(env: dict[str, str]) -> None:
    """대화형 셸로 프로세스를 대체해 터미널 창을 유지합니다."""
    shell = resolve_shell(env)
    os.execvpe(shell, [shell], env)  # noqa: S606  # nosec B606


def spawn_permission_setup(
    launcher_script: str | Path,
    terminal: str,
    model: str,
    *,
    popen=subprocess.Popen,
) -> None:
    common.spawn_permission_setup(
        launcher_script,
        terminal,
        model,
        popen=popen,
    )


def main(argv: list[str] | None = None) -> int:
    # 자식 모드: 부모가 실행된 뒤 독립 세션에서 승인 설정만 수행합니다.
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == PERMISSION_SETUP_FLAG:
        return common.run_permission_setup_child(
            raw,
            cli_type="claude",
            launcher=str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        )

    parser = argparse.ArgumentParser(description="Claude Code 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="Claude 모델 ID (예: claude-3-7-sonnet-20250219, claude-sonnet-4-6)",
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="-p 로 단발 실행합니다. 완료 후 셸로 이어받아 출력을 보존합니다.",
    )
    parser.add_argument(
        "--permission-mode",
        type=str,
        default=None,
        help="권한 모드 (--permission-mode, 예: acceptEdits). 기본값은 미사용입니다.",
    )
    parser.add_argument(
        "--role",
        choices=["auto", "builder", "reviewer"],
        default="auto",
        help="워커 역할 (auto, builder, reviewer. 기본 auto)",
    )
    parser.add_argument(
        "--no-commit-notice",
        action="store_true",
        help="커밋 고지문을 붙이지 않습니다.",
    )
    parser.add_argument(
        "--no-keep-open",
        action="store_true",
        help="단발 실행 종료 후 셸로 이어받지 않고 종료 코드를 그대로 반환합니다.",
    )
    args = parser.parse_args(argv)

    print(f"preamble 대기 중: {args.preamble} (최대 {args.timeout_sec:.0f}초)", flush=True)
    try:
        prompt = wait_for_preamble(args.preamble, args.timeout_sec)
    except (TimeoutError, ValueError) as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    prompt = common.append_role_notice(
        prompt,
        role=args.role,
        no_commit_notice=args.no_commit_notice,
    )

    env = dict(os.environ)
    cmd = build_command(
        args.model,
        prompt,
        one_shot=args.one_shot,
        permission_mode=args.permission_mode,
    )

    common.schedule_permission_setup(
        Path(__file__).resolve(),
        args.model,
        spawn_fn=spawn_permission_setup,
    )

    mode = "-p 단발" if args.one_shot else "대화형"
    print(f"기동: claude --model {args.model} ({mode}, 지시문 {len(prompt)}자)", flush=True)

    if args.one_shot:
        exit_code = run_claude(cmd, env)
        if args.no_keep_open:
            return exit_code
        print(build_completion_message(exit_code, args.model), end="", flush=True)
        open_interactive_shell(env)
        return exit_code

    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # nosec B606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
