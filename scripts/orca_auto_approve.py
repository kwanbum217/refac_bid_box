"""워커 터미널의 권한 프롬프트를 화이트리스트 기반으로 자동 승인합니다.

안전 목록에 없는 명령이나 셸 메타문자, 파괴적 패턴이 보이면 승인하지 않고 stdout 으로 알립니다.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess  # nosec B404  고정된 orca 명령만 실행하며 사용자 입력을 받지 않습니다
import sys
import time

try:
    from scripts.orca_worker_watch import FILE_EDIT_DIALOG_SIGNALS, normalize_text
except ImportError:
    from orca_worker_watch import FILE_EDIT_DIALOG_SIGNALS, normalize_text

SHELL_METACHARS = re.compile(r"[\n\r|<>;`&]|\$\(")

DANGEROUS = re.compile(
    r"rm\s+-rf|git\s+push|git\s+reset\s+--hard|git\s+checkout\s+main|"
    r"DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|UPDATE\s+\w+\s+SET|INSERT\s+INTO|"
    r"docker\s+compose\s+(down|restart|up)|>\s*/dev/sd|chmod\s+777|curl.*-X\s*(POST|PUT|DELETE)",
    re.IGNORECASE,
)

SAFE_STANDALONE_COMMANDS = {
    "cat",
    "diff",
    "echo",
    "grep",
    "head",
    "jq",
    "ls",
    "pytest",
    "rg",
    "tail",
    "wc",
}

SAFE_GIT_SUBCOMMANDS = {
    "diff",
    "log",
    "rev-parse",
    "show",
    "status",
}

GIT_GLOBAL_OPTIONS_WITH_ARG = {
    "-C",
    "-c",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}

GIT_BRANCH_READ_ONLY_FLAGS = {
    "-a",
    "--all",
    "-r",
    "--remotes",
    "-l",
    "--list",
    "--show-current",
    "--contains",
    "--no-contains",
    "--merged",
    "--no-merged",
    "-v",
    "-vv",
    "--verbose",
    "--sort",
    "--points-at",
    "--format",
}

FIND_DANGEROUS_FLAGS = {
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
}


def parse_git_subcommand(args: list[str]) -> tuple[str | None, list[str]]:
    """git 명령어의 글로벌 옵션을 건너뛰고 서브커맨드와 그 이후 인자를 반환합니다."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in GIT_GLOBAL_OPTIONS_WITH_ARG:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, args[i + 1 :]
    return None, []


def is_safe_git_branch(sub_args: list[str]) -> bool:
    """git branch 명령의 인자가 순수 읽기/조회 전용인지 검사합니다."""
    if not sub_args:
        return True
    for a in sub_args:
        if a in GIT_BRANCH_READ_ONLY_FLAGS:
            continue
        if a.startswith("--sort=") or a.startswith("--format=") or a.startswith("--points-at="):
            continue
        return False
    return True


