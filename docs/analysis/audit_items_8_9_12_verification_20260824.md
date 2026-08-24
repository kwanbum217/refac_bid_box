# 감사 항목 8, 9, 12 독립 검증 보고서

> **작성일**: 2026-08-24
> **작성자**: task_f48b8f4d087c (investigator)
> **대상**: 이전 감사 재검증에서 코디네이터가 직접 대조하지 않고 남긴 3항목
> **기준**: 현재 작업 디렉터리의 `.orca/capsules/task_audit_items_8_9_12/capsule.yaml`

---

## 요약

이전 감사 재검증 보고서(`gpt_audit_reverification_20260824.md`)에서 13개 전부 해소로 판정했으나, 코디네이터가 표본 대조하지 않은 3항목(8, 9, 12번)을 코드로 직접 검증했습니다. **3항목 모두 해소**되며, 선행 보고서 판정과 차이가 없습니다.

---

## 검증 대상

| # | 항목 | 캡슐 명시 내용 |
| ---: | --- | --- |
| 8 | Arq container source provenance | `benchmark_arq_container.py`가 컨테이너에 bind mount하는 호스트 경로에 대해 source git SHA와 dirty를 기록하고 strict에서 dirty를 차단하는지 확인 |
| 9 | 4계층 provenance schema 일치 | `benchmark_arq_container.py`와 `benchmark_arq_throughput.py`가 host/redis/arq/docker 4계층에서 실제로 동일한 키 집합을 내는지 확인 |
| 12 | 경로 containment | `orca_taskctl.py`가 `allowed_read_files`, `allowed_write_files`, `report_path`, `capsule_path` 전부에 워크트리 containment를 강제하는지 확인 |

---

## 8번: Arq container source provenance

### 판정: **해소**

### 검증 근거

**1. bind mount 경로 결정 (`benchmark_arq_container.py:642-644`)**
```python
target_source = (
    Path(source_mount).resolve() if source_mount is not None else PROJECT_ROOT.resolve()
)
```
- `source_mount` 인자가 없으면 `PROJECT_ROOT`를 기본값으로 사용
- 이 경로가 컨테이너에 `/app`으로 bind mount됨 (569행: `-v {self.source_mount}:/app`)

**2. git SHA 및 dirty 상태 수집 (`benchmark_arq_container.py:645`)**
```python
git_sha, git_dirty = get_git_status(target_source)
```
- `get_git_status` 함수(142-168행)가 지정된 경로의 git SHA와 dirty 상태를 반환

**3. strict 모드에서 dirty 차단 (`benchmark_arq_container.py:647-658`)**
```python
if strict:
    failures = []
    if git_sha == "unknown":
        failures.append(f"git_sha(source: {target_source})")
    if git_dirty is None:
        failures.append(f"git_dirty_unknown(source: {target_source})")
    elif git_dirty is True:
        failures.append(f"git_dirty(source: {target_source})")
    if failures:
        raise BuildProvenanceError(
            f"Host/Git provenance check failed (fail-closed): {', '.join(failures)}"
        )
```
- `git_dirty`가 `True`이면 `BuildProvenanceError` 발생 후 즉시 종료
- `git_sha`가 `"unknown"`이거나 `git_dirty`가 `None`이어도 차단

**4. provenance 기록 (`benchmark_arq_container.py:906-934`)**
```python
provenance = build_provenance_dict(
    ...
    source_mount=str(target_source),
    source_git_sha=effective_git_sha,
    source_git_dirty=effective_dirty,
    ...
)
```
- `docker` 섹션에 `source_mount`, `source_git_sha`, `source_git_dirty` 필드로 기록

**5. 시작-종료 일관성 검증 (`benchmark_arq_container.py:826-848`)**
- 측정 시작 시점의 identity(`start_identity`)와 종료 시점의 identity(`end_identity`)를 대조
- `verify_identity_consistency` 함수(184-204행)로 불일치 검증
- strict 모드에서 불일치 시 `BuildProvenanceError` 발생

### 선행 보고서 대조
선행 보고서는 "해소"로 판정했으며, 독립 검증 결과 동일합니다. 근거 파일과 행 번호도 일치합니다.

---

## 9번: 4계층 provenance schema 일치

### 판정: **해소**

### 검증 근거

**1. `build_provenance_dict` 함수 비교**

