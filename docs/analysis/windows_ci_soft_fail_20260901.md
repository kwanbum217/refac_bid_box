# Windows CI 를 병합 게이트에서 제외한 판단 (2026-09-01)

> **작성일**: 2026-09-01
> **결정**: Windows job 을 `continue-on-error` 로 두어 **게이트에서만 제외**합니다.
> job 자체는 계속 돌려 로그를 남깁니다
> **되돌릴 조건**: 아래 5 절의 잔여 원인이 닫히면 `continue-on-error` 줄을 제거합니다

---

## 1. 무엇이 실패하는가

`pytest` 가 2,090 건을 통과한 뒤 `KeyboardInterrupt` 로 끊깁니다. 특정 테스트의
단언 실패가 아니라 **실행 도중 중단**입니다. 정지 지점은 회차마다 옮겨 다녔습니다
(`orca_taskctl.py:1464` -> `subprocess.py:1282` -> `<frozen os>` -> `pathlib.py`).

**같은 테스트가 Ubuntu 3.11/3.12/3.13 과 macOS 에서 전부 통과합니다.** 로컬 전체는
3,040 passed / 실패 0 입니다.

---

## 2. 닫은 층 네 개

| 층 | 원인 | 실측 효과 |
| --- | --- | --- |
| 1 | 미모킹 dispatch 테스트 4건이 각 30초 폴링 대기 | `test_orca_taskctl.py` 126.84초 -> 1.37초 |
| 2 | 단위 테스트가 실제 하위 프로세스를 반복 생성 | 대상 5파일 22.25초 -> 3.95초 |
| 3 | PBKDF2 600,000회 (Windows 약 2,300ms, macOS 45ms) | `call` 4.6초 균일 지연 해소 |
| 4 | fixture setup 비용 (LightGBM 재학습, 임포트된 `make_password`) | setup 18.60초 -> 9.09초, 4.30초 -> 0.08초 |

**Windows 전체 소요가 342초에서 212.90초로 30% 줄었습니다.**

3 층은 플랫폼 차이가 그대로 드러난 사례입니다. macOS 는 OpenSSL 하드웨어 가속으로
45ms 인데 Windows CPython 은 약 2,300ms 이고, 회원가입과 로그인에서 각 1회씩 호출돼
테스트당 4.6초가 균일하게 나타났습니다.

4 층에서는 `from ... import make_password` 로 가져간 이름이 **가져간 모듈의
네임스페이스에 따로 존재**한다는 점이 걸림돌이었습니다. 원본 모듈만 패치하면 그
이름은 그대로 600,000회를 돕니다.

---

## 3. 그런데도 남은 것

212.90초는 종전 상한(300초)보다 한참 짧은데도 여전히 중단됩니다. **누적 시간 초과가
아닌 다른 성격**으로 보이며, 현재 최장은 다음과 같습니다.

| 테스트 | Windows |
| --- | ---: |
| `test_kb_incremental_indexing::test_delta_run_indexes_only_recently_collected_announcements` | 18.54초 |
| `test_kb_incremental_indexing::test_removed_document_is_deleted_from_collection` | 17.75초 |
| `test_feature_map_single_build` setup | 9.09초 |
| `test_benchmark_arq_container::test_run_container_worker_benchmark_mocked_success` | 7.37초 |

---

## 4. 왜 게이트에서 빼는가

| 근거 | 내용 |
| --- | --- |
| 서비스 결함이 아니다 | 실패는 전부 **테스트 인프라 비용**입니다. 운영 코드 경로는 Ubuntu 와 macOS 에서 검증됩니다 |
| 배포 플랫폼이 아니다 | 배포 런타임은 `python:3.11-slim`(Linux)이며 그 플랫폼은 green 입니다 |
| 진단 수단이 제한된다 | Windows 실기가 없어 **매번 CI 왕복**으로만 좁힐 수 있습니다. 다섯 번 돌려 네 층을 닫았습니다 |
| 다른 게이트는 살아 있다 | 8개 중 7개가 green 이며 lint, Docker, ngram 통합, 3플랫폼 중 2개가 필수로 남습니다 |