def classify_command(cmd: str) -> tuple[str, str]:
    """명령어 문자열을 분석하여 자동 승인(approve) 또는 보류(hold) 여부와 사유를 반환합니다."""
    if not cmd or not cmd.strip():
        return "hold", "빈 명령"

    # 파일 편집/생성 승인 대화창 신호 검사 (자동 승인하지 않고 보류)
    norm_cmd = normalize_text(cmd)
    for sig in FILE_EDIT_DIALOG_SIGNALS:
        norm_sig = normalize_text(sig)
        if norm_sig == norm_cmd or norm_sig in norm_cmd:
            return "hold", f"파일 편집/생성 승인은 수동 판단 필요 ({sig})"

    # 1. 셸 메타문자 검사 (argv 파싱 전 수행)
    if SHELL_METACHARS.search(cmd):
        return "hold", "셸 메타문자 포함"

    # 2. argv 파싱
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return "hold", "명령 파싱 실패"
    except Exception:
        return "hold", "명령 파싱 실패"

    if not argv:
        return "hold", "빈 명령"

    # 3. 2차 방어선: DANGEROUS 정규식 검사
    if DANGEROUS.search(cmd):
        return "hold", "위험 패턴 감지"

    exe = os.path.basename(argv[0])

    # 4. 정책 테이블 기반 판정
    # 4.1. 단순 읽기 전용 도구
    if exe in SAFE_STANDALONE_COMMANDS:
        return "approve", f"안전한 읽기 전용 명령 ({exe})"

    # 4.2. git 세부 서브커맨드 검사
    if exe == "git":
        subcmd, sub_args = parse_git_subcommand(argv[1:])
        if subcmd is None:
            return "hold", "git 서브커맨드 없음"

        if subcmd in SAFE_GIT_SUBCOMMANDS:
            return "approve", f"안전한 git 서브커맨드 (git {subcmd})"

        if subcmd == "branch":
            if is_safe_git_branch(sub_args):
                return "approve", "안전한 git branch 조회"
            return "hold", "git branch 생성/수정/삭제 명령은 보류"

        if subcmd == "worktree":
            if sub_args and sub_args[0] == "list":
                return "approve", "안전한 git worktree list 조회"
            return "hold", "git worktree 변경 명령은 보류"

        return "hold", f"git 서브커맨드 보류: {subcmd}"

    # 4.3. find 명령어 검사 (-delete, -exec 등 금지)
    if exe == "find":
        if any(arg in FIND_DANGEROUS_FLAGS for arg in argv[1:]):
            return "hold", "find 파괴적 옵션(-delete/-exec 등) 포함"
        return "approve", "안전한 find 검색"

    # 4.4. sed 명령어 검사 (-n 필수, -i 금지)
    if exe == "sed":
        args = argv[1:]
        has_n = "-n" in args or "--quiet" in args or "--silent" in args
        has_inplace = any(
            a == "-i" or a.startswith("-i") or a.startswith("--in-place") for a in args
        )
        if has_n and not has_inplace:
            return "approve", "안전한 sed -n 읽기"
        return "hold", "sed 명령은 -n 옵션(수정 없음)만 허용"

    # 4.5. uv run pytest 검사
    if exe == "uv":
        args = argv[1:]
        if len(args) >= 2 and args[0] == "run" and args[1] == "pytest":
            return "approve", "안전한 uv run pytest 실행"
        return "hold", "uv 명령은 uv run pytest 만 허용"

    # 4.6. 보류 대상 명령 명시적 사유 반환
    if exe in ("python", "python3") or exe.startswith("python3."):
        return "hold", f"{exe} 임의 실행은 보류 대상"
    if exe in ("npm", "npx", "yarn", "pnpm"):
        return "hold", f"{exe} 실행은 보류 대상"
    if exe in ("mv", "cp", "mkdir", "rm", "chmod", "chown", "touch"):
        return "hold", f"{exe} 파일/디렉토리 변경 명령은 보류 대상"
    if exe in ("docker", "docker-compose"):
        return "hold", "docker 실행은 보류 대상"

    # 4.7. 기본값: fail-closed 보류
    return "hold", f"안전목록 밖: {exe}"


def read(handle: str) -> str:
    try:
        # 고정 인자 배열만 넘기고 shell 을 쓰지 않습니다.
        out = subprocess.run(  # nosec B603 B607
            ["orca", "terminal", "read", "--terminal", handle],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return out.stdout
    except Exception:
        return ""


def send(handle: str, text: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["orca", "terminal", "send", "--terminal", handle, "--text", text, "--enter"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def pending_command(screen: str) -> str | None:
    norm_screen = normalize_text(screen)

    # 1. Antigravity 파일 편집/생성 승인 대화창 검사
    for sig in FILE_EDIT_DIALOG_SIGNALS:
        if normalize_text(sig) in norm_screen:
            return sig

    # 2. 기존 도구/명령 실행 승인 프롬프트 검사
    if "Do you want to proceed?" not in screen and "do you want to proceed?" not in norm_screen:
        return None
    marker = "Requesting permission for:"
    if marker not in screen:
        marker_low = "requesting permission for:"
        if marker_low not in norm_screen:
            return ""
        low_screen = screen.lower()
        start_idx = low_screen.find(marker_low) + len(marker_low)
        end_idx = low_screen.find("do you want to proceed?", start_idx)
        return screen[start_idx:end_idx].strip()
    body = screen.split(marker, 1)[1]
    body = body.split("Do you want to proceed?", 1)[0]
    return body.strip()


def poll_loop(terminals: list[str]) -> None:
    seen: dict[str, str] = {}
    while True:
        for h in terminals:
            screen = read(h)
            cmd = pending_command(screen)
            if cmd is None:
                continue
            short = " ".join(cmd.split())[:160]
            verdict, reason = classify_command(cmd)
            if verdict == "approve":
                send(h, "2")
                print(f"[승인] {h[:16]} {short}", flush=True)
                seen.pop(h, None)
                time.sleep(2)
            else:
                if seen.get(h) != short:
                    print(f"[보류] {h[:16]} {reason}: {short}", flush=True)
                    seen[h] = short
        time.sleep(8)


if __name__ == "__main__":
    poll_loop(sys.argv[1:])
