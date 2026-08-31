"""Qwen Code 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Alibaba Token Plan 자격증명으로 도는 Qwen Code CLI 를 Orca 워커로 씁니다. Kimi
런처와 같은 순서 문제를 풉니다. 지시문(preamble)은 Dispatch 이후에야 얻을 수
있으므로, 터미널을 먼저 만들어 두고 나중에 명령을 밀어 넣으면 Orca 가 그 터미널을
에이전트 터미널로 등록하지 않아 좌측 목록에 워커 행이 생기지 않습니다. 이 런처를
명령으로 지정해 터미널을 만들면, 런처가 preamble 을 기다렸다가 qwen 을 띄웁니다.

Kimi 런처와 다른 점이 하나 있습니다. qwen 은 `-i` 로 지시문을 실행한 뒤 대화형
세션을 그대로 유지합니다. 따라서 단발 실행 후 셸로 이어받는 우회가 필요 없고,
코디네이터가 `orca terminal send` 로 후속 지시와 반려 사유를 같은 세션에 보낼 수
있습니다. `--one-shot` 을 주면 `-p` 단발 실행으로 바뀝니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_qwen_launch.py --model qwen3.7-plus"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
    # 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 쓰면 런처가 이어받습니다
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - 코디네이터가 만든 고정 인자 목록으로만 qwen 을 호출합니다
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import orca_worker_launch_common as common  # noqa: E402

PERMISSION_SETUP_FLAG = common.PERMISSION_SETUP_FLAG
run_permission_setup_child = common.run_permission_setup_child
schedule_permission_setup = common.schedule_permission_setup

DEFAULT_PREAMBLE = Path(".orca/preamble.txt")
DEFAULT_SHELL = "/bin/bash"
COMMIT_NOTICE = (
    "\n\n추가 지시: 작업을 마치면 반드시 변경 파일을 스테이징하고 커밋하십시오. "
    "git add -A 는 쓰지 마십시오. 커밋 없이 완료를 선언하면 계약 위반입니다. "
    "커밋 후 git log --oneline main..HEAD 로 확인하고 해시를 보고하십시오."
)


def registered_qwen_models() -> dict[str, str]:
    """MODEL_POOL 에 등록된 qwen provider 모델의 {풀 키: 실제 ID} 를 돌려줍니다."""
    from orca_model_router import MODEL_POOL

    return {name: info["id"] for name, info in MODEL_POOL.items() if info.get("provider") == "qwen"}


def resolve_model(model: str) -> str:
    """풀 키와 실제 모델 ID 를 모두 받아 실제 ID 로 정규화합니다.

    등록되지 않은 ID 는 여기서 막습니다. 2026-08-30 probe 에서 qwen3.8-max 와
    qwen3.8-flash 는 이 계정에서 401 을 돌려줬습니다. 그런 ID 로 기동하면 qwen 이
    화면에는 뜬 채 오류만 답하므로, 사람이 원인을 찾기 어렵습니다.
    """
    registered = registered_qwen_models()
    if model in registered:
        return registered[model]
    if model in registered.values():
        return model
    listed = "\n".join(f"    {key} -> {mid}" for key, mid in sorted(registered.items()))
    raise SystemExit(
        f"모델 {model!r} 이 MODEL_POOL 의 qwen 풀에 등록되어 있지 않습니다.\n"
        f"  등록된 모델:\n{listed}\n"
        "  등록되지 않은 ID 는 인증 오류만 답하고 워커가 아무 일도 하지 않습니다."
    )


def wait_for_preamble(path: Path, timeout_sec: float, poll_sec: float = 1.0) -> str:
    """preamble 파일이 나타나 내용이 채워질 때까지 기다립니다.

    코디네이터가 Dispatch 결과를 파일로 쓰기 전까지는 비어 있습니다. 크기가 0 인
    상태로 읽고 넘어가면 워커가 빈 지시로 기동하므로 내용이 있을 때만 돌려줍니다.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        time.sleep(poll_sec)
    raise TimeoutError(f"preamble 파일을 {timeout_sec:.0f}초 안에 받지 못했습니다: {path}")


