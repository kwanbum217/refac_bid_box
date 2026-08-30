"""워커 터미널의 권한 프롬프트를 화이트리스트 기반으로 자동 승인합니다.

합성 명령은 따옴표 밖 구분자로 파이프라인 구간을 나눠 각 구간을 판정하며, 모든
구간이 승인일 때만 승인합니다. 안전 목록에 없는 명령, 파괴적 패턴, git 전역 옵션,
명령 치환과 프로세스 치환과 히어독, 워크트리 밖 리다이렉트, 비밀 파일 접근은
승인하지 않고 보류합니다.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess  # nosec B404  고정된 orca 명령만 실행하며 사용자 입력을 받지 않습니다
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

try:
    from scripts.orca_worker_watch import FILE_EDIT_DIALOG_SIGNALS, normalize_text
except ImportError:
    from orca_worker_watch import FILE_EDIT_DIALOG_SIGNALS, normalize_text

SHELL_METACHARS = re.compile(r"[\n\r|<>;`&]|\$\(")

# 되돌릴 수 없는 셸 기능. 분해해도 안전을 보장할 수 없으므로 항상 보류합니다.
# 명령 치환과 프로세스 치환은 임의 명령을 숨길 수 있고, 백틱도 마찬가지입니다.
UNSPLITTABLE_METACHARS = re.compile(r"[`]|\$\(|<\(|>\(")

# 파이프라인 구분자. 따옴표 밖에서만 자릅니다. 개행과 캐리지 리턴도 셸에서는
# 명령 구분자이므로 반드시 포함해야 합니다. 빠뜨리면 "git diff\recho x" 가 한
# 구간으로 보여 승인되고 실제로는 두 명령이 실행됩니다.
PIPELINE_SEPARATORS = ("&&", "||", ";", "|", "\n", "\r")

# 리다이렉트 대상으로 허용하는 경로. 워크트리 상대 경로와 임시 디렉터리만 씁니다.
# 절대 경로, 상위 참조, .env, .git 아래는 거부합니다.
REDIRECT_DENY = re.compile(r"^/(?!tmp/|dev/null)|\.\.|(^|/)\.env|(^|/)\.git/")

# 비밀 파일 경로. 읽기 전용 도구라도 화면에 찍히면 노출이므로 인자에서 막습니다.
SECRET_PATH = re.compile(r"(^|/)\.env(\.|$)|(^|/)\.env$|id_rsa|credentials|secrets?\.(json|ya?ml)")

# python 실행 본문에서 보류하는 토큰. 셸 탈출과 파일 삭제 경로입니다.
PYTHON_ESCAPE_TOKENS = re.compile(
    r"\bos\.system\b|\bsubprocess\b|\bshutil\.rmtree\b|\bos\.remove\b|"
    r"\bos\.unlink\b|\bos\.rmdir\b|\bpty\b|\bos\.exec|\beval\s*\(|\bexec\s*\(",
)

DANGEROUS = re.compile(
    r"rm\s+-rf|git\s+push|git\s+reset\s+--hard|git\s+checkout\s+main|"
    r"DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|UPDATE\s+\w+\s+SET|INSERT\s+INTO|"
    r"docker\s+compose\s+(down|restart|up)|>\s*/dev/sd|chmod\s+777|curl.*-X\s*(POST|PUT|DELETE)",
    re.IGNORECASE,
)

# 명령 분류 식별 상수
CATEGORY_READ_ONLY = "read_only"
CATEGORY_TEST_EXECUTION = "test_execution"

SAFE_STANDALONE_COMMANDS = {
    "cat",
    "diff",
    "echo",
    "grep",
    "head",
    "jq",
    "ls",
    "rg",
    "tail",
    "wc",
}

SAFE_TEST_COMMANDS = {
    "pytest",
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

GIT_FORBIDDEN_GLOBAL_OPTIONS = {
    "-C",
    "-c",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
    "--no-pager",
    "--paginate",
    "-p",
    "--bare",
    "--no-replace-objects",
}

# git 서브커맨드별 허용 옵션 화이트리스트
SAFE_GIT_OPTIONS: dict[str, set[str]] = {
    "status": {
        "-s",
        "--short",
        "-b",
        "--branch",
        "-u",
        "--untracked-files",
        "-uno",
        "-unormal",
        "-uall",
        "--untracked-files=no",
        "--untracked-files=normal",
        "--untracked-files=all",
        "--ignored",
        "--ignored=traditional",
        "--ignored=no",
        "--ignored=matching",
        "--porcelain",
        "--porcelain=v1",
        "--porcelain=v2",
        "--porcelain=1",
        "--porcelain=2",
        "-v",
        "-vv",
        "--verbose",
        "--no-ahead-behind",
        "--ahead-behind",
        "--renames",
        "--no-renames",
        "--show-stash",
        "-z",
        "--null",
    },
    "diff": {
        "--stat",
        "--numstat",
        "--shortstat",
        "--summary",
        "--dirstat",
        "--name-only",
        "--name-status",
        "-p",
        "-u",
        "--patch",
        "--no-patch",
        "-s",
        "--no-stat",
        "-w",
        "--ignore-all-space",
        "-b",
        "--ignore-space-change",
        "--ignore-space-at-eol",
        "--ignore-blank-lines",
        "--color",
        "--no-color",
        "--cached",
        "--staged",
        "--word-diff",
        "--check",
        "--quiet",
        "--binary",
        "--exit-code",
        "-z",
        "-R",
        "--relative",
    },
    "log": {
        "--oneline",
        "-n",
        "--max-count",
        "--stat",
        "--shortstat",
        "--name-only",
        "--name-status",
        "-p",
        "-u",
        "--patch",
        "--graph",
        "--decorate",
        "--no-decorate",
        "--all",
        "--branches",
        "--remotes",
        "--tags",
        "--merges",
        "--no-merges",
        "--first-parent",
        "--reverse",
        "--no-color",
        "--color",
        "--follow",
        "--topo-order",
        "--date-order",
        "--author-date-order",
        "-z",
    },
    "show": {
        "--stat",
        "--shortstat",
        "--name-only",
        "--name-status",
        "-s",
        "--no-patch",
        "--oneline",
        "--no-color",
        "--color",
        "--word-diff",
        "-p",
        "-u",
        "--patch",
        "-z",
    },
    "rev-parse": {
        "--show-toplevel",
        "--show-prefix",
        "--show-cdup",
        "--git-dir",
        "--git-path",
        "--is-inside-work-tree",
        "--is-inside-git-dir",
        "--is-bare-repository",
        "--is-shallow-repository",
        "--verify",
        "--short",
        "--abbrev-ref",
        "--symbolic-full-name",
        "--all",
        "--branches",
        "--tags",
        "--remotes",
        "-q",
        "--quiet",
    },
}

SAFE_GIT_OPTION_PREFIXES: dict[str, tuple[str, ...]] = {
    "status": (),
    "diff": (
        "-U",
        "--unified=",
        "--diff-filter=",
        "--word-diff=",
        "--color=",
        "--relative=",
        "--ignore-matching-lines=",
    ),
    "log": (
        "-n",
        "--max-count=",
        "--format=",
        "--pretty=",
        "--date=",
        "--since=",
        "--after=",
        "--until=",
        "--before=",
        "--author=",
        "--committer=",
        "--grep=",
        "--diff-filter=",
        "--color=",
        "--decorate=",
    ),
    "show": ("--format=", "--pretty=", "--color="),
    "rev-parse": ("--short=", "--git-path="),
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

# 비명령 프롬프트 반복 자동 응답 상한 (초과 시 자동 응답 중단 및 사람 개입 로그 기록)
MAX_PROMPT_REPEATS = 3

# 자동 해제 대상 안전한 비명령 프롬프트 화이트리스트
# 각 항목별 전송 키 및 안전 사유:
# 1. cli_satisfaction_survey: "0" 전송 - 단순 CLI 피드백 설문 건너뛰기로 파일/시스템/Git 상태를 변경하지 않아 안전함.
SAFE_NON_COMMAND_PROMPTS: list[dict[str, Any]] = [
    {
        "id": "cli_satisfaction_survey",
        # CLI 만족도 설문 건너뛰기: "0"을 전송하여 설문을 무응답 건너뛰기 처리하며 시스템 및 작업 결과에 부작용 없음
        "keywords": (
            "how's the cli experience so far",
            "[0] skip",
        ),
        "response": "0",
        "description": "CLI 만족도 설문 건너뛰기 ('0' 전송)",
    },
]

# 되돌리기 어렵거나 외부에 영향을 주는 위험한 프롬프트 패턴 (자동 응답 절대 금지 및 사람 개입 로그 기록)
DANGEROUS_PROMPT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "파일 삭제 확인",
        re.compile(
            r"(delete|remove|erase|unlink|destroy)\s+(file|directory|folder|all|database|table|\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        "자격증명/인증 입력",
        re.compile(
            r"(password|passphrase|secret\s*key|api\s*key|access\s*token|credentials?)",
            re.IGNORECASE,
        ),
    ),
    (
        "결제/과금 확인",
        re.compile(
            r"(confirm|process)?\s*(payment|billing|charge|purchase|subscription)",
            re.IGNORECASE,
        ),
    ),
    (
        "원격 반영/배포 확인",
        re.compile(
            r"(push|publish|deploy|release).*(remote|production|prod|master|main|npm|pypi|registry)",
            re.IGNORECASE,
        ),
    ),
    (
        "권한 상승 확인",
        re.compile(
            r"(sudo|root\s*access|elevated\s*privileges?|run\s+as\s+admin)",
            re.IGNORECASE,
        ),
    ),
]


def match_safe_prompt(screen: str) -> dict[str, Any] | None:
    """화면에서 화이트리스트에 등록된 안전한 비명령 프롬프트를 탐색합니다.

    매칭 성공 시 해당 프롬프트 정보 dict를 반환하고, 일치하는 항목이 없으면 None을 반환합니다.
    """
    if not isinstance(screen, str) or not screen:
        return None
    norm_screen = normalize_text(screen)
    for prompt_info in SAFE_NON_COMMAND_PROMPTS:
        keywords = prompt_info.get("keywords", ())
        if keywords and all(kw in norm_screen for kw in keywords):
            return prompt_info
    return None


def check_dangerous_prompt(screen: str) -> str | None:
    """되돌리기 어렵거나 외부 영향이 있는 위험 프롬프트가 화면에 있는지 검사합니다.

    위험 프롬프트 감지 시 사유 문자열을 반환하고, 없으면 None을 반환합니다.
    """
    if not isinstance(screen, str) or not screen:
        return None
    for label, pattern in DANGEROUS_PROMPT_PATTERNS:
        if pattern.search(screen):
            return f"위험 프롬프트 감지 ({label})"
    return None


# 터미널 연속 읽기 실패 허용 상한 (초과 시 감시 대상에서 제외)
MAX_CONSECUTIVE_READ_FAILURES = 5


def get_watcher_pid_path(terminal: str) -> Path:
    """터미널 핸들에 대응하는 PID 파일 경로를 반환합니다."""
    return Path(tempfile.gettempdir()) / "orca_auto_approve" / f"{terminal}.pid"


def get_watcher_log_path(terminal: str) -> Path:
    """터미널 핸들에 대응하는 로그 파일 경로를 반환합니다."""
    return Path(tempfile.gettempdir()) / "orca_auto_approve" / f"{terminal}.log"


def read_watcher_pid(path: Path) -> int | None:
    """PID 파일을 안전하게 읽어 유효한 정수 PID 를 반환합니다. 빈 파일이나 손상된 내용은 None."""
    try:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        pid = int(content)
        return pid if pid > 0 else None
    except Exception:
        return None


def watcher_alive(pid: int | None) -> bool:
    """주어진 PID 프로세스가 실제로 살아 있는지 확인합니다."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def write_watcher_pid(path: Path, pid: int) -> None:
    """PID 파일을 생성하고 PID 를 기록합니다."""
    with suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")


