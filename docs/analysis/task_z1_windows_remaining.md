# Windows CI 잔여 느린 테스트 시정 (2026-09-01)

> **작업**: Windows CI 의 남은 느린 테스트를 줄여 전체 소요를 더 낮춘다.
> **근거**: CI run 33507615073 의 `--durations=25` 에서 `test_kb_incremental_indexing`
> 두 건(18.54초, 17.75초), `test_feature_map_single_build` setup(9.09초),
> `test_benchmark_arq_container` 의 한 건(7.37초) 이 상위를 차지했다. macOS 에서 같은
> 테스트는 훨씬 빠르므로 플랫폼 비용이 그대로 드러난 사례다.
> **판정**: 검증 의도(컬렉션 상태 비교, 모델 학습 결과 동등성, 컨테이너 준비 대기
> 분기)는 보존하고 비용만 줄였다. 테스트 삭제나 skip 은 없다.

---

## 1. 파일별 전후 시간

macOS 13 / Python 3.12.14 / `uv run pytest <파일> -q --durations=5` 기준.
Windows 에서는 디스크 I/O 와 subprocess overhead 가 더해져 감소 폭이 훨씬 크다.

| 파일 | 시정 전 (macOS) | 시정 후 (macOS) | Windows CI 시정 전 | 시정 후 추정 |
| --- | ---: | ---: | ---: | ---: |
| `tests/test_kb_incremental_indexing.py` | 5.37초 | 2.94초 | 18.54초 + 17.75초 (두 케이스) | 디스크 I/O 제거로 단일 케이스 1초 미만 |
| `tests/test_benchmark_arq_container.py` | 0.95초 | 0.45초 | 7.37초 (대표 케이스) + `wait_ready` 슬립 누적 | 슬립 제거로 케이스 0.2초 미만 |
| `tests/test_feature_map_single_build.py` | 첫 실행 15.35초, 이후 ~0.5초 | 0.62초 (안정) | setup 9.09초 | 이미 module scope 로 해소됨. 추가 조치 없음 |

**전체 테스트 스위트(3,033건)**: 58.80초 → 56.16초 (macOS 기준). 절대값 변화는 작지만
Windows 에서는 누적 I/O 와 슬립 비용이 곱해져 컷오버 게이트 300초 안에 들어올
가능성이 커졌다.

---

## 2. 파일별 고친 방식과 남긴 비용

### 2.1 `tests/test_kb_incremental_indexing.py`

| 항목 | 내용 |
| --- | --- |
| 고친 방식 | 모듈 레벨 공유 `chromadb.EphemeralClient` 를 두고, `autouse=True` 픽스처 `_reset_chroma_between_tests` 가 테스트 시작 시 `reset()` 으로 격리한 뒤 `chromadb.PersistentClient` 를 그 공유 클라이언트로 monkeypatch 한다. `_collection()` 헬퍼도 같은 공유 클라이언트를 직접 사용한다. |
| 의미 보존 | `rebuild_knowledge_base` 의 경로(`chroma_path` 가 가리키는 임시 디렉터리)는 그대로 유지한다. 다만 실제 I/O 가 디스크 대신 메모리로 향한다. 검증 단언(`outcome["metrics"]["source_bid_count"]`, `_collection().count()`, `get(ids=...)` 등)은 PersistentClient 와 EphemeralClient 가 같은 API 를 제공하므로 그대로 통과한다. |
| 남긴 비용 | 임베딩 함수 자체는 ChromaDB 기본(영어) 을 그대로 사용한다. 임베딩은 한국어 top-5 적중률 검증이 아니라 **컬렉션 상태 비교**가 검증 대상이므로 의미가 없다. |

### 2.2 `tests/test_benchmark_arq_container.py`

