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

import json
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
    "커밋 후 git log --oneline main..HEAD 로 확인하고 해시를 보고하십시오. "
    "전량 시험과 긴 명령은 배경(& 또는 run_in_background)으로 돌리지 말고 앞에서 실행해 "
    "끝까지 기다리십시오. 배경 작업의 완료 알림은 오지 않으므로, 결과를 기다리겠다며 턴을 "
    "끝내면 작업이 멈춥니다. 같은 턴에 커밋·보고서·worker_done 까지 마치십시오. "
    "보고서를 쓰기 직전, 마지막 코드·문서 수정 뒤에 전량 시험을 다시 한 번 돌리고 그 출력의 "
    "passed 건수를 verification 에 그대로 적으십시오. 수정 뒤 대상 시험만 다시 돌리고 이전 "
    "전량 건수를 적으면 Level 1 게이트 6 이 건수 불일치로 막습니다. "
    "같은 세션에서 큰 파일을 여러 번 열어 컨텍스트가 커졌다면, 구현을 마친 뒤 보고서 작성 전에 "
    "불필요한 재열람을 하지 말고 이미 얻은 결과로 바로 마무리하십시오."
)

REVIEWER_NOTICE = (
    "\n\n추가 지시: 리뷰어는 소스 코드를 수정하지 않으며 커밋이나 git add 를 절대 수행하지 마십시오. "
    ".orca/ 아래 review_done.json 은 검토 산출물이므로 gitignore 대상이며 커밋하지 않습니다. "
    "전량 시험과 긴 명령은 배경으로 돌리지 말고 앞에서 실행해 끝까지 기다리십시오. "
    "결과를 기다리겠다며 턴을 끝내면 작업이 멈추므로 같은 턴에 review_done.json 작성과 "
    "worker_done 전송까지 마치십시오. "
    "검토를 마치면 review_done.json 작성과 orca orchestration send --type worker_done 전송을 "
    "둘 다 마쳐야 완료입니다."
)


DEFAULT_PREAMBLE = Path(".orca/preamble.txt")

WORKER_HANDLE_ENV_VAR = "ORCA_TERMINAL_HANDLE"
WORKER_HANDLE_SUFFIX = ".handle"
WORKER_HANDLE_PREFIX = "term_"


def worker_handle_path(preamble_path: Path) -> Path:
    """preamble 과 같은 nonce 를 공유하는 워커 핸들 파일 경로를 돌려줍니다.

    taskctl 이 preamble 을 쓰기 직전에 이 경로에 워커 터미널 핸들을 기록합니다.
    preamble 이름이 `preamble_<task>_<dispatch>_<nonce>.txt` 이므로 핸들 파일은
    `preamble_<task>_<dispatch>_<nonce>.handle` 이 되어 다른 시도의 값과 섞이지 않습니다.
    """
    path = Path(preamble_path)
    return path.with_name(path.stem + WORKER_HANDLE_SUFFIX)