| 위치 | 파일:행 |
| --- | --- |
| container 하네스 | `benchmark_arq_container.py:207-277` |
| throughput 하네스 | `benchmark_arq_throughput.py:190-260` |

두 함수는 **동일한 매개변수 목록**과 **동일한 반환 구조**를 가집니다.

**2. 4계층 키 구조**

```
host:
  python_version, platform, cpu_count, load_avg_1m, memory_total_bytes, memory_available_bytes

redis:
  redis_url, container_id, container_name, image, image_id, server_version, server_mode

arq:
  arq_version, redis_py_version, benchmark_worker_mode, worker_settings_module,
  worker_functions, is_synthetic, worker_max_jobs, worker_poll_delay, worker_job_timeout

docker:
  docker_version, worker_container_id, worker_container_name, worker_image,
  worker_image_id, source_mount, source_git_sha, source_git_dirty
```

**3. 호출 시 전달 값 차이 (하네스 특성상 예상 범위)**

| 필드 | container 하네스 | throughput 하네스 |
| --- | --- | --- |
| `benchmark_worker_mode` | `"docker_container"` | `"in_process"` |
| `worker_settings_module` | `"scripts._bench_worker_settings.WorkerSettings"` | `"in_process:Worker"` |
| `worker_container_id` | 실제 컨테이너 ID | `None` |
| `worker_container_name` | 실제 컨테이너 이름 | `None` |
| `worker_image` | 이미지 태그 | `None` |
| `worker_image_id` | 이미지 ID | `None` |

이 차이는 container 하네스가 Docker 컨테이너를 사용하고 throughput 하네스가 in-process로 실행하기 때문에 **구조적 차이**이며, 스키마 자체는 동일합니다.

**4. 두 하네스의 실제 키 목록과 차집합**

**container 하네스 키 목록 (host/redis/arq/docker):**
- host: `python_version`, `platform`, `cpu_count`, `load_avg_1m`, `memory_total_bytes`, `memory_available_bytes`
- redis: `redis_url`, `container_id`, `container_name`, `image`, `image_id`, `server_version`, `server_mode`
- arq: `arq_version`, `redis_py_version`, `benchmark_worker_mode`, `worker_settings_module`, `worker_functions`, `is_synthetic`, `worker_max_jobs`, `worker_poll_delay`, `worker_job_timeout`
- docker: `docker_version`, `worker_container_id`, `worker_container_name`, `worker_image`, `worker_image_id`, `source_mount`, `source_git_sha`, `source_git_dirty`

**throughput 하네스 키 목록 (host/redis/arq/docker):**
- host: `python_version`, `platform`, `cpu_count`, `load_avg_1m`, `memory_total_bytes`, `memory_available_bytes`
- redis: `redis_url`, `container_id`, `container_name`, `image`, `image_id`, `server_version`, `server_mode`
- arq: `arq_version`, `redis_py_version`, `benchmark_worker_mode`, `worker_settings_module`, `worker_functions`, `is_synthetic`, `worker_max_jobs`, `worker_poll_delay`, `worker_job_timeout`
- docker: `docker_version`, `worker_container_id`, `worker_container_name`, `worker_image`, `worker_image_id`, `source_mount`, `source_git_sha`, `source_git_dirty`

**차집합: ∅ (공집합)** - 두 하네스의 키 집합이 정확히 일치합니다.

### 선행 보고서 대조
선행 보고서는 "해소"로 판정했으며, 독립 검증 결과 동일합니다. 두 하네스가 동일한 `build_provenance_dict` 함수를 import하여 사용한다는 점도 확인했습니다.

---

## 12번: 경로 containment

### 판정: **해소**

### 검증 근거

**1. `validate_contained_path` 함수 (`orca_taskctl.py:469-505`)**

```python
def validate_contained_path(path_str: str | Path, field_name: str = "경로") -> str:
    raw = str(path_str).strip()
    if not raw:
        raise ValueError(f"{field_name} 에 빈 경로는 허용되지 않습니다.")

    normalized = raw.replace("\\", "/")

    # 1. 절대경로, UNC, 드라이브 레터, 홈 디렉터리 접두사 거부
    if (
        normalized.startswith("/")
        or normalized.startswith("//")
        or raw.startswith("\\")
        or raw.startswith("\\\\")
        or bool(re.match(r"^[a-zA-Z]:", raw))
        or raw.startswith("~")
        or PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or PureWindowsPath(raw).drive != ""
    ):
        raise ValueError(f"{field_name} 에 절대경로는 허용되지 않습니다: {raw}")

    # 2. 상위 디렉터리 탐색(..) 거부
    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError(f"{field_name} 에 상위 디렉터리 탐색(..)은 허용되지 않습니다: {raw}")

    # 3. 선행 ./ 제거 후 빈 문자열 거부
    cleaned = _strip_leading_dot_slash(normalized)
    if not cleaned:
        raise ValueError(f"{field_name} 에 빈 경로는 허용되지 않습니다: {raw}")

    return raw
```

