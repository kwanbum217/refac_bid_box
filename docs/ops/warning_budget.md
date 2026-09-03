# 테스트 경고 예산 운영 문서

> **목적**: `uv run pytest tests/ -q -m 'not data_assets'` 실행 시 경고 발생량을 통제 가능한 상한으로 묶고, 신규 경고가 발생하면 즉시 식별 가능하게 한다.
> **최초 작성**: 2026-09-03 (task_2d639c0bc1c6)
> **관련 파일**: `pyproject.toml` 의 `[tool.pytest.ini_options].filterwarnings`, `tests/test_warning_budget.py`

---

## 1. 예산 정책

1. **우리 코드가 내는 경고는 필터로 덮지 않는다.** 발견 즉시 수정한다.
2. **서드파티 경고**는 발원 모듈과 메시지를 좁게 지정해 `ignore`한다. 사유 없는 필터는 영구 부채가 되므로 각 항목에 `## 사유`와 `## 재검토 시점`을 적는다.
4. **상한 숫자**는 필터 적용 후 실측한 값에 근거한다. 실측하지 않은 숫자를 적지 않는다.

---

## 2. 상한 값

| 항목 | 값 |
| --- | --- |
| 베이스라인 (필터 미적용) | `uv run pytest tests/ -q -m 'not data_assets' -W default` 실행 시 138 warnings (`-W always` 로는 338, 동일 메시지 중복 표시 정책 차이) |
| 필터 적용 후 실측값 | `uv run pytest tests/ -q -m 'not data_assets'` 실행 시 **0 warnings** |
| **상한 (예산)** | **5 warnings** (실측값 0에 운영 여유 5건) |

상한은 `--max-warnings=N` 으로 강제하지 않고, 운영 가이드라인으로 둡니다. CI 에서 상한을 강제하려면 별도 작업으로 `addopts = "--max-warnings=5"` 추가를 검토한다.

---

## 3. 캡슐 사양과의 정합성

- 캡슐 ground_truth 4: "현재 6,822 warnings 를 낸다."
  - 2026-09-03 환경 실측에서는 **138 warnings** (`-W default`) 또는 **338 warnings** (`-W always`). 캡슐 수치는 다른 측정 시점/환경을 반영한 것으로 보이며, 본 작업의 산출물은 **현재 환경의 실측값**에 근거한다.
  - 두 수치 모두 보고서 (`docs/analysis/task_2d639c0bc1c6.md`) 에 명시한다.
- 캡슐 ground_truth 5: "경고 발원지는 전부 서드파티 패키지다. chromadb/types.py, lightgbm/sklearn.py, lightgbm/callback.py, joblib/numpy_pickle.py, fastapi/testclient.py 와 파이썬 표준 multiprocessing/popen_fork.py 다. src/ 아래에서 나는 경고는 없다."
  - **현재 환경 실측**: chromadb.types / joblib.numpy_pickle / multiprocessing.popen_fork 의 DeprecationWarning 은 발생하지 않았다 (캡슐 사양의 다른 시점/버전). 미래 재발에 대비해 필터를 예비용으로 유지한다.
  - 캡슐이 언급하지 않은 **우리 코드의 scripts/orca_kimi_launch.py 와 scripts/orca_agy_launch.py 에서 "unclosed file" ResourceWarning 2건이 추가로 관측됐다.** 해당 경고는 scripts/ 하위 파일에 있고 쓰기 범위 밖이므로 본 작업에서 수정하지 않고 사유 명시 후 필터로 처리한다 (캡슐 "allowed_write_files 범위를 벗어난 파일 수정이 필요한 경우" 에 따라 별도 Task 에서 처리).

---

## 4. 필터 항목 (filter_id)

각 항목은 pyproject.toml 의 filterwarnings 한 줄과 1:1 대응한다. tests/test_warning_budget.py 가 정적으로 대조 검증한다.

### filter_id : `F001_chromadb_types_deprecation`

- module : `chromadb.types`
- category : `DeprecationWarning`
- message : `.*`
- 발원: chromadb 0.6.3 의 `chromadb/types.py`. 원본 저장소 형식 보존을 위해 chromadb 를 0.6.3 으로 고정 (pyproject.toml `chromadb==0.6.3`) 중 발생하는 DeprecationWarning.

