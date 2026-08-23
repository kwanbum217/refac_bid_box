# Antigravity 신뢰 설정 잠금 경화 및 동시성 테스트 플랫폼 독립화 분석

> **작성일**: 2026-08-23
> **대상 모듈**: `scripts/orca_trust_worktree.py`, `tests/test_orca_trust_worktree.py`
> **목적**: stale lock 회수 경로의 TOCTOU 경쟁 조건 및 FileNotFoundError 예외 제거, Windows CI 호환성을 위한 os.fork() 제거

---

## 1. 개요 및 배경

Antigravity CLI 워커 생성 전 워크스페이스 경로를 신뢰 목록(`settings.json`, `trustedFolders.json`)에 사전 등록하는 과정에서 두 가지 결함이 식별되었습니다.

1. **Stale Lock 회수 경로의 TOCTOU 및 예외 전파 결함**:
   - `scripts/orca_trust_worktree.py`의 기존 ad-hoc 락 파일 메커니즘에서 `read_text()`와 `stat()` 사이, 그리고 `stat()`과 `unlink()` 사이에 다른 프로세스가 락을 해제하거나 새로 획득할 경우 `FileNotFoundError`가 발생하거나 다른 프로세스의 유효한 락을 임의로 삭제하는 경쟁 조건(TOCTOU)이 존재했습니다.
2. **동시성 테스트의 Windows 비호환 결함**:
   - `tests/test_orca_trust_worktree.py`의 `test_settings_lock_stale_recovery`가 `os.fork()`를 직접 호출하여 POSIX 환경에 종속되어 있었으며, Windows CI 환경에서 `AttributeError: module 'os' has no attribute 'fork'`로 인해 테스트가 중단되는 문제가 발생했습니다.

본 작업에서는 신규 외부 라이브러리 추가 없이 파이썬 표준 라이브러리의 OS advisory lock(POSIX `fcntl.flock`, Windows `msvcrt.locking`)으로 락 메커니즘을 통일하고, 테스트를 플랫폼 독립적인 `subprocess`/`threading` 방식으로 전환했습니다.

---

## 2. 결함 분석 및 재현 조건

### 2.1 Stale Lock 회수 경로의 경쟁 조건 (TOCTOU)

| 단계 | 발생 메커니즘 | 취약점 및 영향 |
| --- | --- | --- |
| 1. `stat()` 미포착 예외 | `LOCK_FILE.read_text()` 직후 다른 프로세스가 락을 정상 해제하여 파일이 삭제된 경우, 뒤이어 호출되는 `LOCK_FILE.stat()`이 `suppress` 블록 밖에 있어 `FileNotFoundError` 발생 | 워커 기동 스크립트 비정상 종료 |
| 2. 타 프로세스 락 삭제 | 프로세스 A가 stale 판정 후 `LOCK_FILE.unlink()`를 호출하기 직전에 프로세스 B가 새로 락을 획득하고 파일을 생성하면, 프로세스 A가 프로세스 B의 활성 락 파일을 삭제 | 동시 쓰기 보호 상실 및 데이터 손상 |
| 3. 비원자적 PID 검사 | `_is_owner_process_dead`에서 `os.kill(pid, 0)`을 통한 PID 생존 검사는 프로세스 네임스페이스 격리, PID 재사용(PID wrap-around), 권한 문제 등으로 인해 비원자적이며 신뢰성이 부족 | 오탐 또는 stale 락 미회수 |

### 2.2 `os.fork()` 호출로 인한 Windows CI 중단

`os.fork()`는 POSIX 전용 시스템 호출입니다. Windows 커널 및 Python 런타임에는 `fork()`가 존재하지 않으므로, Windows 환경에서 해당 테스트 수트 실행 시 즉시 예외가 발생하여 CI 파이프라인이 깨지는 문제가 있었습니다.

---

## 3. 개선 및 구현 내용

### 3.1 OS Advisory Lock 기반 배타 제어 구현

파이썬 표준 라이브러리만을 활용하여 운영체제 커널 레벨의 자문 잠금(Advisory Lock)을 적용했습니다.