def remove_watcher_pid(path: Path) -> None:
    """PID 파일을 안전하게 삭제합니다."""
    with suppress(OSError):
        if path.exists():
            path.unlink(missing_ok=True)


def parse_git_subcommand(args: list[str]) -> tuple[str | None, list[str]]:
    """git 명령어의 서브커맨드와 그 이후 인자를 반환합니다. 전역 옵션이 선행되면 None 을 반환합니다."""
    if not args:
        return None, []
    if args[0].startswith("-"):
        return None, []
    return args[0], args[1:]


def is_safe_git_subcommand(subcmd: str, sub_args: list[str]) -> tuple[bool, str]:
    """git 서브커맨드 인자가 화이트리스트에 부합하는지 검사합니다."""
    allowed_flags = SAFE_GIT_OPTIONS.get(subcmd, set())
    allowed_prefixes = SAFE_GIT_OPTION_PREFIXES.get(subcmd, ())

    i = 0
    while i < len(sub_args):
        arg = sub_args[i]
        if arg == "--":
            # -- 이후는 모두 파일/경로/리비전 인자로 간주
            break
        if arg.startswith("-"):
            if arg in allowed_flags:
                if (
                    arg in ("-n", "--max-count")
                    and subcmd == "log"
                    and i + 1 < len(sub_args)
                    and not sub_args[i + 1].startswith("-")
                ):
                    i += 1
                i += 1
                continue
            if any(arg.startswith(prefix) for prefix in allowed_prefixes):
                i += 1
                continue
            if subcmd == "log" and re.match(r"^-\d+$", arg):
                i += 1
                continue
            return False, f"허용되지 않은 git {subcmd} 옵션 ({arg})"
        i += 1
    return True, f"안전한 git {subcmd} 명령"


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


