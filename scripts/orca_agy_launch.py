"""Antigravity(agy) 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

Antigravity TUI 는 `orca terminal create --command "agy --model <id>"` 로 띄우면
스플래시에서 멈추는 사례가 반복됐습니다. 지시문을 런치 인자(`-i`)로 넘겨 기동하면
안정적이지만, 지시문(preamble)은 Dispatch 이후에야 얻을 수 있어서 순서가 맞지
않았습니다. 이 런처가 그 순서를 뒤집습니다. 터미널을 **런처를 명령으로 지정해**
먼저 만들고, 런처는 preamble 파일이 나타날 때까지 기다렸다가 agy 를 exec 합니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_agy_launch.py --model gemini-3.8-flash-medium"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
    # 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 쓰면 런처가 이어받습니다

이 경로는 `orca_taskctl.py dispatch` 를 거치지 않으므로 그 안에 있는 권한 자동
승인 4단계가 통째로 빠집니다. 그래서 워커가 파일 편집 대화창마다 멈추고 사람이
직접 승인하게 됩니다. 런처가 그 단계를 스스로 수행해 절차를 기억할 필요를
없앱니다. `exec` 로 자리를 내주기 전에 분리된 자식을 띄우고, 자식이 agy TUI 가
뜬 뒤 accept-edits 모드와 셸 명령 감시기를 확보합니다.
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - 자기 자신을 sys.executable 로 고정 인자로만 재호출합니다
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import orca_worker_launch_common as common  # noqa: E402

PERMISSION_SETUP_DEADLINE_SEC = common.PERMISSION_SETUP_DEADLINE_SEC
PERMISSION_SETUP_DELAY_SEC = common.PERMISSION_SETUP_DELAY_SEC
PERMISSION_SETUP_FLAG = common.PERMISSION_SETUP_FLAG
PERMISSION_SETUP_INTERVAL_SEC = common.PERMISSION_SETUP_INTERVAL_SEC

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
    --mode accept-edits 를 시작 인자로 넣어 TUI 가 첫 프롬프트를 받기 전에 편집
    모드를 확정합니다. 이렇게 하지 않으면 스피너 화면에서 shift+tab 전환을
    시도하는 경쟁 조건이 생겨 첫 편집 대화창보다 모드 확신이 늦어집니다.
    """
    return ["agy", "--model", model, "--mode", "accept-edits", "-i", prompt]


def acquire_permissions(
    terminal: str,
    model: str,
    *,
    cli_type: str = "antigravity",
    launcher: str | None = None,
    delay_sec: float = PERMISSION_SETUP_DELAY_SEC,
    deadline_sec: float = PERMISSION_SETUP_DEADLINE_SEC,
    interval_sec: float = PERMISSION_SETUP_INTERVAL_SEC,
    sleep=time.sleep,
    prepare=None,
) -> tuple[bool, str]:
    """agy 기동 뒤 워커 준비 4단계를 수행합니다.

    prepare_worker_terminal 을 통째로 부르는 것이 중요합니다. 감시기 부착과
    모드 전환 헬퍼만 직접 부르면 CLI 종류 메타데이터가 기록되지 않고,
    그 메타데이터로 CLI 를 판정하는 classify_file_edit_auto_approve_support
    가 fail-closed 로 막혀 accept-edits 를 영영 확보하지 못합니다. 2026-08-31
    에 이 방식으로 워커가 파일 편집 대화창에 그대로 갇혔습니다.

    force_file_edit 은 쓰지 않습니다. 화면이 스피너면 모드가 unknown 으로
    읽히는데 그때 키를 보내면 순환이 accept-edits 를 지나 plan 으로 넘어가
    워커가 파일을 아예 못 고칩니다. 판정 불가일 때는 보내지 않고 다음 주기를
    기다립니다.

    cli_type 과 launcher 를 키워드로 받는 이유는 이 함수가 acquire_fn 으로
    common.run_permission_setup_child 에 넘겨지기 때문입니다. 그쪽은 항상 두
    값을 키워드로 전달하므로 받지 않으면 TypeError 로 자식이 즉시 죽고,
    부모는 이미 exec 로 사라진 뒤라 아무도 실패를 보지 못합니다. 2026-08-31
    에 이 형태로 승인 자동화가 통째로 동작하지 않았습니다.
    """
    return common.acquire_permissions(
        terminal,
        model,
        cli_type=cli_type,
        launcher=launcher or str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        delay_sec=delay_sec,
        deadline_sec=deadline_sec,
        interval_sec=interval_sec,
        sleep=sleep,
        prepare=prepare,
    )


def spawn_permission_setup(terminal: str, model: str, *, popen=subprocess.Popen) -> None:
    """승인 설정을 분리된 자식으로 넘깁니다.

    부모는 곧바로 agy 를 exec 해서 사라지므로 여기서 기다릴 수 없습니다. 자식은
    자기 세션으로 떨어져 나가 agy TUI 가 뜬 뒤에 일을 합니다.
    """
    common.spawn_permission_setup(
        Path(__file__).resolve(),
        terminal,
        model,
        popen=popen,
    )


def main(argv: list[str] | None = None) -> int:
    # 자식 모드: 부모가 exec 로 사라진 뒤 승인 설정만 수행합니다. argparse 앞에서
    # 갈라내야 런처 인자 규약을 건드리지 않습니다.
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == PERMISSION_SETUP_FLAG:
        return common.run_permission_setup_child(
            raw,
            cli_type="antigravity",
            launcher=str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
            acquire_fn=acquire_permissions,
        )

    parser = argparse.ArgumentParser(description="Antigravity 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="Antigravity 모델 ID (예: gemini-3.8-flash-medium, claude-sonnet-4-6)",
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

    # 이 런처 경로는 taskctl dispatch 를 거치지 않아 권한 자동 승인 4단계가
    # 빠집니다. 코디네이터가 prepare-worker 를 따로 부르는 것을 잊으면 워커가
    # 파일 편집 대화창마다 멈추고 사람이 손으로 승인하게 됩니다. 기억에 의존하지
    # 않도록 런처가 직접 겁니다.
    common.schedule_permission_setup(
        Path(__file__).resolve(),
        args.model,
        spawn_fn=lambda script, term, model: spawn_permission_setup(term, model),
    )

    print(f"기동: agy --model {args.model} (지시문 {len(prompt)}자)", flush=True)
    # 인자는 셸을 거치지 않고 그대로 전달되므로 주입 위험이 없습니다. 모델 ID 와
    # 지시문 모두 코디네이터가 만든 값입니다.
    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # nosec B606
    return 0  # execvpe 가 성공하면 여기에 도달하지 않습니다.


if __name__ == "__main__":
    raise SystemExit(main())