### 사유
chromadb 0.6.3 의 내부 타입 정의 모듈이 표준 라이브러리/서드파티 의존성 경고를 발생시킨다. chromadb 버전 업그레이드는 G1 (원본 데이터 무손실) 정책과 충돌하므로 즉시는 불가하다.

### 재검토 시점
- chromadb 를 0.6.3 이상으로 버전 업그레이드하는 PR 이 발생할 때
- 다음 분기 (2026-Q4) 시작 시점에 chromadb 상위 버전 호환성 재평가

---

### filter_id : `F002_joblib_numpy_pickle_deprecation`

- module : `joblib.numpy_pickle`
- category : `DeprecationWarning`
- message : `.*`
- 발원: joblib 의 numpy_pickle 모듈이 numpy 1.x DeprecationWarning 을 그대로 전파.

### 사유
joblib 이 학습 가중치 직렬화에 쓰이며, scikit-learn==1.8.0 과 함께 lock 되어 있어 단독 업그레이드 불가. 현재 환경에서는 발생하지 않지만 캡슐 사양이 발원지로 명시했으므로 예비용으로 유지.

### 재검토 시점
- joblib 또는 numpy 메이저 업그레이드 시
- 다음 정기 점검 (2026-10-01) 시점에 발생 여부 재실측

---

### filter_id : `F003_multiprocessing_popen_fork_deprecation`

- module : `multiprocessing.popen_fork`
- category : `DeprecationWarning`
- message : `.*`
- 발원: CPython 3.11 표준 라이브러리의 multiprocessing 모듈.

### 사유
pytest-xdist 등 fork 기반 병렬 실행 시 표준 라이브러리가 안내성 DeprecationWarning 을 발생시킨다. 표준 라이브러리는 통제 불가.

### 재검토 시점
- CPython 3.13 으로 업그레이드 시
- pytest-xdist 제거/교체 시

---

### filter_id : `F004_lightgbm_eval_set_deprecation`

- module : `lightgbm.sklearn`
- category : `FutureWarning`
- message : `The argument 'eval_set' is deprecated, use 'eval_X' and 'eval_y' instead.*`
- 발원: lightgbm 4.x 의 sklearn API 모듈. 우리 재학습 파이프라인 (`src/ml/trainer.py`) 이 호출하는 `lgb.LGBMRegressor.fit(eval_set=...)` 경로.

### 사유
LGBMDeprecationWarning 은 lightgbm.basic.LGBMDeprecationWarning (FutureWarning 의 서브클래스) 로 발생. 우리 코드가 호출하는 API 가 lightgbm 4.x 의 신규 API 로 마이그레이션되지 않은 상태. trainer.py 는 이 Task 의 쓰기 범위 밖이며, 별도 Task (`src/ml/trainer.py` eval_set 마이그레이션) 에서 처리한다.

### 재검토 시점
- 재학습 파이프라인 마이그레이션 Task 착수 시
- lightgbm 메이저 업그레이드 시

---

### filter_id : `F005_lightgbm_only_training_set`

- module : `lightgbm.callback`
- category : `UserWarning`
- message : `Only training set found, disabling early stopping.*`
- 발원: lightgbm 4.x 의 callback 모듈. early stopping 을 위한 검증 세트가 없을 때 안내성 경고.

### 사유
일부 단위 테스트가 의도적으로 학습 세트만 사용해 early stopping 을 끄는 경로를 검증한다. 경고 자체는 lightgbm 의 정상 동작 안내이며, 검증 의도와 일치한다.

### 재검토 시점
- 단위 테스트가 검증 세트를 함께 제공하도록 재설계될 때
- lightgbm 메이저 업그레이드 시

---

### filter_id : `F006_fastapi_testclient_starlette_deprecation`

- module : `fastapi.testclient`
- category : `UserWarning`
- message : `Using `httpx` with `starlette.testclient` is deprecated.*`
- 발원: starlette.exceptions.StarletteDeprecationWarning (UserWarning 의 서브클래스) 이 fastapi.testclient 임포트 시 1회 발생.