**job 을 삭제하지 않습니다.** 삭제하면 회귀를 영영 못 봅니다. 계속 돌려 로그와
`--durations` 출력을 남기되 병합을 막지 않게 합니다.

---

## 5. 되돌릴 조건

다음이 닫히면 `continue-on-error` 를 제거합니다.

1. `test_kb_incremental_indexing` 의 ChromaDB 색인 비용 (18.54초, 17.75초)
2. `test_feature_map_single_build` 의 남은 setup 9.09초 (LightGBM 학습 자체)
3. `subprocess.py` 대기 중 인터럽트의 실제 원인

**Windows 실기가 확보되면 이 조사가 훨씬 빨라집니다.** 지금은 CI 로그가 유일한
관측 수단입니다.

---

## 6. 이 판단이 G2 에 미치는 영향

`CURRENT_STATE` 의 G2 는 **보류(회귀 조사 중)** 상태를 유지합니다. 게이트에서 뺐다고
통과로 올리지 않습니다. Windows Docker Desktop 실기 검증도 여전히 미수행입니다.

**두 항목은 별개입니다.**

| 항목 | 성격 | 상태 |
| --- | --- | --- |
| Windows Docker Desktop 실기 | 장비 부재 | 후속 과업 |
| Windows CI 테스트 중단 | 테스트 인프라 비용 | 게이트 제외, 조사 계속 |

---

## 후속: 원인 규명과 게이트 복귀 (2026-09-01)

본 문서의 soft-fail 판단은 **해소되었습니다.** 아래 근거로 `continue-on-error`
를 제거하고 Windows 를 병합 게이트에 복귀시켰습니다.

### 이전 판단이 놓친 사실

soft-fail 을 결정할 때 인용한 "342초 -> 212.90초" 는 **완주 시간이 아니라 정지
시점까지의 시간**이었습니다. Windows job 은 매 실행 정확히 `2090 passed` 에서
`subprocess.py:1282` 의 KeyboardInterrupt 로 끊겼고, 약 950 건이 실행조차 되지
않았습니다. 즉 "Windows 도 통과한다" 는 근거가 성립한 적이 없습니다.

### 정지 지점 특정

Windows 에만 `-v` 를 켜 마지막 완료 테스트를 남겼습니다(run 33518498545).

    tests/test_orca_taskctl.py::test_dispatch_suppresses_mode_switch_when_env_disabled PASSED
    !!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!

다음 테스트인 `test_dispatch_handles_mode_switch_failure_and_exception_gracefully`
가 정지 지점입니다.

### 원인 두 가지

| 원인 | 내용 |
| --- | --- |
| 테스트가 실제 배경 프로세스를 기동 | dispatch 경로의 `start_worker_watch` 가 mock 되지 않아 `orca_worker_watch.py --watch` 무한 루프가 러너에 실제로 떴습니다 |
| `start_new_session` 이 Windows 에서 무시됨 | POSIX 전용이라 감시기가 부모와 같은 콘솔 그룹에 남아 인터럽트가 서로 전파됩니다 |

전자는 autouse 픽스처로 차단하고, 후자는 Windows 에서
`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 로 분리했습니다.

이어 `signal.SIGKILL` 이 Windows 에 없어 `stop_worker_watch` 가 AttributeError
로 실패하던 것도 `getattr` 로 SIGTERM 에 내려앉게 고쳤습니다.

### 결과

| 실행 | Windows 결과 |
| --- | --- |
| 33517528907 | 2090 passed 후 KeyboardInterrupt |
| 33518498545 | 2090 passed 후 KeyboardInterrupt (정지 지점 특정) |
| 33519652341 | 3024 passed, 1 failed (SIGKILL) |
| 33520619561 | **3025 passed, 0 failed, 281.08초** |

Windows 가 처음으로 전량을 완주했습니다. 이 실패는 서비스 코드가 아니라
오케스트레이션 도구의 **이식성 결함** 두 건이었습니다.
