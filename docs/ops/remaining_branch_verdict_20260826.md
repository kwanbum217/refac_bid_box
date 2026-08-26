# 잔여 미판정 브랜치 회수/폐기 판정 보고서

> **작성일**: 2026-08-26
> **작성 근거**: `run_5d9b78e37332 / task_14ca214849b4` 정본 사양
> **대상 브랜치 수**: 2개 (`feat/p1-reliability-lock`, `kwanbum217/orca-w1-concurrency-2`)
> **판정 기준**: main 현재 코드 대비 고유 가치 유무 및 상위 호환성 여부

---

## 1. 판정 요약

| # | 브랜치 | 마지막 커밋 SHA | 고유 커밋 수 | 핵심 변경 내용 | 판정 |
| :---: | --- | :---: | :---: | --- | :---: |
| 1 | `feat/p1-reliability-lock` | `75dd01912dd3281d52adc24ae9121115913de23f` (`75dd019`) | 1 | `scripts/orca_model_router.py` msvcrt 잠금 결함 수정(`seek(0)`, `LK_LOCK`), 동시성 테스트 Barrier 도입 | **폐기 권고** (main에 상위 호환 반영 완료) |
| 2 | `kwanbum217/orca-w1-concurrency-2` | `12f88c3ad8fd674598dedf9bc07fa8ac943e40e1` (`12f88c3`) | 1 | `tests/test_orca_model_router.py` lost-update 테스트의 `Pool.map` 및 전역 Barrier 방식 전환 | **폐기 권고** (main 판본이 크로스플랫폼 상위 구현) |

본 판정으로 저장소의 모든 브랜치에 대한 판정(총 11개: 베이크오프 9개 + 잔여 2개)이 완료되었습니다. 두 브랜치 모두 회수할 고유 가치가 없으므로 **폐기 권고**로 판정합니다.

---

## 2. 상세 판정 근거

### 2.1 `feat/p1-reliability-lock` (커밋 `75dd019`)

- **작업 내용**:
  - `scripts/orca_model_router.py`: Windows `msvcrt` 파일 잠금 시 `fobj.seek(0)` 호출 추가 및 non-blocking(`LK_NBLCK`)을 blocking(`LK_LOCK`)으로 변경.
  - `tests/test_orca_model_router.py`: 전역 Barrier(`_concurrent_barrier`)와 `ctx.Pool(processes=N).map`을 이용한 동시성 경쟁 유도 테스트 추가, 소스 코드 내 하드코딩 절대경로 리터럴 부재 검증 추가.
- **main 현재 코드와의 대조 결과**:
  1. **잠금 로직 (`scripts/orca_model_router.py:632-670`)**: main 브랜치는 `_MsvcrtLockModule` Protocol 정의, `cast`를 활용한 정적 타입 좁히기, `fobj: IO[str]` 타입 힌트, 상세 주석과 함께 `fobj.seek(0)` 및 `LK_LOCK` / `LK_UNLCK`이 완전히 적용되어 있습니다. 브랜치의 변경 사항이 더 정교한 상위 형태로 이미 반영되어 있습니다.
  2. **동시성 테스트 (`tests/test_orca_model_router.py:1751-1790`)**: 브랜치의 전역 Barrier 방식은 `spawn` 컨텍스트에서 pickle이 불가능하여 Windows 환경을 skip(`pytest.skip`)하지만, main은 `ctx.Process` 생성 시 `Barrier` 인스턴스를 직접 주입하여 macOS/Linux(`fork`) 및 Windows(`spawn`)를 모두 지원하며, 각 자식 프로세스의 `exitcode == 0` 단언까지 수행합니다.
  3. **절대경로 검증 (`tests/test_orca_model_router.py:1801-1818`)**: main은 `Path.home()` monkeypatch를 통해 fallback 경로 생성 로직을 런타임 수준에서 엄밀하게 검증하고 있습니다.
- **판정**: **폐기 권고** (main에 상위 호환 반영 완료로 회수 가치 없음)

### 2.2 `kwanbum217/orca-w1-concurrency-2` (커밋 `12f88c3`)

- **작업 내용**:
  - `tests/test_orca_model_router.py`의 `TestConcurrentReliabilityRecord.test_no_lost_updates_under_concurrent_writes`를 `ctx.Process` 목록 관리 방식에서 `ctx.Pool(processes=n_writers).map` 및 모듈 전역 `_concurrent_barrier` 방식으로 변경.
- **main 현재 코드와의 대조 결과**:
  1. **크로스 플랫폼 지원 (G2 목표)**: `kwanbum217/orca-w1-concurrency-2` 방식은 전역 Barrier 객체를 참조하므로 Windows(`spawn`) 환경에서 동작하지 않아 `if os.name == "nt": pytest.skip(...)` 처리를 강제합니다.
  2. **프로세스 정상 종료 단언**: main 브랜치의 구현(`ctx.Process`)은 프로세스별 `proc.exitcode == 0`을 명시적으로 검증하여 경쟁 시 프로세스 충돌 여부를 정확히 잡아냅니다.
  3. **기각 이력**: 이미 `docs/handoff/session_20260826_branch_cleanup_orca.md` 3.1절에서 main 판본의 우수성으로 인해 병합 기각된 바 있습니다.
- **판정**: **폐기 권고** (기각 유지, 크로스플랫폼 및 검증 정밀도 측면에서 main 판본이 상위)

---

## 3. 삭제 시 복구용 SHA 목록

폐기 권고된 브랜치가 삭제된 후 필요 시 되살릴 수 있도록 마지막 커밋 SHA를 기록합니다.

| 브랜치 | 마지막 커밋 SHA (Full) | 단축 SHA | 커밋 메시지 요약 |
| --- | --- | :---: | --- |
| `feat/p1-reliability-lock` | `75dd01912dd3281d52adc24ae9121115913de23f` | `75dd019` | fix: msvcrt 잠금 결함 수정 및 동시성 테스트 강화 |
| `kwanbum217/orca-w1-concurrency-2` | `12f88c3ad8fd674598dedf9bc07fa8ac943e40e1` | `12f88c3` | test: force real contention in reliability lost-update regression |

---

## 4. 메타데이터

| 항목 | 값 |
| --- | --- |
| 작업 브랜치 | `kwanbum217/orca-w3-verdict` |
| 대상 커밋 SHA | `75dd019`, `12f88c3` |
| 검증 스크립트 | `python3 scripts/validate_agent_rules.py --quiet` |
| 최종 판정 결과 | 대상 2개 브랜치 전량 폐기 권고 |