def split_pipeline(cmd: str) -> list[str] | None:
    """따옴표 밖의 파이프라인 구분자로 명령을 자릅니다.

    따옴표 안의 구분자는 데이터이므로 자르지 않습니다. 히어독(<<)이 있으면
    본문에 무엇이든 들어올 수 있으므로 자르지 않고 None 을 돌려 상위에서
    별도 처리하게 합니다.
    """
    if "<<" in cmd:
        return None
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        matched = None
        for sep in PIPELINE_SEPARATORS:
            if cmd.startswith(sep, i):
                matched = sep
                break
        if matched:
            segments.append("".join(buf))
            buf = []
            i += len(matched)
            continue
        buf.append(ch)
        i += 1
    if quote:
        return None
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


def strip_redirections(segment: str) -> tuple[str, str | None]:
    """구간 끝의 리다이렉트를 떼어냅니다.

    반환값은 (리다이렉트를 뗀 명령, 거부 사유 또는 None) 입니다. 대상 경로가
    워크트리 밖이거나 .env, .git 아래이면 사유를 돌려줍니다.
    """
    pattern = re.compile(r"\s*(?:\d?>>?|\d?>&\d)\s*([^\s]*)")
    reason: str | None = None
    out = segment
    while True:
        m = pattern.search(out)
        if not m:
            break
        target = m.group(1)
        # 2>&1 처럼 파일 디스크립터끼리 붙이는 형태는 대상이 비어 있습니다.
        if target and not target.isdigit() and REDIRECT_DENY.search(target):
            reason = f"리다이렉트 대상이 허용 범위 밖 ({target})"
        out = out[: m.start()] + out[m.end() :]
    return out.strip(), reason