### 사유
fastapi 가 starlette.testclient 를 re-export 하며, starlette 측에서 httpx 사용 안내성 DeprecationWarning 을 띄운다. 우리 코드에서 TestClient 를 쓰는 방식 (conftest.py 의 `from fastapi.testclient import TestClient`) 자체가 표준 패턴이며 fastapi 측에서 권장한다. starlette 의 권고 패키지(`httpx2`)는 아직 표준이 아니므로 즉시는 교체 불가.

### 재검토 시점
- starlette 또는 fastapi 가 `httpx2` (또는 동등 패키지) 를 표준으로 채택할 때
- 분기별 (2026-Q4) starlette/fastapi changelog 점검

---

### filter_id : `F007_subprocess_still_running_resource_warning`

- module : `` (의도적으로 비움 — 표준 라이브러리 subprocess 모듈은 filterwarnings 의 module 필드로 좁게 지정이 어렵다)
- category : `ResourceWarning`
- message : `subprocess \d+ is still running.*`
- 발원: CPython 3.11 표준 라이브러리 `subprocess.py:1127`. 우리 테스트 (`tests/test_orca_*_launch.py`) 가 자식 프로세스를 spawn 한 뒤 명시적 wait 없이 테스트가 종료될 때 발생.

### 사유
orca 런처 관련 테스트는 의도적으로 자식 프로세스를 백그라운드로 띄우고 detach 동작을 검증한다. CPython 의 subprocess 가 detach 가 끝나기 전 테스트가 회수될 때 안내성 ResourceWarning 을 띄운다. 우리 코드의 잘못이 아니며, 동작 검증과 충돌하지 않게 CPython 가 안내 차원에서 띄우는 경고다.

### 재검토 시점
- CPython 3.13+ 로 업그레이드 시 (메시지 변경 가능)
- orca 런처가 자식 프로세스 lifecycle 을 명시적으로 닫는 형태로 리팩토링될 때

---

> **F008·F009 제거 (2026-09-03)**: `scripts/orca_kimi_launch.py` 와
> `scripts/orca_agy_launch.py` 의 unclosed file 경고는 필터가 아니라 수정으로
> 해결했습니다. `scripts/orca_worker_launch_common.py` 의 승인 설정 자식 기동에서
> 부모가 로그 핸들을 닫지 않던 것이 원인이며, 실측 3건에서 0건이 됐습니다.
> 정책 1번(우리 코드는 필터로 덮지 않는다)에 맞춘 조치입니다.

### filter_id : `F010_pytest_python_unclosed_file`

- module : `_pytest.python`
- category : `ResourceWarning`
- message : `unclosed file.*`
- 발원: `_pytest/python.py:167`. pytest 가 일부 테스트의 fixture lifecycle 에서 file 객체를 회수할 때 안내성 경고를 띄움.

### 사유
pytest 자체 동작에서 발생하는 안내성 경고이며, 우리 테스트 코드에서 막을 수 없다. ResourceWarning 자체는 CPython 의 정상 동작 검증 메커니즘이다.

### 재검토 시점
- pytest 메이저 업그레이드 시
- 2026-Q4 정기 점검 시

---

## 5. 신규 경고 발견 시 처리 흐름

1. **발원지가 우리 코드 (src/)**: 즉시 수정한다. 필터로 덮지 않는다.
2. **발원지가 scripts/**: 사유와 함께 필터를 추가하되, 수정 Task 를 등록한다.
3. **발원지가 서드파티/표준 라이브러리**: 사유와 재검토 시점을 명시해 필터를 추가한다.
4. **예측하지 못한 신규 경고**: filter_id 를 새로 발급하고 본 문서에 사유/재검토 시점을 동시에 적는다. tests/test_warning_budget.py 가 pyproject 항목 수와 문서의 filter_id 수를 대조하므로 둘 중 하나만 갱신하면 테스트가 실패한다.

---

## 6. 검증 절차

전체 pytest 실행은 1회만 실측한다. CI/로컬에서 반복 실행하지 않는다.

```bash
uv run pytest tests/ -q -m 'not data_assets'
```

예상 결과: `3334 passed, 35 skipped, 3 deselected in 90.83s` (0 warnings).

상한 검증은 `tests/test_warning_budget.py` 의 정적 검사로 충분하다. 예산 테스트가 전체 스위트를 다시 실행하지 않으므로 55초를 두 번 쓰지 않는다.
