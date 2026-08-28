"""Antigravity(agy) 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Antigravity TUI 는 `orca terminal create --command "agy --model <id>"` 로 띄우면
스플래시에서 멈추는 사례가 반복됐습니다. 지시문을 런치 인자(`-i`)로 넘겨 기동하면
안정적이지만, 지시문(preamble)은 Dispatch 이후에야 얻을 수 있어서 순서가 맞지
않았습니다. 이 런처가 그 순서를 뒤집습니다. 터미널을 **런처를 명령으로 지정해**
먼저 만들고, 런처는 preamble 파일이 나타날 때까지 기다렸다가 agy 를 exec 합니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_agy_launch.py --model gemini-3.7-flash-medium"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
    # 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 쓰면 런처가 이어받습니다
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_PREAMBLE = Path(".orca/preamble.txt")
COMMIT_NOTICE = (
    "\n\n추가 지시: 작업을 마치면 반드시 변경 파일을 스테이징하고 커밋하십시오. "
    "git add -A 는 쓰지 마십시오. 커밋 없이 완료를 선언하면 계약 위반입니다. "
    "커밋 후 git log --oneline main..HEAD 로 확인하고 해시를 보고하십시오."
)


def wait_for_preamble(path: Path, timeout_sec: float, poll_sec: float = 1.0) -> str:
    """preamble 파일이 나타나 내용이 채워질 때까지 기다립니다.

    코디네이터가 Dispatch 결과를 파일로 쓰기 전까지는 비어 있습니다. 크기가 0 인
    상태로 읽고 넘어가면 워커가 빈 지시로 기동하므로 내용이 있을 때만 돌려줍니다.
    시간이 지나도 내용이 채워지지 않으면 TimeoutError 를 던져 호출자가 종료 코드를
    책임지게 합니다.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        time.sleep(poll_sec)
    raise TimeoutError(f"preamble 파일을 {timeout_sec:.0f}초 안에 받지 못했습니다: {path}")


def build_command(model: str, prompt: str) -> list[str]:
    """agy 기동 명령 배열을 순수 함수로 조립합니다.

    Antigravity 는 추론 수준이 모델 ID 에 포함되므로 별도 effort 인자가 없습니다.
    """
    return ["agy", "--model", model, "-i", prompt]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="Antigravity 모델 ID (예: gemini-3.7-flash-medium, claude-sonnet-4-6)",
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--no-commit-notice",
        action="store_true",
        help="커밋 고지문을 붙이지 않습니다. one-shot 워커는 기본으로 붙입니다.",
    )
    args = parser.parse_args(argv)

    print(f"preamble 대기 중: {args.preamble} (최대 {args.timeout_sec:.0f}초)", flush=True)
    try:
        prompt = wait_for_preamble(args.preamble, args.timeout_sec)
    except TimeoutError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    if not args.no_commit_notice:
        prompt += COMMIT_NOTICE

    env = dict(os.environ)
    cmd = build_command(args.model, prompt)
    print(f"기동: agy --model {args.model} (지시문 {len(prompt)}자)", flush=True)
    # 인자는 셸을 거치지 않고 그대로 전달되므로 주입 위험이 없습니다. 모델 ID 와
    # 지시문 모두 코디네이터가 만든 값입니다.
    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # nosec B606
    return 0  # execvpe 가 성공하면 여기에 도달하지 않습니다.


if __name__ == "__main__":
    raise SystemExit(main())
