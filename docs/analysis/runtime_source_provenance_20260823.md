# 벤치마크 런타임 소스 Provenance 결박 및 Dirty 소스 거부(Fail-Closed) 보고서

> **작성일**: 2026-08-23
> **우선순위**: P1 (Runtime Source Provenance & Integrity)
> **대상 모듈**: `scripts/benchmark_latency.py`, `scripts/benchmark_sse_gate.py`, `tests/test_benchmark_latency.py`, `tests/test_benchmark_sse_gate.py`
> **상태**: 구현 및 검증 완료

---

## 1. 개요 및 배경

`docker-compose.yml`에서 `app`과 `worker` 컨테이너는 호스트의 `./src`를 컨테이너 내부 `/app/src`로 bind mount합니다. 따라서 Docker 이미지 SHA가 동일하더라도 컨테이너 내부에서 실행되는 실제 Python 코드는 호스트 작업 트리(worktree)의 `src` 디렉터리 상태에 종속됩니다.

기존 벤치마크 하네스는 컨테이너 이미지 및 하네스 실행 저장소의 `git_sha`만을 결박하여 다음과 같은 공백이 존재했습니다:
1. `--target-container`로 다른 작업 트리가 띄운 컨테이너를 측정하는 경우, 하네스 저장소의 `git_sha`와 실제 실행 컨테이너의 소스 revision이 다를 수 있으나 이를 기록하지 못함.
2. bind mount된 소스 디렉터리에 미커밋 변경(dirty state)이 있더라도 이를 감지하지 못하고 오염된 상태로 측정치가 기록될 위험이 존재함.

본 작업에서는 컨테이너의 `/app/src` bind mount 호스트 경로 및 해당 작업 트리의 Git 상태(`target_source_git_sha`, `target_source_git_dirty`)를 provenance evidence에 기록하고, `strict` 모드에서 dirty 소스 감지 시 `BuildProvenanceError`로 측정을 즉시 거부(Fail-Closed, 종료 코드 2)하도록 개선했습니다.

---

## 2. 주요 구현 내용

### 2.1 Bind Mount 및 Git 상태 조회 로직 구현

1. **Host Source Mount 경로 추출 (`_parse_source_mount`)**:
   - `docker inspect -f '{{json .Mounts}}' <container_id>` 출력에서 `Destination`이 `/app/src`인 항목의 `Source`를 추출합니다.
   - `/app/src` 마운트가 없는 이미지 전용(image-only) 컨테이너의 경우 `None`을 반환하여 `null`로 기록합니다.

2. **Worktree Revision 및 Dirty 여부 추출**:
   - `target_source_mount`가 존재하는 경우:
     - `git -C <target_source_mount> rev-parse HEAD`로 대상 소스 작업 트리의 커밋 SHA(`target_source_git_sha`)를 조회합니다.
     - `git -C <target_source_mount> status --porcelain`으로 미커밋 변경 유무(`target_source_git_dirty`)를 판별합니다.
   - `target_source_mount`가 `None`인 경우:
     - `target_source_git_sha = None`, `target_source_git_dirty = None`으로 기록됩니다.

3. **`_command_output` Porcelain 처리 개선**:
   - `git status --porcelain` 실행 결과 작업 트리가 깨끗할 때 빈 문자열(`""`)을 반환하므로, 기존의 `or "unknown"` 처리가 클린 상태를 `unknown`으로 왜곡하지 않도록 `status --porcelain` 질의에 대한 빈 문자열 허용 로직을 구현했습니다.

### 2.2 Strict 모드 Fail-Closed 거부

`reproducibility_metadata`에서 `strict=True`일 때:
- `target_source_mount`가 존재하는 경우:
  - `target_source_git_sha`가 `"unknown"`이거나 조회가 실패하면 `BuildProvenanceError` 발생.
  - `target_source_git_dirty`가 `True`이면 `BuildProvenanceError("Docker/Git provenance lookup failed or returned unknown for: target_source_git_dirty(...)")`를 발생시켜 측정을 거부하고 종료 코드 2로 중단합니다.
- `target_source_mount`가 `None`인 경우 (이미지 기반 컨테이너):
  - 거부하지 않고 정상 통과하며 `target_source_mount: null`로 기록합니다.

