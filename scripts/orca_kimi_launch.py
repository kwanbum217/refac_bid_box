"""Kimi Code 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Kimi TUI 는 주입된 Enter 를 종료로 처리하므로 `dispatch --inject` 를 쓸 수 없고,
지시문을 `-p` 런치 인자로 넘겨야 합니다. 그런데 지시문(preamble)은 Dispatch 이후에야
얻을 수 있어서, 지금까지는 명령 없는 셸 터미널을 먼저 만들고 나중에 명령을 밀어
넣었습니다. 그 결과 Orca 는 그 터미널을 에이전트 터미널로 등록하지 않았고 좌측
목록에 워커 행이 생기지 않아 진행 상태를 눈으로 볼 수 없었습니다.

이 런처가 그 순서를 뒤집습니다. 터미널을 **런처를 명령으로 지정해** 먼저 만들고,
런처는 preamble 파일이 나타날 때까지 기다렸다가 kimi 를 자식 프로세스로 실행합니다.
`-p` 는 단발 모드이므로 작업이 끝나면 kimi 가 종료됩니다. 예전에는 `os.execvpe` 로
프로세스를 kimi 에 넘겨 창까지 함께 닫혔지만, 이제는 종료 코드와 완료 안내를 남긴 뒤
대화형 셸로 이어받아 cursor·Antigravity 워커처럼 사후에 출력을 확인할 수 있습니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_kimi_launch.py --model or-free/nemotron-ultra"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
    # 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 쓰면 런처가 이어받습니다
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess  # nosec B404 - 코디네이터가 만든 고정 인자 목록으로만 kimi 를 호출합니다
import sys
import time
from pathlib import Path

DEFAULT_PREAMBLE = Path(".orca/preamble.txt")
DEFAULT_HOME = Path.home() / ".kimi-openrouter-bakeoff"
DEFAULT_SHELL = "/bin/bash"
COMMIT_NOTICE = (
    "\n\n추가 지시: 작업을 마치면 반드시 변경 파일을 스테이징하고 커밋하십시오. "
    "git add -A 는 쓰지 마십시오. 커밋 없이 완료를 선언하면 계약 위반입니다. "
    "커밋 후 git log --oneline main..HEAD 로 확인하고 해시를 보고하십시오."
)


def available_models(home: Path) -> list[str]:
    """지정한 KIMI_CODE_HOME 프로필의 config.toml 에 등록된 모델 별칭을 돌려줍니다."""
    config = home / "config.toml"
    if not config.exists():
        return []
    pattern = re.compile(r'^\s*\[models\."([^"]+)"\]', re.MULTILINE)
    return pattern.findall(config.read_text(encoding="utf-8"))


def assert_model_available(model: str, home: Path) -> None:
    """기동 전에 모델이 그 프로필에 있는지 확인합니다.

    프로필마다 등록된 모델이 다릅니다. 2026-08-30 에 코디네이터가 기본 프로필
    (~/.kimi-code)에서 or-free/minimax-m3 응답을 확인한 뒤 런처로 띄웠는데, 런처의
    DEFAULT_HOME 은 ~/.kimi-openrouter-bakeoff 라 그 프로필에는 해당 모델이 없어
    기동 직후 종료했습니다. 화면에는 워커가 뜬 것처럼 보이므로 사람이 원인을
    찾기 어렵습니다. 여기서 미리 걸러 어느 프로필에 무엇이 있는지 알려 줍니다.
    """
    models = available_models(home)
    if not models:
        raise SystemExit(
            f"KIMI_CODE_HOME 프로필에 config.toml 이 없거나 모델이 없습니다: {home}\n"
            "  --home 으로 올바른 프로필을 지정하십시오."
        )
    if model not in models:
        listed = "\n".join(f"    {m}" for m in sorted(models))
        raise SystemExit(
            f"모델 {model!r} 이 프로필 {home} 에 등록되어 있지 않습니다.\n"
            f"  이 프로필에서 쓸 수 있는 모델:\n{listed}\n"
            "  --home 으로 다른 프로필을 지정하거나 등록된 모델을 쓰십시오."
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


def build_command(model: str, prompt: str) -> list[str]:
    return ["kimi", "-m", model, "-p", prompt]


def build_completion_message(exit_code: int, model: str) -> str:
    """kimi 종료 후 터미널에 남길 완료 안내 문구를 조립합니다."""
    return (
        f"\n---\nKimi 작업 완료 (종료 코드: {exit_code})\n세션 이어가기: kimi -m {model} -c\n---\n"
    )


def resolve_shell(env: dict[str, str]) -> str:
    return env.get("SHELL") or DEFAULT_SHELL


def run_kimi(cmd: list[str], env: dict[str, str]) -> int:
    """kimi 를 자식 프로세스로 실행하고 표준 입출력은 터미널에 그대로 둡니다."""
    completed = subprocess.run(cmd, env=env)  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
    return completed.returncode


def open_interactive_shell(env: dict[str, str]) -> None:
    """대화형 셸로 프로세스를 대체해 터미널 창을 유지합니다."""
    shell = resolve_shell(env)
    os.execvpe(shell, [shell], env)  # noqa: S606  # nosec B606


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kimi Code 워커 런처")
    parser.add_argument(
        "--model", required=True, help="Kimi 모델 별칭 (예: or-free/nemotron-ultra)"
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="KIMI_CODE_HOME 프로필")
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--no-commit-notice",
        action="store_true",
        help="커밋 고지문을 붙이지 않습니다. one-shot 워커는 기본으로 붙입니다.",
    )
    parser.add_argument(
        "--no-keep-open",
        action="store_true",
        help="kimi 종료 후 셸로 이어받지 않고 kimi 종료 코드를 그대로 반환합니다.",
    )
    args = parser.parse_args(argv)

    # preamble 을 기다리기 전에 검사합니다. 모델이 없으면 최대 300초를 기다린 뒤에야
    # 실패하게 되고, 그동안 코디네이터는 워커가 도는 줄 압니다.
    assert_model_available(args.model, args.home)

    print(f"preamble 대기 중: {args.preamble} (최대 {args.timeout_sec:.0f}초)", flush=True)
    try:
        prompt = wait_for_preamble(args.preamble, args.timeout_sec)
    except TimeoutError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    if not args.no_commit_notice:
        prompt += COMMIT_NOTICE

    env = dict(os.environ)
    env["KIMI_CODE_HOME"] = str(args.home)
    cmd = build_command(args.model, prompt)
    print(f"기동: kimi -m {args.model} (지시문 {len(prompt)}자)", flush=True)
    # 인자는 셸을 거치지 않고 그대로 전달되므로 주입 위험이 없습니다. 모델 별칭과
    # 지시문 모두 코디네이터가 만든 값입니다.
    exit_code = run_kimi(cmd, env)

    if args.no_keep_open:
        return exit_code

    print(build_completion_message(exit_code, args.model), end="", flush=True)
    open_interactive_shell(env)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
