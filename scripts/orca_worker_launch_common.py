"""Orca 워커 런처(agy, kimi, qwen)에서 공유하는 권한 자동 승인 준비 공통 로직.

런처 경로로 워커를 띄우면 orca_taskctl.py dispatch 를 거치지 않아 권한 자동
승인 4단계가 통째로 빠집니다. 각 런처는 exec 또는 CLI 실행 전에 분리된 자식을
띄워 이 모듈의 준비 로직을 수행합니다.

주요 불변식:
1. 반드시 prepare_worker_terminal(terminal, cli_type=..., model=..., launcher=...)
   을 통째로 호출합니다 (start_auto_approve, enable_file_edit_auto_approve 직접 호출 금지).
2. force_file_edit 은 사용하지 않습니다.
3. antigravity 워커의 경우 file_edit_auto_approve.ok 가 True 여야만 준비 완료로
   판정합니다 (최상위 ok 는 파일 편집 실패 시에도 True 일 수 있으므로 판정 기준으로 쓰지 않음).
4. 자식 프로세스는 start_new_session=True 로 분리되어 부모 프로세스의 exec 이후에도
   독립적으로 동작합니다.
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404 - 자기 자신(런처 스크립트)을 고정 인자로만 재호출합니다
import sys
import time
from pathlib import Path
from typing import Any

# agy TUI 가 상태줄을 그리기 전에 키를 보내면 모드 판정이 unknown 이 되어
# 아무것도 확보하지 못합니다. 첫 시도를 이만큼 미룹니다.
PERMISSION_SETUP_DELAY_SEC = 10.0
# 워커가 긴 생성 중이면 화면이 스피너뿐이라 모드를 읽을 수 없습니다. 그동안은
# 키를 보내지 않고 기다려야 하므로 확보 시도 창을 넉넉히 잡습니다.
PERMISSION_SETUP_DEADLINE_SEC = 600.0
PERMISSION_SETUP_INTERVAL_SEC = 15.0
PERMISSION_SETUP_FLAG = "--setup-permissions"

COMMIT_NOTICE = (
    "\n\n추가 지시: 작업을 마치면 반드시 변경 파일을 스테이징하고 커밋하십시오. "
    "git add -A 는 쓰지 마십시오. 커밋 없이 완료를 선언하면 계약 위반입니다. "
    "커밋 후 git log --oneline main..HEAD 로 확인하고 해시를 보고하십시오."
)

REVIEWER_NOTICE = (
    "\n\n추가 지시: 리뷰어는 소스 코드를 수정하지 않으며 커밋이나 git add 를 절대 수행하지 마십시오. "
    ".orca/ 아래 review_done.json 은 검토 산출물이므로 gitignore 대상이며 커밋하지 않습니다. "
    "검토를 마치면 review_done.json 작성과 orca orchestration send --type worker_done 전송을 "
    "둘 다 마쳐야 완료입니다."
)


DEFAULT_PREAMBLE = Path(".orca/preamble.txt")


def wait_for_preamble(path: Path, timeout_sec: float, poll_sec: float = 1.0) -> str:
    """고유한 파일명의 preamble 이 나타나 내용이 채워질 때까지 기다리고 소비(삭제)합니다.

    1. 기본 경로(.orca/preamble.txt) 또는 디렉터리로 대기 중일 때:
       - 워크트리 .orca 디렉터리 내에서 preamble_*.txt 고유 파일을 찾아 읽고 즉시 삭제합니다.
       - 후보가 둘 이상이면 어느 것도 소비하지 않고 남아있는 파일 목록을 출력한 뒤 거부합니다.
       - 고유 preamble 없이 옛 형태의 고정 .orca/preamble.txt 만 남아있으면 격리 파손 위험으로 거부합니다.
    2. 명시적 파일 경로로 대기 중일 때:
       - 해당 파일이 나타나 내용이 채워질 때까지 기다립니다.
       - preamble_*.txt 파일인 경우 소비 후 즉시 삭제합니다.
       - 동일 디렉터리에 preamble_*.txt 후보가 둘 이상이면 거부합니다.
    """
    path = Path(path)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        # 1. path 가 기본 경로이거나 디렉터리인 경우: .orca 내 고유 preamble 감지
        if path == DEFAULT_PREAMBLE or path.is_dir() or not path.exists():
            search_dir = path if path.is_dir() else path.parent
            if search_dir.exists():
                candidates = sorted(search_dir.glob("preamble_*.txt"))
                if len(candidates) > 1:
                    remaining = [c.name for c in candidates]
                    sys.stderr.write(
                        f"오류: 워크트리({search_dir})에 둘 이상의 preamble 후보가 발견되었습니다: {remaining}. "
                        "시도 단위 격리가 성립하지 않으므로 어느 것도 소비하지 않고 기동을 거부합니다.\n"
                    )
                    raise ValueError(
                        f"다중 preamble 후보 발견 ({len(candidates)}개): {remaining}. "
                        "시도 단위 격리가 성립하지 않으므로 어느 것도 소비하지 않고 기동을 거부합니다."
                    )
                elif len(candidates) == 1:
                    chosen = candidates[0]
                    text = chosen.read_text(encoding="utf-8").strip()
                    if text:
                        chosen.unlink(missing_ok=True)
                        print(f"preamble 소비 완료 ({chosen.name}): {len(text)}자", flush=True)
                        return text
                elif (search_dir / "preamble.txt").exists() and (
                    path == DEFAULT_PREAMBLE or path.name == "preamble.txt"
                ):
                    sys.stderr.write(
                        f"오류: 옛 형태의 고정 preamble({search_dir / 'preamble.txt'})이 발견되었습니다. "
                        "이전 지시문 격리 파손 위험으로 기동을 거부합니다. 해당 파일을 삭제하고 고유 preamble 로 재기동하십시오.\n"
                    )
                    raise ValueError(f"옛 형태의 고정 preamble 발견: {search_dir / 'preamble.txt'}")

        # 2. 명시된 path 가 직접 존재하는 경우
        if path.is_file() and path.exists():
            if path.name.startswith("preamble_"):
                candidates = sorted(path.parent.glob("preamble_*.txt"))
                if len(candidates) > 1:
                    remaining = [c.name for c in candidates]
                    sys.stderr.write(
                        f"오류: 워크트리({path.parent})에 둘 이상의 preamble 후보가 발견되었습니다: {remaining}. "
                        "시도 단위 격리가 성립하지 않으므로 어느 것도 소비하지 않고 기동을 거부합니다.\n"
                    )
                    raise ValueError(
                        f"다중 preamble 후보 발견 ({len(candidates)}개): {remaining}. "
                        "시도 단위 격리가 성립하지 않으므로 어느 것도 소비하지 않고 기동을 거부합니다."
                    )
            text = path.read_text(encoding="utf-8").strip()
            if text:
                if path.name.startswith("preamble_"):
                    path.unlink(missing_ok=True)
                    print(f"preamble 소비 완료 ({path.name}): {len(text)}자", flush=True)
                return text

        time.sleep(poll_sec)
    raise TimeoutError(f"preamble 파일을 {timeout_sec:.0f}초 안에 받지 못했습니다: {path}")


ROLE_MARKER_PREFIX = "[ORCA_ROLE: "
ROLE_MARKER_BUILDER = "[ORCA_ROLE: builder]"
ROLE_MARKER_REVIEWER = "[ORCA_ROLE: reviewer]"

_ROLE_MARKER_RE = re.compile(
    r"^[ \t]*\[?[ \t]*ORCA_ROLE:[ \t]*(builder|reviewer)[ \t]*\]?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def format_role_marker(role: str) -> str:
    """역할 표지 한 줄을 생성합니다.

    사람이 읽어도 무해하고 기계가 정확히 매칭할 수 있는 독립된 한 줄 표지입니다.
    값은 'builder' 또는 'reviewer' 로 한정합니다.
    """
    normalized = (role or "").strip().lower()
    if normalized not in ("builder", "reviewer"):
        normalized = "builder"
    return f"[ORCA_ROLE: {normalized}]"


def parse_role_marker(text: str) -> str | None:
    """텍스트에서 독립된 한 줄의 역할 표지를 추출합니다.

    표지가 발견되면 'builder' 또는 'reviewer' 를 반환하고, 없으면 None 을 반환합니다.
    """
    if not text:
        return None
    match = _ROLE_MARKER_RE.search(text)
    if match:
        return match.group(1).lower()
    return None


def inject_role_marker(preamble: str, role: str) -> str:
    """preamble 텍스트에 독립된 한 줄로 역할 표지를 기록합니다.

    이미 표지가 있으면 덮어쓰고, 없으면 맨 앞에 추가합니다.
    """
    marker = format_role_marker(role)
    if not preamble:
        return marker
    existing = parse_role_marker(preamble)
    if existing:
        return _ROLE_MARKER_RE.sub(marker, preamble, count=1)
    return f"{marker}\n\n{preamble}"


def detect_role(prompt: str) -> str:
    """지시문 텍스트에서 역할을 판정합니다.

    1. 표지(role marker)를 최우선 근거로 삼습니다 (builder 또는 reviewer).
    2. 표지가 없으면 종전 문자열 판정(ORCA_REVIEW_DONE_V2, review_done.json, role: reviewer)으로 물러섭니다.
    3. 그래도 확정할 수 없으면 builder 로 판정합니다 (fail-closed).
    """
    if not prompt:
        return "builder"
    marker = parse_role_marker(prompt)
    if marker:
        return marker
    if (
        "ORCA_REVIEW_DONE_V2" in prompt
        or "review_done.json" in prompt
        or 'role: "reviewer"' in prompt
        or "role: reviewer" in prompt
    ):
        return "reviewer"
    return "builder"


def resolve_notice(role: str = "auto", prompt: str = "") -> str:
    """역할과 지시문 텍스트를 바탕으로 첨부할 고지문 문자열을 돌려줍니다.

    role 이 auto 이면 detect_role 로 판정합니다.
    reviewer 로 판정되거나 지정되면 REVIEWER_NOTICE 를,
    그 외(builder 또는 판정 불가)는 COMMIT_NOTICE 를 돌려줍니다.
    """
    normalized_role = role.strip().lower() if role else "auto"
    if normalized_role == "auto":
        normalized_role = detect_role(prompt)

    if normalized_role == "reviewer":
        return REVIEWER_NOTICE
    return COMMIT_NOTICE


def append_role_notice(
    prompt: str,
    *,
    role: str = "auto",
    no_commit_notice: bool = False,
) -> str:
    """고지문 설정에 따라 prompt 에 적절한 고지문을 덧붙입니다.

    no_commit_notice 가 True 이면 역할과 무관하게 어떤 고지문도 붙이지 않습니다.
    """
    if no_commit_notice:
        return prompt
    return prompt + resolve_notice(role=role, prompt=prompt)


def _load_prepare_worker():
    """orca_taskctl 의 준비 상태 기계를 지연 로드합니다.

    런처는 워크트리 안에서 실행되므로 저장소 루트를 sys.path 에 넣어야 합니다.
    """
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.orca_taskctl import prepare_worker_terminal

    return prepare_worker_terminal


def is_terminal_ready(result: dict[str, Any], cli_type: str) -> bool:
    """prepare_worker_terminal 반환값에서 준비 완료 여부를 엄격하게 판정합니다.

    prepare_worker_terminal 은 파일 편집 모드 전환이 실패(skipped_or_failed)해도
    최상위 ok 를 True 로 반환합니다. 따라서 antigravity CLI 에서는 최상위 ok 가 아닌
    반드시 file_edit_auto_approve.ok 가 True 인 경우에만 준비 완료로 판정합니다.
    kimi, qwen 등 shift+tab 을 지원하지 않는 CLI 는 감시기 기동 및 신뢰 대화창 처리 상태를
    기준으로 판정합니다.
    """
    if not isinstance(result, dict):
        return False
    if cli_type in ("antigravity", "agy"):
        file_edit = result.get("file_edit_auto_approve")
        if isinstance(file_edit, dict):
            return bool(file_edit.get("ok"))
        return False

    auto_approve = result.get("auto_approve_watcher")
    trust = result.get("trust_prompt")
    if isinstance(auto_approve, dict):
        trust_ok = True
        if isinstance(trust, dict):
            trust_ok = trust.get("status") != "still_present"
        return bool(auto_approve.get("ok")) and trust_ok
    return bool(result.get("ok"))


def acquire_permissions(
    terminal: str,
    model: str,
    *,
    cli_type: str,
    launcher: str | None = None,
    delay_sec: float = PERMISSION_SETUP_DELAY_SEC,
    deadline_sec: float = PERMISSION_SETUP_DEADLINE_SEC,
    interval_sec: float = PERMISSION_SETUP_INTERVAL_SEC,
    sleep=time.sleep,
    prepare=None,
) -> tuple[bool, str]:
    """워커 기동 뒤 워커 준비 4단계를 수행합니다.

    prepare_worker_terminal 을 통째로 부르는 것이 중요합니다. 감시기 부착과
    모드 전환 헬퍼만 직접 부르면 CLI 종류 메타데이터가 기록되지 않고,
    그 메타데이터로 CLI 를 판정하는 classify_file_edit_auto_approve_support
    가 fail-closed 로 막혀 accept-edits 를 영영 확보하지 못합니다.

    force_file_edit 은 쓰지 않습니다. 화면이 스피너면 모드가 unknown 으로
    읽히는데 그때 키를 보내면 순환이 accept-edits 를 지나 plan 으로 넘어가
    워커가 파일을 아예 못 고칩니다. 판정 불가일 때는 보내지 않고 다음 주기를
    기다립니다.

    성공 판정은 최상위 ok 가 아닌 CLI 별 준비 완료 상태(antigravity 의 경우
    file_edit_auto_approve.ok == True)를 기준으로 수행합니다.
    """
    prepare_worker_terminal = prepare or _load_prepare_worker()

    sleep(delay_sec)
    deadline = time.monotonic() + deadline_sec
    last: dict[str, Any] = {}
    while True:
        last = prepare_worker_terminal(
            terminal,
            cli_type=cli_type,
            model=model,
            launcher=launcher
            or str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        )
        if is_terminal_ready(last, cli_type):
            return True, f"준비 완료: {last}"
        if time.monotonic() >= deadline:
            break
        sleep(interval_sec)

    return False, (f"워커 준비를 {deadline_sec:.0f}초 안에 마치지 못했습니다. 마지막 상태: {last}")


def spawn_permission_setup(
    launcher_script: str | Path,
    terminal: str,
    model: str,
    *,
    log_path: Path = Path(".orca/permission_setup.log"),
    popen=subprocess.Popen,
) -> Any:
    """승인 설정을 분리된 자식으로 넘깁니다.

    부모는 곧바로 CLI 를 exec 하거나 실행하여 제어권을 넘기므로 여기서 기다릴 수 없습니다.
    자식은 자기 세션(start_new_session=True)으로 떨어져 나가 CLI TUI 가 뜬 뒤에 일을 합니다.
    """
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", encoding="utf-8")
    except OSError:
        handle = subprocess.DEVNULL
    try:
        return popen(
            [
                sys.executable,
                str(Path(launcher_script).resolve()),
                PERMISSION_SETUP_FLAG,
                terminal,
                model,
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        # 자식이 자기 복제본을 갖고 떠나므로 부모 쪽 핸들은 남겨 둘 이유가 없습니다.
        # 닫지 않으면 ResourceWarning("unclosed file") 이 테스트마다 쌓입니다.
        if handle is not subprocess.DEVNULL:
            handle.close()


def run_permission_setup_child(
    raw_args: list[str],
    *,
    cli_type: str,
    launcher: str | None = None,
    acquire_fn=acquire_permissions,
    stderr=None,
    stdout=None,
) -> int:
    """--setup-permissions 자식 모드 인자를 검증하고 acquire_permissions 를 실행합니다.

    인자가 부족하거나 비어 있으면 종료 코드 2 를 반환합니다.
    준비 성공 시 0, 실패 시 1 을 반환합니다.
    """
    err_stream = sys.stderr if stderr is None else stderr
    out_stream = sys.stdout if stdout is None else stdout

    if len(raw_args) < 3 or not raw_args[1].strip() or not raw_args[2].strip():
        err_stream.write(
            f"오류: {PERMISSION_SETUP_FLAG} 에는 터미널 핸들과 모델 ID 가 필요합니다\n"
        )
        if hasattr(err_stream, "flush"):
            err_stream.flush()
        return 2
    terminal = raw_args[1].strip()
    model = raw_args[2].strip()
    ok, detail = acquire_fn(
        terminal,
        model,
        cli_type=cli_type,
        launcher=launcher,
    )
    status_label = "확보" if ok else "실패"
    out_stream.write(f"[권한설정] {status_label}: {detail}\n")
    if hasattr(out_stream, "flush"):
        out_stream.flush()
    return 0 if ok else 1


def schedule_permission_setup(
    launcher_script: str | Path,
    model: str,
    *,
    terminal: str | None = None,
    spawn_fn=spawn_permission_setup,
    stderr=None,
    stdout=None,
) -> bool:
    """ORCA_TERMINAL_HANDLE 환경변수 또는 전달된 터미널 핸들을 확인하여 자식 프로세스를 예약합니다.

    터미널 핸들이 없으면 stderr 에 경고를 출력하고 False 를 반환합니다.
    """
    err_stream = sys.stderr if stderr is None else stderr
    out_stream = sys.stdout if stdout is None else stdout

    handle = (
        terminal if terminal is not None else os.environ.get("ORCA_TERMINAL_HANDLE", "")
    ).strip()
    if handle:
        spawn_fn(launcher_script, handle, model)
        out_stream.write(f"권한 설정 예약: {handle} (.orca/permission_setup.log)\n")
        if hasattr(out_stream, "flush"):
            out_stream.flush()
        return True
    err_stream.write(
        "경고: ORCA_TERMINAL_HANDLE 이 없어 권한 자동 승인을 걸지 못했습니다. "
        "코디네이터가 orca_taskctl.py prepare-worker 를 직접 실행해야 합니다\n"
    )
    if hasattr(err_stream, "flush"):
        err_stream.flush()
    return False