```python
try:
    import fcntl as _fcntl

    def _acquire_platform_lock(fobj: IO[Any]) -> bool:
        try:
            _fcntl.flock(fobj.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _release_platform_lock(fobj: IO[Any]) -> None:
        with suppress(OSError):
            _fcntl.flock(fobj.fileno(), _fcntl.LOCK_UN)

    _LOCK_AVAILABLE = True
except ImportError:
    try:
        import msvcrt as _msvcrt

        _LOCK_CHUNK = 1

        def _acquire_platform_lock(fobj: IO[Any]) -> bool:
            try:
                fobj.seek(0)
                _msvcrt.locking(fobj.fileno(), _msvcrt.LK_NBLCK, _LOCK_CHUNK)
                return True
            except (BlockingIOError, OSError):
                return False

        def _release_platform_lock(fobj: IO[Any]) -> None:
            with suppress(OSError):
                fobj.seek(0)
                _msvcrt.locking(fobj.fileno(), _msvcrt.LK_UNLCK, _LOCK_CHUNK)

        _LOCK_AVAILABLE = True
    except ImportError:
        _LOCK_AVAILABLE = False
```

- **POSIX**: `fcntl.flock(fileno, LOCK_EX | LOCK_NB)`로 non-blocking 배타 락을 시도합니다.
- **Windows**: `msvcrt.locking(fileno, LK_NBLCK, 1)`로 파일 시작 1바이트에 대한 non-blocking 잠금을 수행합니다.
- **비정상 종료 시 즉시 회수**: 프로세스가 비정상 종료(SIGKILL, 크래시, 전원 단절 등)되더라도 열린 파일 디스크립터가 닫히면서 커널에 의해 락이 즉시 원자적으로 해제됩니다. 별도의 stale timeout 대기나 수동 `unlink()`가 불필요합니다.
- **TOCTOU 제거**: 잠금 파일 자체를 `unlink()`하지 않고 유지하므로 파일 생성/삭제 간의 레이스 컨디션 및 `FileNotFoundError`가 원천 제거됩니다.

### 3.2 플랫폼 독립적 동시성 및 회수 테스트 개편

- `os.fork()`를 완전히 제거하고 Python 표준 `subprocess.Popen`을 사용하여 락을 보유한 격리된 자식 프로세스를 기동합니다.
- 자식 프로세스가 락을 잡고 있음을 확인한 후 `proc.kill()`을 호출하여 비정상 프로세스 사망 상황을 모사합니다.
- 자식 프로세스 사망 즉시 대기 중이던 부모 프로세스가 락을 즉시 정상 획득함을 검증합니다.
- 다중 스레드 동시성(`threading.Barrier`, 10개 스레드)을 통해 동시 락 획득 요청이 데이터 손실 없이 직렬화됨을 확인합니다.

---

## 4. 검증 결과

| 검증 항목 | 검증 명령 | 결과 | 상세 내용 |
| --- | --- | :---: | --- |
| 락 단위 테스트 | `uv run pytest tests/test_orca_trust_worktree.py -v` | **PASS** | 9개 테스트 전량 통과 (0.97s, fork deprecation warning 제거) |
| 준비 스크립트 연계 | `uv run pytest tests/test_orca_prepare_worktree.py -v` | **PASS** | 12개 테스트 전량 통과 |
| 정적 분석 / 린트 | `uv run ruff check scripts/orca_trust_worktree.py tests/test_orca_trust_worktree.py` | **PASS** | 린트 위반 0건 |
| 포맷 검사 | `uv run ruff format --check scripts/orca_trust_worktree.py tests/test_orca_trust_worktree.py` | **PASS** | 포맷 일치 확인 |
| 저장소 내 fork 전수조사 | `grep -rn "os.fork" scripts/ tests/` | **PASS** | 코드 및 테스트 내 `os.fork` 사용 0건 |

---

## 5. 남은 한계 및 주의사항

1. **네트워크 파일시스템(NFS/SMB) 환경**:
   - `fcntl.flock` 및 `msvcrt.locking`은 로컬 파일시스템에서 완벽히 동작합니다. 네트워크 공유 드라이브(NFS, CIFS 등)의 경우 락 데몬 지원 여부에 따라 동작이 달라질 수 있으나, 본 프로젝트의 Antigravity CLI 설정 경로는 사용자 홈 로컬 디렉터리(`~/.gemini`)에 위치하므로 영향이 없습니다.
2. **동일 스레드 내 재진입(Non-reentrant)**:
   - 배타 잠금은 재진입(Reentrant)을 허용하지 않으며, 동일 컨텍스트에서 중복 진입 시 타임아웃 예외가 발생하도록 설계되어 데드락을 방지합니다.