def classify_python_execution(argv: list[str], raw: str) -> tuple[str, str]:
    """python 실행을 판정합니다.

    워커의 조사와 검증은 거의 전부 python 으로 이뤄지므로 무조건 보류하면
    작업이 멈춥니다. 셸로 빠져나가거나 파일을 지우는 토큰이 없을 때만 승인하고,
    그 밖에는 종전대로 보류합니다.
    """
    if PYTHON_ESCAPE_TOKENS.search(raw):
        return "hold", "python 본문에 셸 탈출/삭제 토큰 포함"
    args = argv[1:]
    if args and args[0] in ("-m", "-c"):
        return "approve", f"python {args[0]} 실행 (탈출 토큰 없음)"
    if args and not args[0].startswith("-"):
        target = args[0]
        if REDIRECT_DENY.search(target):
            return "hold", f"python 실행 대상이 허용 범위 밖 ({target})"
        return "approve", f"python 스크립트 실행 ({target})"
    if not args:
        return "hold", "python 대화형 실행은 보류"
    return "approve", "python 실행 (탈출 토큰 없음)"


def classify_command(cmd: str) -> tuple[str, str]:
    """명령을 파이프라인 구간으로 나눠 각각을 판정합니다.

    종전에는 셸 메타문자가 하나라도 있으면 통째로 보류했습니다. 그 결과 워커의
    조사와 검증 명령이 거의 전부 보류에 걸려 사람이 손으로 풀어 줄 때까지 작업이
    멈췄습니다(2026-08-30 다수 발생).

    구간을 나눠 각각을 기존 규칙으로 판정하면 판정이 느슨해지는 것이 아니라
    정밀해집니다. 모든 구간이 승인일 때만 승인하고 하나라도 보류면 보류합니다.
    되돌릴 수 없는 셸 기능(명령 치환, 프로세스 치환, 백틱)과 히어독은 종전대로
    보류합니다.
    """
    if not cmd or not cmd.strip():
        return "hold", "빈 명령"

    if UNSPLITTABLE_METACHARS.search(cmd):
        return "hold", "명령 치환/프로세스 치환 포함"

    segments = split_pipeline(cmd)
    if segments is None:
        return "hold", "히어독 또는 따옴표 불일치"

    for segment in segments:
        stripped, redirect_reason = strip_redirections(segment)
        if redirect_reason:
            return "hold", redirect_reason
        if not stripped:
            continue
        verdict, reason = classify_segment(stripped)
        if verdict != "approve":
            return verdict, reason

    if len(segments) == 1:
        return classify_segment(strip_redirections(segments[0])[0])
    return "approve", f"파이프라인 {len(segments)}개 구간 전부 승인"