def write_worker_handle(preamble_path: Path, handle: str | None) -> Path | None:
    """워커 핸들을 preamble 옆 파일에 기록합니다. 핸들이 비었거나 쓰기에 실패하면 None."""
    text = (handle or "").strip()
    if not text:
        return None
    target = worker_handle_path(preamble_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    except OSError:
        return None
    return target


def read_worker_handle(preamble_path: Path) -> str:
    """preamble 옆 핸들 파일을 읽고 즉시 삭제합니다. 없거나 형식이 틀리면 빈 문자열."""
    target = worker_handle_path(preamble_path)
    try:
        text = target.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    finally:
        target.unlink(missing_ok=True)
    if not text.startswith(WORKER_HANDLE_PREFIX):
        return ""
    return text


def apply_worker_handle(
    env: dict[str, str],
    handle: str,
    *,
    stderr=None,
) -> dict[str, str]:
    """에이전트 환경의 ORCA_TERMINAL_HANDLE 을 워커 자기 터미널 핸들로 확정합니다.

    상속된 값은 신뢰하지 않습니다. 런처는 코디네이터 셸에서 기동되므로 부모 환경에
    코디네이터 핸들이 남아 있을 수 있고, 그 값이 에이전트로 넘어가면 worker_done 과
    escalation 이 'not the exact process that owns Dispatch' 로 거부됩니다.
    워커 핸들을 알면 그 값으로 덮어쓰고, 모르면 상속값을 비운 뒤 경고를 남깁니다.
    """
    resolved = dict(env)
    worker = (handle or "").strip()
    inherited = resolved.get(WORKER_HANDLE_ENV_VAR, "")
    if worker:
        if inherited and inherited != worker:
            stream = sys.stderr if stderr is None else stderr
            stream.write(
                f"안내: 상속된 ORCA_TERMINAL_HANDLE({inherited}) 을 "
                f"워커 핸들({worker})로 교체합니다\n"
            )
            if hasattr(stream, "flush"):
                stream.flush()
        resolved[WORKER_HANDLE_ENV_VAR] = worker
        return resolved

    resolved.pop(WORKER_HANDLE_ENV_VAR, None)
    if inherited:
        stream = sys.stderr if stderr is None else stderr
        stream.write(
            f"경고: 워커 터미널 핸들을 확인하지 못해 상속된 "
            f"ORCA_TERMINAL_HANDLE({inherited}) 을 비웠습니다. worker_done 과 escalation 은 "
            "--from 을 명시하지 않으면 접수되지 않습니다\n"
        )
        if hasattr(stream, "flush"):
            stream.flush()
    return resolved


def wait_for_preamble_with_handle(
    path: Path,
    timeout_sec: float,
    poll_sec: float = 1.0,
    *,
    wait_fn=None,
) -> tuple[str, str]:
    """preamble 본문과 그 preamble 옆에 기록된 워커 핸들을 함께 소비합니다.

    wait_fn 을 주면 그 함수로 preamble 을 기다립니다. 런처가 자기 모듈의
    wait_for_preamble 별칭을 넘기면 기존 시험이 그 별칭을 가로채도 같은
    소비 지점을 관측할 수 있습니다.
    """
    waiter = wait_for_preamble if wait_fn is None else wait_fn
    consumed: list[Path] = []
    text = waiter(path, timeout_sec, poll_sec, on_consume=consumed.append)
    handle = read_worker_handle(consumed[0]) if consumed else ""
    return text, handle


def remove_orphan_worker_handles(directory: Path) -> list[Path]:
    """짝이 되는 preamble 이 없는 낡은 워커 핸들 파일을 지웁니다.

    preamble 을 소비하지 않는 런처(codex 등)는 같은 nonce 의 .handle 을 읽을
    기회가 없어 파일이 남습니다. preamble 이 이미 사라진 핸들은 그 시도의
    워커 핸들이므로 다른 시도가 쓸 수 없고, 남겨 두면 워크트리에 누적됩니다.
    짝이 되는 preamble 이 아직 있으면 소비 대기 중인 다른 런처의 것이므로
    건드리지 않습니다. 지운 경로만 돌려줍니다.
    """
    base = Path(directory)
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    for handle in sorted(base.glob("preamble_*" + WORKER_HANDLE_SUFFIX)):
        if handle.with_suffix(".txt").exists():
            continue
        try:
            handle.unlink()
        except OSError:
            continue
        removed.append(handle)
    return removed


def wait_for_preamble(
    path: Path,
    timeout_sec: float,
    poll_sec: float = 1.0,
    *,
    on_consume=None,
) -> str:
    """고유한 파일명의 preamble 이 나타나 내용이 채워질 때까지 기다리고 소비(삭제)합니다.

    1. 기본 경로(.orca/preamble.txt) 또는 디렉터리로 대기 중일 때:
       - 워크트리 .orca 디렉터리 내에서 preamble_*.txt 고유 파일을 찾아 읽고 즉시 삭제합니다.
       - 후보가 둘 이상이면 어느 것도 소비하지 않고 남아있는 파일 목록을 출력한 뒤 거부합니다.
       - 고유 preamble 없이 옛 형태의 고정 .orca/preamble.txt 만 남아있으면 격리 파손 위험으로 거부합니다.
    2. 명시적 파일 경로로 대기 중일 때:
       - 해당 파일이 나타나 내용이 채워질 때까지 기다립니다.
       - preamble_*.txt 파일인 경우 소비 후 즉시 삭제합니다.
       - 동일 디렉터리에 preamble_*.txt 후보가 둘 이상이면 거부합니다.
    3. on_consume 콜백을 주면 소비(삭제) 직전에 선택된 경로로 호출합니다. 런처는
       이 경로로 같은 nonce 의 워커 핸들 파일을 찾습니다.
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
                        if on_consume is not None:
                            on_consume(chosen)
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
                    if on_consume is not None:
                        on_consume(path)
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


WORKER_POLICY_FILENAME = "commandcode_worker_settings.json"
WORKER_SETTINGS_PATH = Path(".commandcode") / "settings.json"


def worker_policy_source() -> Path:
    """저장소가 관리하는 cmd 워커 정책 원본 경로를 돌려줍니다."""
    return Path(__file__).resolve().parent / "orca_policies" / WORKER_POLICY_FILENAME


def _git_rev_parse(cwd: Path, flag: str, runner: Any) -> str | None:
    """git rev-parse 결과를 문자열로 돌려줍니다. 실패하면 None 입니다."""
    try:
        completed = runner(  # nosec B603 B607 - 고정 인자 목록으로 git 만 조회합니다
            ["git", "-C", str(cwd), "rev-parse", flag],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def is_main_worktree(cwd: Path, *, runner: Any = None) -> bool:
    """cwd 가 저장소의 주 작업 트리인지 판정합니다.

    연결 워크트리(git worktree add)에서는 --git-dir 이 공용 .git/worktrees/<이름>
    을 가리키고 --git-common-dir 은 공용 .git 을 가리켜 서로 다릅니다. 주 작업
    트리에서는 둘이 같은 .git 입니다. 판정할 수 없으면(fail-safe) 주 작업 트리로
    봅니다. 그래야 정책 배치가 주 저장소의 사용자 설정을 덮어쓰지 않습니다.
    """
    run = subprocess.run if runner is None else runner  # nosec B603 B607 - 고정 인자 목록으로 git 만 조회합니다
    cwd = Path(cwd)
    git_dir = _git_rev_parse(cwd, "--git-dir", run)
    common_dir = _git_rev_parse(cwd, "--git-common-dir", run)
    if git_dir is None or common_dir is None:
        return True

    def _absolute(value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else cwd / path).resolve()

    return _absolute(git_dir) == _absolute(common_dir)


def deploy_worker_settings(
    cwd: Path,
    *,
    source: Path | None = None,
    runner: Any = None,
    stderr: Any = None,
) -> Path | None:
    """cmd 워커 워크트리일 때만 <cwd>/.commandcode/settings.json 을 배치합니다.

    주 저장소(메인 작업 트리)에서는 아무것도 쓰지 않습니다. 주 저장소의
    .commandcode/settings.json 은 사용자 개인 allow 규칙을 담고 있어 덮어쓰면
    안 됩니다. 정책 원본이 JSON 으로 읽히지 않으면 배치하지 않습니다. 깨진
    정책을 배치하면 cmd 가 기동을 거부하거나 규칙 없이 뜰 수 있습니다.

    배치한 경로를 돌려주고, 배치하지 않았거나 실패하면 None 을 돌려줍니다.
    """
    err_stream = sys.stderr if stderr is None else stderr
    cwd = Path(cwd)
    if is_main_worktree(cwd, runner=runner):
        return None

    root = worker_policy_source() if source is None else Path(source)
    try:
        payload = root.read_text(encoding="utf-8")
        json.loads(payload)
    except (OSError, ValueError) as err:
        err_stream.write(f"오류: cmd 워커 정책을 읽을 수 없습니다: {root} ({err})\n")
        if hasattr(err_stream, "flush"):
            err_stream.flush()
        return None

    target = cwd / WORKER_SETTINGS_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    except OSError as err:
        err_stream.write(f"오류: cmd 워커 정책을 배치하지 못했습니다: {target} ({err})\n")
        if hasattr(err_stream, "flush"):
            err_stream.flush()
        return None
    return target
