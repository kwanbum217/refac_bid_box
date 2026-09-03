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