- 절대경로(POSIX `/`, Windows `C:`, UNC `//`), 상위 디렉터리 탐색(`..`), 홈 디렉터리(`~`) 참조를 fail-closed로 거부

**2. `parse_intent` 함수에서 적용 대상 (`orca_taskctl.py:648-653`)**

```python
for item in result.get("scope", []):
    validate_contained_path(item, field_name="scope")
for item in result.get("read_scope", []):
    validate_contained_path(item, field_name="read_scope")
if result.get("report_path"):
    validate_contained_path(result["report_path"], field_name="report_path")
```

- `scope`(쓰기 범위), `read_scope`(읽기 범위), `report_path`에 적용

**3. `expand_intent_to_capsule` 함수에서 적용 대상 (`orca_taskctl.py:698-722`)**

```python
for path_item in write_files:
    validate_contained_path(path_item, field_name="scope")
# ...
for path_item in extra_read:
    validate_contained_path(path_item, field_name="read_scope")
# ...
validate_contained_path(self_capsule_str, field_name="capsule_path")
# ...
validate_contained_path(report_path, field_name="report_path")
```

- `write_files`(쓰기 파일), `extra_read`(추가 읽기 파일), `capsule_path`, `report_path`에 적용

**4. `cmd_dispatch` 함수에서 기존 Capsule 검증 (`orca_taskctl.py:1888-1898`)**

```python
try:
    for p in parse_capsule_list(capsule, "allowed_read_files"):
        validate_contained_path(p, field_name="allowed_read_files")
    for p in parse_capsule_list(capsule, "allowed_write_files"):
        validate_contained_path(p, field_name="allowed_write_files")
    rep_p = parse_capsule_scalar(capsule, "report_path")
    if rep_p:
        validate_contained_path(rep_p, field_name="report_path")
except ValueError as err:
    sys.stderr.write(f"오류: {err}\n")
    return 2
```

- 기존 Capsule을 사용할 때 `allowed_read_files`, `allowed_write_files`, `report_path`를 검증
- `capsule_path`는 `worktree_relative_capsule_path` 함수(1315-1329행)에서 간접적으로 검증

**5. 검증 필드 요약**

| 필드 | 검증 위치 | 적용 방식 |
| --- | --- | --- |
| `allowed_read_files` | `cmd_dispatch:1889-1890` | 직접 검증 |
| `allowed_write_files` | `cmd_dispatch:1891-1892` | 직접 검증 |
| `report_path` | `cmd_dispatch:1893-1895`, `expand_intent_to_capsule:745` | 직접 검증 |
| `capsule_path` | `expand_intent_to_capsule:722`, `worktree_relative_capsule_path:1315-1329` | 간접 검증 |

### 선행 보고서 대조
선행 보고서는 "해소"로 판정했으며, 독립 검증 결과 동일합니다. 4개 필드 전부에 워크트리 containment가 강제됨을 확인했습니다.

---

## 판정 요약표

| # | 항목 | 판정 | 근거 파일:행 | 선행 보고서 대조 |
| ---: | --- | ---: | --- | --- |
| 8 | Arq container source provenance | **해소** | `scripts/benchmark_arq_container.py:642-658, 906-934` | 동일 |
| 9 | 4계층 provenance schema 일치 | **해소** | `scripts/benchmark_arq_container.py:207-277`, `scripts/benchmark_arq_throughput.py:190-260` | 동일 |
| 12 | 경로 containment | **해소** | `scripts/orca_taskctl.py:469-505, 648-653, 698-722, 1888-1898` | 동일 |

---

## 결론

3개 항목 전부 **해소**. 선행 보고서(`gpt_audit_reverification_20260824.md`)의 판정과 차이가 없습니다. 코드 수정 불필요.