def classify_segment(cmd: str) -> tuple[str, str]:
    """파이프라인 한 구간을 판정합니다. 종전 classify_command 의 본체입니다."""
    if not cmd or not cmd.strip():
        return "hold", "빈 명령"

    # 파일 편집/생성 승인 대화창 신호 검사 (자동 승인하지 않고 보류)
    norm_cmd = normalize_text(cmd)
    for sig in FILE_EDIT_DIALOG_SIGNALS:
        norm_sig = normalize_text(sig)
        if norm_sig == norm_cmd or norm_sig in norm_cmd:
            return "hold", f"파일 편집/생성 승인은 수동 판단 필요 ({sig})"

    # 1. 되돌릴 수 없는 셸 기능만 검사합니다. 파이프와 리다이렉트는 상위
    #    classify_command 가 이미 분해하고 대상 경로를 검증했습니다.
    if UNSPLITTABLE_METACHARS.search(cmd):
        return "hold", "명령 치환/프로세스 치환 포함"

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
    # 4.0. .env 는 어떤 명령으로도 열지 않습니다. AGENTS.md 7장이 실제 값 노출을
    #      금지하며, 읽기 전용 도구라도 화면에 찍히면 노출입니다.
    if any(SECRET_PATH.search(arg) for arg in argv[1:]):
        return "hold", ".env 등 비밀 파일 접근은 보류"

    # 4.1. 단순 읽기 전용 도구
    if exe in SAFE_STANDALONE_COMMANDS:
        return "approve", f"안전한 읽기 전용 명령 ({exe})"

    # 4.1.1. 테스트 코드 실행 검증 명령
    if exe in SAFE_TEST_COMMANDS:
        return "approve", f"신뢰된 워크트리 안의 테스트 코드 실행 검증 ({exe})"

    # 4.2. git 세부 서브커맨드 검사
    if exe == "git":
        git_args = argv[1:]
        if not git_args:
            return "hold", "git 서브커맨드 없음"

        # 전역 옵션 검출: 첫 인자가 '-' 로 시작하면 전역 옵션 사용으로 간주하고 hold
        if git_args[0].startswith("-"):
            opt = git_args[0]
            return "hold", f"git 전역 옵션 사용 금지 ({opt})"

        subcmd, sub_args = parse_git_subcommand(git_args)
        if subcmd is None:
            return "hold", "git 서브커맨드 없음"

        if subcmd in SAFE_GIT_SUBCOMMANDS:
            safe, msg = is_safe_git_subcommand(subcmd, sub_args)
            if safe:
                return "approve", f"안전한 git 서브커맨드 (git {subcmd})"
            return "hold", msg

        if subcmd == "branch":
            if is_safe_git_branch(sub_args):
                return "approve", "안전한 git branch 조회"
            return "hold", "git branch 생성/수정/삭제 명령은 보류"

        if subcmd == "worktree":
            if sub_args and sub_args[0] == "list":
                if len(sub_args) == 1 or (len(sub_args) == 2 and sub_args[1] == "--porcelain"):
                    return "approve", "안전한 git worktree list 조회"
                return "hold", "git worktree list 에 허용되지 않은 옵션"
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
            return "approve", "신뢰된 워크트리 안의 테스트 코드 실행 검증 (uv run pytest)"
        return "hold", "uv 명령은 uv run pytest 만 허용"

    # 4.6. 보류 대상 명령 명시적 사유 반환
    if exe in ("python", "python3") or exe.startswith("python3."):
        return classify_python_execution(argv, cmd)
    if exe in ("npm", "npx", "yarn", "pnpm"):
        return "hold", f"{exe} 실행은 보류 대상"
    if exe in ("mv", "cp", "mkdir", "rm", "chmod", "chown", "touch"):
        return "hold", f"{exe} 파일/디렉토리 변경 명령은 보류 대상"
    if exe in ("docker", "docker-compose"):
        return "hold", "docker 실행은 보류 대상"

    # 4.7. 기본값: fail-closed 보류
    return "hold", f"안전목록 밖: {exe}"


