# Arq 벤치마크 Provenance 공통화 및 Redis 결박 Fail-Closed 개선

> **작성일**: 2026-08-24
> **관련 감사 항목**: P1-1 (Provenance 단일화), P1-5 (Redis 컨테이너 명시 결박)
> **대상 모듈**: `scripts/benchmark_provenance.py`, `scripts/benchmark_arq_container.py`, `scripts/benchmark_arq_throughput.py`, 관련 테스트
> **상태**: 구현 및 검증 완료

---

## 1. 개요 및 배경

외부 감사 항목 P1-1 과 P1-5 입니다.

1. **P1-1 (Provenance 헬퍼 단일화)**: `build_provenance_dict`, `get_git_status`, `get_host_memory` 가 두 Arq 벤치마크 하네스(`benchmark_arq_container.py`, `benchmark_arq_throughput.py`)에 각각 복사되어 있어, 한쪽만 수정되면 조용히 갈라지는 중복 상태였습니다.
2. **P1-5 (Redis 컨테이너 명시 결박)**: 두 하네스의 `inspect_redis_container` 가 `docker ps --filter name=redis` 의 **첫 번째 결과를 무조건 채택**하고, 조회 예외가 나면 전 필드를 `unknown` 으로 채운 채 성공으로 반환했습니다. 다른 프로젝트 Redis 가 함께 떠 있으면 실제 측정 대상과 다른 컨테이너의 identity 가 provenance 에 기록될 수 있고, 조회 실패를 조용히 삼키는 문제가 있었습니다.

본 작업은 provenance 헬퍼를 공통 모듈로 단일화하고, Redis 대상 선택을 **명시 지정 + fail-closed** 로 바꿉니다.

---

## 2. 변경 사항

### 2.1 공통 모듈 단일화 (`scripts/benchmark_provenance.py`)

다음 함수를 공통 모듈로 이동하고 두 하네스가 `import` 하도록 변경했습니다. 하네스의 자체 `def` 는 제거했습니다.

| 함수 | 이동 대상 | 두 하네스에서 중복 제거 여부 |
| --- | --- | --- |
| `build_provenance_dict` | 공통 모듈 | 제거 |
| `get_git_status` | 공통 모듈 | 제거 |
| `get_host_memory` | 공통 모듈 | 제거 |

- `benchmark_provenance.py` 의 기존 `is_source_dirty` 를 `get_git_status` 가 재사용합니다 (단일 구현 유지).
- 하네스별 차이가 있었던 부분(예: container 하네스는 `network` 키 사용)은 공통 `build_provenance_dict` 에서 하네스가 넘기는 인자(`worker_container_id` 등)로 분기·구분되며, 함수 본문을 복제하지 않습니다.

### 2.2 Redis 대상 선택 명시화 및 fail-closed (`resolve_redis_container`)

공통 모듈에 `resolve_redis_container(redis_url, target, strict, ...)` 를 추가했습니다. 두 하네스의 `inspect_redis_container` 는 이 함수에 위임하는 얇은 어댑터가 되었습니다.

**동작 변경:**

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 후보 선택 | `name=redis` 첫 줄 무조건 채택 | `--redis-container` 로 명시 지정 가능. 미지정 시 `name=redis` 후보가 **정확히 1개일 때만** 채택 |
| 후보 모호/부재 | 조용히 첫 줄 또는 `unknown` | 0개 또는 2개 이상이면 `BuildProvenanceError` 로 **자동 선택 없이 중단** |
| 조회 예외 | `unknown` 채우고 성공 반환 | `BuildProvenanceError` 로 **중단 (흡수 금지)** |
| `redis_url` 대응 | 미검증 | strict 모드에서 선택된 컨테이너의 발행 호스트 포트와 `redis_url` 의 호스트/포트가 대응하는지 검증. 대응 불가 시 fail-closed |

명시 대상은 컨테이너 이름/ID 또는 docker compose 서비스명(`docker compose ps -q <service>` 로 해석)을 지원합니다. 두 하네스에 `--redis-container` CLI 인자를 추가했습니다.

### 2.3 스키마 동등성 유지

공통화 이후에도 두 하네스의 provenance JSON 키 집합과 값 의미는 이전과 동일합니다. `test_provenance_schema_equality_between_inprocess_and_container` 테스트가 키 집합 동등성을 결박합니다.

---

## 3. 검증 결과

```bash
uv run pytest tests/test_benchmark_provenance.py tests/test_benchmark_arq_container.py tests/test_benchmark_arq_throughput.py -q
# 85 passed
```

```bash
uv run pytest tests/ -q -m 'not data_assets'
# 1932 passed, 6 skipped, 3 deselected
```

```bash
python3 scripts/validate_agent_rules.py --quiet
# 12/12 건 전량 PASS
```

```bash
uv run ruff check <수정된 6개 파일>
# All checks passed
```

신규 테스트:
- `test_redis_url_mismatch_fail_closed` — `redis_url` 과 컨테이너 발행 포트 불일치 시 중단
- `test_ambiguous_candidates_fail_closed` — 후보 2개 이상 시 자동 선택 없이 중단
- `test_zero_candidates_fail_closed` — 후보 0개 시 중단
- `test_lookup_exception_not_swallowed` — 조회 예외를 unknown 성공으로 흡수하지 않음
- `TestCommonHarnessHelpers` — 공통 모듈로 이동한 헬퍼 동작 및 4계층 스키마 결박

---

## 4. 준수 확인

- 기존 DB 스키마·행 수·모델 가중치 변경 없음.
- `docker-compose.yml` 변경 없음.
- 새 Python 라이브러리 추가 없음 (표준 라이브러리만 사용).
- 이모지 사용 없음.
