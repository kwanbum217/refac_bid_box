"""Command Code(cmd) 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Command Code CLI 를 Orca 워커로 씁니다. 터미널을 런처를 명령으로 지정해 먼저 만들고,
런처는 preamble 파일이 나타날 때까지 기다렸다가 cmd 를 기동합니다.

대화형 모드는 cmd "<message>" 위치 인자로 기동하며 os.execvpe 로 제어권을 넘깁니다.
--one-shot 을 주면 cmd -p <message> 단발 실행으로 바뀌며, subprocess.run 으로
완주시킨 뒤 대화형 셸로 이어받아 터미널 창을 유지합니다.

추론 등급은 모델 ID 에 포함되지 않고 --effort 플래그로 지정합니다.
DeepSeek V4.1 Flash 가 받는 값은 low, high, max 입니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_cmd_launch.py --model deepseek/deepseek-v4.1-flash --effort high"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - 코디네이터가 만든 고정 인자 목록으로만 cmd 를 호출합니다
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

# DeepSeek V4.1 Flash 가 지원하는 추론 등급 네 가지입니다. default 는 --effort 를
# 붙이지 않고 기동하는 모델 기본값이라 CLI 인자로는 나가지 않습니다. 목록 밖의 값을
# 주면 CLI 가 종료 코드 0 으로 "Unknown effort" 만 출력하고 기본 등급으로 진행하므로
# 런처가 먼저 거부합니다.
EFFORT_DEFAULT_LEVEL = "default"
EFFORT_CHOICES = ("default", "low", "high", "max")

wait_for_preamble = common.wait_for_preamble


def build_command(
    model: str,
    prompt: str,
    *,
    effort: str | None = None,
    one_shot: bool = False,
    auto: bool = False,
) -> list[str]:
    """cmd 기동 명령 배열을 조립합니다.

    대화형은 cmd "<message>" 위치 인자이고 단발은 cmd -p <message> 입니다.
    모델은 --model 로 provider/model 형태이며 추론 등급은 --effort 입니다.
    권한 자동 승인(--trust --yolo)은 기본으로 붙이지 않으며 명시적으로 요청될 때만
    포함합니다.
    """
    cmd = ["cmd", "--model", model]
    if effort and effort != EFFORT_DEFAULT_LEVEL:
        cmd.extend(["--effort", effort])
    if auto:
        # --permission-mode auto-accept 는 파일 편집만 자동 승인하고 셸 명령은
        # 여전히 대화창을 띄웁니다. 감시기가 그 대화창을 읽어 승인하지만 화면
        # 줄바꿈과 판정 지연 때문에 워커가 멈추는 구간이 생깁니다. 격리 워크트리에서
        # 도는 워커는 대화창 자체를 띄우지 않는 편이 낫습니다.
        cmd.extend(["--trust", "--yolo"])
    if one_shot:
        cmd.extend(["-p", prompt])
        return cmd
    cmd.append(prompt)
    return cmd


def build_completion_message(exit_code: int, model: str) -> str:
    """cmd 종료 후 터미널에 남길 완료 안내 문구를 조립합니다."""
    return f"\n---\nCommand Code 작업 완료 (종료 코드: {exit_code})\n---\n"


def resolve_shell(env: dict[str, str]) -> str:
    return env.get("SHELL") or DEFAULT_SHELL


def run_cmd(cmd: list[str], env: dict[str, str]) -> int:
    """cmd 를 자식 프로세스로 실행하고 표준 입출력은 터미널에 그대로 둡니다."""
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
            cli_type="cmd",
            launcher=str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        )

    parser = argparse.ArgumentParser(description="Command Code 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="Command Code 모델 ID (예: deepseek/deepseek-v4.1-flash, meta/muse-spark-1.3)",
    )
    parser.add_argument(
        "--effort",
        choices=EFFORT_CHOICES,
        help="추론 등급 (default, low, high, max). default 와 미지정은 모두 "
        "--effort 를 붙이지 않고 모델 기본값으로 기동합니다.",
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="cmd -p 단발 실행으로 기동합니다. 완료 후 셸로 이어받아 출력을 보존합니다.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="권한 자동 승인(--trust --yolo)을 추가합니다. 기본값은 미사용입니다.",
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
        effort=args.effort,
        one_shot=args.one_shot,
        auto=args.auto,
    )

    common.schedule_permission_setup(
        Path(__file__).resolve(),
        args.model,
        spawn_fn=spawn_permission_setup,
    )

    mode = "-p 단발" if args.one_shot else "대화형"
    effort_disp = (
        "모델 기본값" if not args.effort or args.effort == EFFORT_DEFAULT_LEVEL else args.effort
    )
    print(
        f"기동: cmd --model {args.model} --effort {effort_disp} ({mode}, 지시문 {len(prompt)}자)",
        flush=True,
    )

    if args.one_shot:
        exit_code = run_cmd(cmd, env)
        if args.no_keep_open:
            return exit_code
        print(build_completion_message(exit_code, args.model), end="", flush=True)
        open_interactive_shell(env)
        return exit_code

    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # nosec B606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