def read(handle: str) -> str | None:
    """orca terminal read 로 터미널 화면을 읽습니다. 실패 시 None 을 반환합니다."""
    try:
        out = subprocess.run(  # nosec B603 B607
            ["orca", "terminal", "read", "--terminal", handle],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if out.returncode != 0:
            return None
        return out.stdout
    except Exception:
        return None


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


def poll_loop(terminals: list[str], max_failures: int = MAX_CONSECUTIVE_READ_FAILURES) -> None:
    """터미널 목록을 순회하며 권한 대화창 및 안전한 비명령 프롬프트를 자동 승인/해제합니다. 감시 대상이 모두 소진되면 종료합니다."""
    try:
        active = list(terminals)
        fail_counts: dict[str, int] = dict.fromkeys(active, 0)
        seen_cmds: dict[str, str] = {}
        prompt_repeat_counts: dict[tuple[str, str], int] = {}
        seen_prompts: dict[str, str] = {}
        while active:
            for h in list(active):
                screen = read(h)
                if screen is None:
                    fail_counts[h] = fail_counts.get(h, 0) + 1
                    if fail_counts[h] >= max_failures:
                        active.remove(h)
                    continue
                fail_counts[h] = 0

                cmd = pending_command(screen)
                if cmd is not None:
                    short = " ".join(cmd.split())[:160]
                    verdict, reason = classify_command(cmd)
                    if verdict == "approve":
                        send(h, "2")
                        print(f"[승인] {h[:16]} {short}", flush=True)
                        seen_cmds.pop(h, None)
                        time.sleep(2)
                    else:
                        if seen_cmds.get(h) != short:
                            print(f"[보류] {h[:16]} {reason}: {short}", flush=True)
                            seen_cmds[h] = short
                    continue

                # 비명령 프롬프트 판정 계층 (명령 승인과는 별도 경로)
                safe_prompt = match_safe_prompt(screen)
                if safe_prompt is not None:
                    prompt_id = safe_prompt["id"]
                    resp = str(safe_prompt["response"])
                    desc = safe_prompt.get("description", prompt_id)
                    key = (h, prompt_id)
                    current_count = prompt_repeat_counts.get(key, 0)

                    if current_count >= MAX_PROMPT_REPEATS:
                        if seen_prompts.get(h) != f"limit_{prompt_id}":
                            print(
                                f"[경고] {h[:16]} 프롬프트 반복 상한({MAX_PROMPT_REPEATS}회) 초과로 자동 응답 중단: {prompt_id} (사람 개입 필요)",
                                flush=True,
                            )
                            seen_prompts[h] = f"limit_{prompt_id}"
                    else:
                        prompt_repeat_counts[key] = current_count + 1
                        send(h, resp)
                        print(
                            f"[자동해제] {h[:16]} 비명령 프롬프트 '{prompt_id}' 응답 '{resp}' 전송 ({desc}, 시도 {prompt_repeat_counts[key]}/{MAX_PROMPT_REPEATS})",
                            flush=True,
                        )
                        seen_prompts[h] = f"answered_{prompt_id}"
                        time.sleep(2)
                    continue

                # 안전 비명령 프롬프트가 해제되었거나 감지되지 않으면 카운트 및 상태 초기화
                for k in list(prompt_repeat_counts.keys()):
                    if k[0] == h:
                        prompt_repeat_counts.pop(k, None)
                if seen_prompts.get(h, "").startswith("answered_") or seen_prompts.get(
                    h, ""
                ).startswith("limit_"):
                    seen_prompts.pop(h, None)

                # 위험 프롬프트 감지 검사 (자동 응답 금지, 사람 개입 보류 로그 기록)
                danger_reason = check_dangerous_prompt(screen)
                if danger_reason:
                    if seen_prompts.get(h) != f"danger_{danger_reason}":
                        print(
                            f"[보류] {h[:16]} {danger_reason}: 자동 응답하지 않고 사람에게 보류",
                            flush=True,
                        )
                        seen_prompts[h] = f"danger_{danger_reason}"
                else:
                    if seen_prompts.get(h, "").startswith("danger_"):
                        seen_prompts.pop(h, None)

            if active:
                time.sleep(8)
    finally:
        for h in terminals:
            remove_watcher_pid(get_watcher_pid_path(h))


if __name__ == "__main__":
    poll_loop(sys.argv[1:])