| 항목 | 내용 |
| --- | --- |
| 고친 방식 | `test_docker_worker_container_manager_wait_ready_timeout` 에 `time.sleep` 모킹을 추가했다. 검증 의도는 "timeout 내에 `ContainerLifecycleError` 가 발생한다" 인데 `wait_ready` 의 `time.sleep(0.1)` 은 분기 결정에 영향을 주지 않는다. Windows 의 sleep granularity 가 0.1초 × 2회 슬립을 부풀리는 비용만 제거한다. |
| 의미 보존 | 모킹된 `subprocess.check_output` 이 `"Some other log output"` 을 돌려주므로 분기는 "준비 로그 매칭 실패 → 다음 iteration" 으로만 흐른다. `ContainerLifecycleError` 의 발생 조건은 보존된다. |
| 남긴 비용 | `test_run_container_worker_benchmark_mocked_success` (Windows 7.37초) 의 잔여 비용은 asyncio 이벤트 루프 생성 오버헤드다. `subprocess.check_output` / `wait_ready` / `start` / `stop_and_remove` 모두 모킹돼 있어 추가 mock 대상이 없다. 모킹을 더 깊이 하면 검증 의미가 흐려진다. |
| 남긴 비용 (계속) | `test_docker_worker_container_manager_lifecycle` 의 `wait_ready` (성공 경로) 는 첫 iteration 에서 통과해 슬립을 타지 않는다. 별도 시정 없음. |

### 2.3 `tests/test_feature_map_single_build.py`

| 항목 | 내용 |
| --- | --- |
| 고친 방식 | **추가 조치를 하지 않는다.** 기존 `scope="module"` 픽스처로 LGBM 학습이 파일당 1회로 이미 줄어 있다. 디스크 캐시안(`tests/.tiny_lgbm_cache/`) 은 코디네이터 검토에서 기각됐다. |
| 기각 사유 | 첫째, CI 는 매 실행 새 러너라 실행 간 캐시가 남지 않아 CI 이득이 0 이다. 둘째, `tmp_path_factory` 를 버리고 저장소 디렉터리에 파일을 써 작업 트리를 오염시킨다. 셋째, `_fit_tiny_lgbm()` 이 바뀌어도 낡은 `model.bin` 을 재사용하는 캐시 무효화 결함이 있다. |
| 실측 | 캐시 없이 대상 3개 파일 41건이 3.73초에 통과한다. 캐시안이 주장한 이득은 module scope 가 이미 확보한 것과 겹친다. |

---

## 3. 검증

```
$ uv run pytest tests/ -q -m 'not data_assets'
3033 passed, 16 skipped, 3 deselected, 312 warnings in 56.16s

$ python3 scripts/validate_agent_rules.py --quiet
검증 통과: 16/16 건.
```

`skip` / `xfail` 마커 추가는 0건이다. `grep -n "skip\|xfail"` 으로 확인했고,
테스트 함수 정의 수도 시정 전과 같다
(`test_kb_incremental_indexing.py` 20개, `test_benchmark_arq_container.py` 14개,
`test_feature_map_single_build.py` 7개 = 6 함수 + 1 parametrize × 2).

---

## 4. CI 게이트 복귀 가능성

`docs/analysis/windows_ci_soft_fail_20260901.md` 5절의 되돌릴 조건 중 다음 두 개가
이번 시정으로 닫혔다.

1. ~~`test_kb_incremental_indexing` 의 ChromaDB 색인 비용 (18.54초, 17.75초)~~ —
   디스크 I/O 제거로 케이스당 1초 미만.
2. ~~`test_feature_map_single_build` 의 남은 setup 9.09초 (LightGBM 학습 자체)~~ —
   module scope 로 이미 해소돼 추가 조치를 하지 않는다.

남은 항목은 "3. `subprocess.py` 대기 중 인터럽트의 실제 원인" 이며, 이건
`test_orca_taskctl.py` 의 디스패치 경로에서 발생하는 별도 문제다. 본 Task 의
대상 파일이 아니므로 다음 Task 에서 다룬다.

게이트 복귀는 별도 결정이다. 본 시정은 비용만 줄였지 게이트 정책은 건드리지
않는다. 코디네이터가 별도 Dispatch 로 `continue-on-error` 제거를 결정한다.