def build_command(model_id: str, prompt: str, one_shot: bool) -> list[str]:
    """qwen 실행 인자를 만듭니다.

    기본은 -i 입니다. 지시문을 실행한 뒤 대화형 세션이 남아 코디네이터가 후속
    지시를 같은 세션에 보낼 수 있습니다. -p 는 단발이라 세션이 끝납니다.
    """
    flag = "-p" if one_shot else "-i"
    return ["qwen", "-m", model_id, flag, prompt]


def build_completion_message(exit_code: int, model_id: str) -> str:
    """qwen 종료 후 터미널에 남길 완료 안내 문구를 조립합니다."""
    return (
        f"\n---\nQwen 작업 완료 (종료 코드: {exit_code})\n"
        f"세션 이어가기: qwen -m {model_id} -c\n---\n"
    )


def resolve_shell(env: dict[str, str]) -> str:
    return env.get("SHELL") or DEFAULT_SHELL


def run_qwen(cmd: list[str], env: dict[str, str]) -> int:
    """qwen 을 자식 프로세스로 실행하고 표준 입출력은 터미널에 그대로 둡니다."""
    completed = subprocess.run(cmd, env=env)  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
    return completed.returncode


def open_interactive_shell(env: dict[str, str]) -> None:
    """대화형 셸로 프로세스를 대체해 터미널 창을 유지합니다."""
    shell = resolve_shell(env)
    os.execvpe(shell, [shell], env)  # noqa: S606  # nosec B606


def main(argv: list[str] | None = None) -> int:
    # 자식 모드: 부모가 실행된 뒤 독립 세션에서 승인 설정만 수행합니다.
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == PERMISSION_SETUP_FLAG:
        return run_permission_setup_child(
            raw,
            cli_type="qwen",
            launcher=str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        )

    parser = argparse.ArgumentParser(description="Qwen Code 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="풀 키 또는 모델 ID (예: qwen-plus, qwen3.7-plus, deepseek-v4-pro)",
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="-i 대신 -p 로 단발 실행합니다. 대화형 세션이 남지 않습니다.",
    )
    parser.add_argument(
        "--no-commit-notice",
        action="store_true",
        help="커밋 고지문을 붙이지 않습니다.",
    )
    parser.add_argument(
        "--no-keep-open",
        action="store_true",
        help="qwen 종료 후 셸로 이어받지 않고 종료 코드를 그대로 반환합니다.",
    )
    args = parser.parse_args(argv)

    # preamble 을 기다리기 전에 검사합니다. 모델이 없으면 최대 300초를 기다린 뒤에야
    # 실패하게 되고, 그동안 코디네이터는 워커가 도는 줄 압니다.
    model_id = resolve_model(args.model)

    print(f"preamble 대기 중: {args.preamble} (최대 {args.timeout_sec:.0f}초)", flush=True)
    try:
        prompt = wait_for_preamble(args.preamble, args.timeout_sec)
    except TimeoutError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    if not args.no_commit_notice:
        prompt += COMMIT_NOTICE

    env = dict(os.environ)
    cmd = build_command(model_id, prompt, args.one_shot)

    # Qwen Code 는 -i(대화형)과 -p(--one-shot 단발) 두 모드를 지원합니다.
    # 단발 모드라도 워커가 긴 작업(파일 수정, 셸 명령 실행 등)을 수행하는 동안
    # 셸 명령 승인 감시기 부착과 워커 메타데이터 기록(cli_type=qwen)이 반드시 필요합니다.
    # 또한 prepare_worker_terminal 은 Qwen 메타데이터를 인식하여 shift+tab 전송을
    # 안전하게 건너뛰므로(fail-closed/auto mode 보호), 두 모드 모두 동일하게
    # 권한 자동 승인 준비 자식을 기동합니다.
    schedule_permission_setup(Path(__file__).resolve(), model_id)

    mode = "-p 단발" if args.one_shot else "-i 대화형"
    print(f"기동: qwen -m {model_id} ({mode}, 지시문 {len(prompt)}자)", flush=True)
    # 인자는 셸을 거치지 않고 그대로 전달되므로 주입 위험이 없습니다. 모델 ID 와
    # 지시문 모두 코디네이터가 만든 값입니다.
    exit_code = run_qwen(cmd, env)

    if args.no_keep_open:
        return exit_code

    print(build_completion_message(exit_code, model_id), end="", flush=True)
    open_interactive_shell(env)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
