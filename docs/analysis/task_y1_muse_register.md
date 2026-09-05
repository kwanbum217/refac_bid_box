# Meta Muse Spark 1.3 모델 풀 등록 및 가용성 검증 보고서

> **작성일**: 2026-09-05
> **태스크 ID**: `task_75828a01d336`
> **런 ID**: `run_febef4f1cee9`
> **담당**: Builder
> **정본 사양**: `.orca/capsules/task_y1_muse_register/capsule.yaml`

---

## 1. 작업 개요

Meta Muse Spark 1.3 모델을 `opencode` 무료 경로(`opencode/muse-spark-1.3-contributor-free`)를 통해 Orca 모델 풀(`scripts/orca_model_router.py`)에 등록했습니다.

사용자의 주요 워커 활용 수요를 충족하면서도 안전성을 확보하기 위해, 자동 배정(`auto_selectable`)은 비활성화(`False`)하고 수동 명시 지정(`--model opencode-muse-spark` 또는 `--model opencode/muse-spark-1.3-contributor-free`) 전용으로 배치했습니다. 정식 승격 및 자동 배정 편입 여부는 후속 `benchmarks/free_workers` 쓰기 경합 실측 결과에 따라 결정됩니다.

---

## 2. 모델 등록 사양

| 항목 | 설정값 | 비고 |
| --- | --- | --- |
| 풀 키 (별칭) | `opencode-muse-spark` | 기존 `opencode-<model>` 명명 규칙 준수 |
| 모델 ID | `opencode/muse-spark-1.3-contributor-free` | 무료 기여자 엔드포인트 |
| 제공자 (`provider`) | `opencode` | 기존 opencode CLI 하네스 활용 |
| 티어 (`tier`) | `free` | 무료 모델 티어 |
| 자동 배정 (`auto_selectable`) | `False` | 수동 명시 지정 전용 |
| 허용 역할 (`suitable_for`) | `builder`, `investigator` | 임계 경로인 `reviewer` 배정 엄격 제외 |
| 컨텍스트 (`max_tokens`) | `None` | 미확인 상태 유지 (보수적 접근) |
| 추론 등급 (`variant`) | `capability_unknown` | 임의 매핑 배제, 미검증 상태 보존 |

### 2.1 등록 및 운용 방침

1. **도구 사용 및 기본 응답 실측**: 코디네이터 사전 probe를 통해 기본 응답 및 도구 사용이 정상 동작함을 확인했습니다(파일 읽기 도구로 `pyproject.toml` 프로젝트명 조회 완료, 종료 코드 0).
2. **유료 경로 미등록**: `opencode-go/muse-spark-1.3-contributor`는 세션 쿠키 미설정으로 호출 불가 상태이므로 등록에서 제외했습니다.
3. **리뷰어 역할 배제**: 리뷰어는 병합 및 품질 판정에 직결되는 임계 경로이므로 무료 풀 항목인 Muse Spark 1.3의 `suitable_for`에서 제외했습니다.
4. **외부 미검증 벤치마크 수치 배제**: 공인되지 않은 외부 벤치마크 수치(DeepSWE, Terminal-Bench 등)는 인용하지 않았으며, 사실에 근거한 내용만 문서와 메타데이터에 기록했습니다.
5. **승격 조건**: `benchmarks/free_workers`의 쓰기 경합 실측 결과 통과를 유일한 승격 조건으로 명시했습니다.

---

## 3. 추론 등급(--variant) 판별 결과

`opencode run` 옵션 분석 결과 `--variant` 및 `--thinking` 플래그가 지원되는 것을 확인했습니다. 그러나 무료 엔드포인트 특성상 콜드스타트와 큐 지연이 길어 조율 프로세스의 동기적 실행 환경에서 과도한 대기를 유발했습니다.

이에 따라 Task Capsule 사양 및 코디네이터 지침에 의거하여, 검증되지 않은 추론 등급을 임의로 하드코딩하지 않고 `variant: capability_unknown`으로 안전하게 기록했습니다. 후속 배치 측정 시 격리 환경에서 별도로 정밀 분석을 수행할 예정입니다.

---

## 4. 검증 결과

<!-- METRICS_START -->
| 검증 항목 | 실행 명령 | 결과 | 판정 |
| --- | --- | --- | :---: |
| 라우터 단위 테스트 | `uv run pytest tests/test_orca_model_router.py -q` | 199 passed in 0.33s | PASS |
| 정적 타입 검사 | `uv run mypy src` | 93 files checked, 0 issues | PASS |
| 에이전트 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 passed | PASS |
| CLI 모델 목록 조회 | `python3 scripts/orca_model_router.py list` | `비대상 (수동 지정 전용)` 출력 확인 | PASS |
<!-- METRICS_END -->

### 4.1 회귀 방지 검증 세부사항

- `test_auto_selectable_pools_distinction`: `non_auto_pools`에 `opencode-muse-spark`가 포함되어 자동 선택 대상에서 완벽히 배제됨을 확인했습니다.
- `test_muse_spark_pool_registration`: 모델 ID, 프로바이더, 티어(`free`), 비자동선택(`False`), 허용 역할(`builder`, `investigator`) 및 리뷰어 제외를 검증했습니다.
- `test_provider_for_model_muse_spark`: `provider_for_model`과 `pool_for_model`이 풀 키 및 원본 ID를 모두 `opencode` 및 `opencode-muse-spark`로 정확히 매핑함을 확인했습니다.
- `test_probe_muse_spark_uses_opencode_cli`: probe 실행 시 `opencode run --model opencode/muse-spark-1.3-contributor-free ping` 명령 규격이 준수됨을 모의 하위 프로세스로 검증했습니다.
- `test_muse_spark_not_in_tier_policy_or_free_candidate_orders`: 기존 `TIER_POLICY` 및 `FREE_BUILDER_ORDER`, `FREE_INVESTIGATOR_ORDER`에 포함되지 않아, 등록 전후의 자동 배정 결과가 100% 동일함을 증명했습니다.
- `test_route_muse_spark_explicit`: 명시적 지정(`--model opencode-muse-spark`) 시 builder와 investigator 경로가 정상 라우팅됨을 검증했습니다.

---

## 5. 결론 및 향후 계획

Meta Muse Spark 1.3이 Orca 모델 풀에 성공적으로 등록되었으며, 기존 라우팅 체계 및 규칙과의 완벽한 정합성을 유지하고 있습니다.

후속 단계로 `benchmarks/free_workers`의 builder 과제 경합을 통해 실제 코드 생성 능력과 속도, 신뢰도를 실측한 후 정규 티어로의 편입 여부를 판단할 것을 권장합니다.