### 2.3 시작/종료 일관성 검증 결박 (`PROVENANCE_IDENTITY_KEYS`)

`verify_provenance_consistency`의 결박 대상 키 목록에 다음 3개 항목을 추가했습니다:
- `target_source_mount`
- `target_source_git_sha`
- `target_source_git_dirty`

측정 도중 소스 마운트가 바뀌거나 호스트 코드가 수정/커밋되는 경우 `verify_provenance_consistency`에서 감지되어 `BuildProvenanceError`가 발생하고 산출물 생성이 차단됩니다.

### 2.4 공용 정책 공유 (`scripts/benchmark_sse_gate.py`)

`scripts/benchmark_sse_gate.py`는 `scripts/benchmark_latency.py`의 `reproducibility_metadata`, `verify_provenance_consistency`, `BuildProvenanceError`를 그대로 공유하여 동일한 fail-closed 정책과 메타데이터 규약을 준수합니다.

---

## 3. 검증 결과

### 3.1 벤치마크 및 SSE 게이트 회귀 테스트

```bash
uv run pytest tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py -v
```

- **결과**: 45 passed in 10.26s
- **추가된 주요 검증 항목**:
  1. `test_reproducibility_metadata_bind_mount_clean_success`: Clean 상태의 bind mount 시 `target_source_mount`, `target_source_git_sha`, `target_source_git_dirty: False` 정상 기록 및 strict 통과.
  2. `test_reproducibility_metadata_bind_mount_dirty_rejected_in_strict_mode`: Dirty 상태 소스 시 strict 모드에서 `BuildProvenanceError` 발생 확인 및 non-strict 모드에서 dirty=True 기록 확인.
  3. `test_reproducibility_metadata_image_only_container_has_null_source_mount`: bind mount 없는 이미지 전용 컨테이너에서 strict 통과 및 `target_source_mount: null` 기록 확인.
  4. `test_benchmark_latency_main_fails_on_dirty_runtime_source`: main 실행 시 dirty 소스 감지로 종료 코드 2 반환 및 산출물 파일 생성 차단(fail-closed) 확인.
  5. `test_verify_provenance_consistency_detects_source_mount_and_git_changes`: 측정 도중 소스 마운트 경로, git sha, dirty 상태 변경 감지 시 strict 예외 발생 확인.
  6. `test_benchmark_sse_gate_main_fails_on_dirty_runtime_source`: SSE 게이트 main 실행 시 dirty 소스 감지 및 종료 코드 2 반환 확인.
  7. `test_sse_reproducibility_metadata_bind_mount_clean_and_image_only`: SSE 게이트에서 clean 및 이미지 전용 컨테이너의 메타데이터 규약 정합성 확인.

### 3.2 전체 테스트 스위트 및 규칙 검증

```bash
uv run pytest tests/ -q -m 'not data_assets'
python3 scripts/validate_agent_rules.py --quiet
```

- `pytest`: 1798 passed, 6 skipped, 3 deselected, 292 warnings in 97.59s
- `validate_agent_rules`: 12/12 건 전량 PASS

---

## 4. 결론 및 산출물 정합성

| 요구사항 | 구현 상태 | 확인 근거 |
| --- | --- | --- |
| 대상 컨테이너 /app/src bind mount host 경로 기록 | 완료 | `target_source_mount` 메타 필드 기록 |
| host worktree의 HEAD SHA 및 dirty 상태 기록 | 완료 | `target_source_git_sha`, `target_source_git_dirty` 필드 기록 |
| strict 모드에서 dirty 소스 측정 거부 | 완료 | `BuildProvenanceError` 발생 및 `main()` 종료 코드 2 반환 |
| bind mount 없는 이미지 전용 컨테이너 null 처리 | 완료 | `target_source_mount: null` 기록 및 strict 정상 통과 |
| 정상 clean, dirty 거부, mount 없음 회귀 테스트 | 완료 | 8건 신규 테스트 추가 (총 45건 pass) |
| benchmark_sse_gate.py 동일 정책 공유 | 완료 | `reproducibility_metadata` 및 fail-closed 동일 적용 |
| docker-compose.yml 및 기존 원시 증거 불변 유지 | 완료 | `docker-compose.yml`, `data/benchmarks/` 무변경 |
