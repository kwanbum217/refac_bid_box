---
name: platform-health-checklist
description: 배포 전, 큰 병합 뒤, 주간 점검에서 프로젝트 기능과 성능, 데이터 무손실을 같은 통과 기준으로 확인할 때 호출됩니다.
---

# platform-health-checklist (기능·성능 점검표)

> **작성일**: 2026-11-07
> **성격**: 통과 기준 정본. 실행 절차는 기존 스킬과 `scripts/` 를 가리킵니다.
> **기준값 출처**: [`docs/context/CURRENT_STATE.md`](../../../docs/context/CURRENT_STATE.md), [`docs/context/current_state_facts.yaml`](../../../docs/context/current_state_facts.yaml)
> **측정 규약**: [`docs/ops/latency_gate_protocol.md`](../../../docs/ops/latency_gate_protocol.md)

---

## 0. 이 스킬의 범위

| 담는 것 | 담지 않는 것 |
| --- | --- |
| 무엇을, 어떤 기준으로 통과로 보는가 | 도커 기동, 백업, 마이그레이션 실행 절차 |
| 항목별 확인 명령과 화면 경로 | 벤치마크 스크립트의 내부 구현 |
| 판정 표현과 결과 기록 양식 | 새로운 기준값의 정의 |

실행 절차는 아래 스킬을 그대로 따릅니다. 같은 절차를 이 문서에 다시 적지 않습니다.

| 작업 | 실행 정본 |
| --- | --- |
| 도커 기동, 헬스체크, 레이턴시 벤치마크 | [project-orchestrator](../project-orchestrator/SKILL.md) |
| E2E, P95 컷오버, 크로스 플랫폼 | [validation-cutover](../validation-cutover/SKILL.md) |
| DB 행 수·스키마, 가중치, ChromaDB 무손실 | [data-preservation](../data-preservation/SKILL.md) |
| 재학습, Champion/Challenger 승격 | [retraining-pipeline](../retraining-pipeline/SKILL.md) |
| 추론 싱글톤, RAG 캐싱 | [inference-rag-opt](../inference-rag-opt/SKILL.md) |

- 기준값은 `CURRENT_STATE.md` 와 사실 원장에 있는 값만 씁니다. 없는 항목은 **기준 미정**으로 적고 측정값만 기록합니다.
- 기준값이 바뀌면 같은 커밋에서 `docs/context/CURRENT_STATE.md` 와 `docs/context/current_state_facts.yaml` 을 함께 갱신합니다.
- `.env` 의 실제 값은 문서에 적지 않습니다.

## 1. 쓰는 때

| 계기 | 범위 | 선행 조건 |
| --- | --- | --- |
| `main` 병합 직전 (배포 전) | 기능 전체, 성능 게이트, 데이터 무손실 | `make check-all` 과 전량 테스트 증거 |
| 큰 병합 뒤 (모델·검색·API·인프라 변경) | 변경 영향 기능과 해당 성능 지표 | 영향 범위 표시 |
| 주간 점검 | 기능 전체, 성능 추세, 크론 상태, 원장 | 지난 기록과 같은 측정 조건 |

주간 점검은 같은 조건으로 반복합니다. 조건이 다른 회차는 추세 비교에 쓰지 않습니다.

## 2. 기능 점검 표

### 2.1 서비스 기반

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| 컨테이너 기동 | `make up` 후 `docker compose ps` | `app`·`db`·`redis`·`meilisearch` 가 healthy 이고 `worker` 가 실행 중 |
| 헬스 | `curl -fsS http://localhost:8000/api/v1/health` | HTTP 200, `status` 가 `healthy` |
| 레디니스 | `curl -fsS http://localhost:8000/api/v1/health/ready` | HTTP 200, `checks` 의 `mysql`·`redis`·`meilisearch`·`model_registry`·`chromadb` 가 모두 `ok` |
| 서빙 모델 버전 | `curl -fsS http://localhost:8000/api/v1/health/served-version` | `status` 가 `ok` 이고 인메모리와 디스크 승격본 버전이 일치 |

### 2.2 공고 탐색

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| 공고 목록 | 화면 `/bids/`, API `GET /api/v1/bids` | HTTP 200, 첫 페이지에 공고가 표시됨 |
| 공고 검색 | 화면 `/bids/?q=<검색어>`, API `GET /api/v1/bids?q=<검색어>` | HTTP 200, 검색 인덱스 불가(503)가 아님. 0건이면 `uv run python scripts/sync_search_index.py` 로 색인 상태를 확인 |
| 공고 상세 | 화면 `/bids/{pk}/`, API `GET /api/v1/bids/{pk}` | HTTP 200, 상세 본문과 분석 영역이 렌더됨 |

### 2.3 공고 상세 분석

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| 분석 모델 카드 | 화면 `/bids/{pk}/` 의 `AI 투찰 금액 분석기` 영역, API `GET /api/v1/predictions/list-models` | 모델명과 설명이 표시되고 모델 목록이 HTTP 200 |
| 투찰가 추천 | 화면 동일 영역의 `투찰가 추천 계산`, API `POST /api/v1/predictions/predict-price` | 추천 금액과 예측 낙찰률이 표시되거나, 계산 불가 사유가 안내됨. 5xx 가 아님 |
| 비슷한 진행 중 공고 | 화면 `/bids/{pk}/` 의 `비슷한 진행 중 공고` 목록 | 목록 또는 0건 안내가 표시되고 각 링크가 HTTP 200 |
| 과거 사례 | 화면 `/bids/{pk}/` 의 `과거 사례` 목록 | 목록 또는 0건 안내가 표시되고 각 링크가 HTTP 200 |
| 비예가 안내 | 화면 `/bids/{pk}/` 의 비예가 공고 표시 | `비예가라 예정가격이 없음` 안내가 표시됨. 빈 카드나 5xx 가 아님 |

### 2.4 결과·대시보드·챗봇

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| 낙찰 결과 목록 | 화면 `/bids/results/`, API `GET /api/v1/bids/results` | HTTP 200, 결과가 표시됨 |
| 낙찰 결과 상세 | 화면 `/bids/result/{pk}/`, API `GET /api/v1/bids/results/{pk}` | HTTP 200, 공고 연결과 상세 값이 표시됨 |
| 대시보드 | 화면 `/bids/dashboard/`, API `GET /api/v1/bids/stats` | HTTP 200, 집계 값이 표시됨(0 포함) |
| 공고 대비 비교 | 화면 `/bids/compare/`, API `GET /api/v1/bids/compare-stats` | HTTP 200, 비교 집계가 표시됨(0 포함) |
| 챗봇 화면 | 화면 `/chatbot/` | HTTP 200, 세션 사이드바와 입력창이 렌더됨 |

### 2.5 챗봇 점검 세트

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| fixture 형식·근거 실재성 | `uv run python scripts/validate_llm_quality_fixture.py data/eval/llm_quality_fixture_v2.json --quiet` | 종료 코드 0 |
| 질문 세트 스키마 | `uv run python scripts/measure_chat_user_questions.py --dry-run` | 종료 코드 0, HTTP·DB 미호출 |
| 질문 세트 실측 | `uv run python scripts/measure_chat_user_questions.py --limit 5` | 종료 코드 0, 실패 문항 0건. `heuristic: true` 문항은 답변을 직접 읽어 확정 |
| 품질 정본 측정 | `uv run python scripts/measure_llm_quality.py --fixture data/eval/llm_quality_fixture_v2.json --model-label <모델 라벨> --expected-model <OLLAMA_MODEL 값> --output <결과 JSON 경로>` | 종료 코드 0, `canonical` 이 true. 시작·종료 모델이 `--expected-model` 과 일치하고 작업 트리가 dirty 가 아님 |

- fixture 별 manifest: `llm_quality_fixture_v2.json` 은 `data/eval/llm_quality_evidence_manifest_v2.json`, v1 은 `data/eval/llm_quality_evidence_manifest.json` 을 기본으로 씁니다.
- v2 manifest 생성(정본 ChromaDB 가 있는 주 저장소에서): `uv run python scripts/build_llm_fixture_manifest.py --fixture data/eval/llm_quality_fixture_v2.json --chroma-db-path chroma_db/chroma.sqlite3`

### 2.6 크론·재학습·원장

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| 워커·스케줄 관측 | `curl -fsS http://localhost:8000/api/v1/health/worker`, `docker compose logs worker --tail 100` | `worker` 와 `queue` 가 null 이 아니고, `schedules` 에 `nightly_schedule`·`weekly_retrain`·`drift_monitor`·`result_coverage_monitor` 가 있으며 각 `success` 가 true |
| 첨부 판별 크론 | 위 `schedules` 의 `band_regime_daily` | `BAND_REGIME_SCHEDULE_ENABLED` 가 켜진 환경은 `success` 가 true, 꺼진 환경은 `해당 없음` 으로 기록 |
| 모델 레지스트리 상태 | `uv run python scripts/promote_model.py status` | 레지스트리 최신본과 서빙본을 비교한 결과가 출력되고 종료 코드 0 |
| 재학습 실행 | `uv run python scripts/retrain_servc_from_parquet.py` 또는 `POST /api/v1/automation/run/retrain` | 스크립트는 종료 코드 0 과 학습 지표 출력, API 는 작업 상태 `succeeded`. 승격은 쌍대 검증 뒤에만 수행 |
| 규칙 커버리지 원장 | `uv run python scripts/report_rule_coverage.py --check` | 출력의 `차이 0건`. 이 스크립트는 차이가 있어도 종료 코드 0 이므로 출력으로 판정 |
| 낙찰하한율 불일치 지표 | `uv run python scripts/report_lwlt_mismatch.py --check` | 종료 코드 0, 출력의 `차이 0건` |

두 `--check` 는 `--as-of YYYY-MM-DD` 가 없으면 기존 원장·지표의 창 끝 날짜를 기준일로 씁니다. 원장을 만든 날과 같은 창으로 다시 계산하므로, 날짜가 바뀌었다는 이유만으로는 차이가 나지 않습니다. 다른 날짜로 비교하려면 `--as-of` 를 명시합니다.

재학습·승격의 상세 절차는 [retraining-pipeline](../retraining-pipeline/SKILL.md) 을 따릅니다. 크론 등록 시각과 태스크 이름은 `src/tasks/worker.py` 의 `cron_jobs` 가 정본입니다.

## 3. 성능 점검 표

기준값은 `CURRENT_STATE.md` 와 사실 원장에 기록된 값만 씁니다. 고정 기준이 없는 항목은 **기준 미정**으로 적고 정본 기록값과 비교합니다.

| 지표 | 측정 명령 | 기준값 (출처) | 측정 함정 |
| --- | --- | --- | --- |
| 예측 API c10 P95 | `make benchmark` 또는 `uv run python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000` | 100ms 이하 (CURRENT_STATE `slo_alerts`). 정본 기록값 c10 48.14ms (`prediction_latency`) | 회차당 표본 600 이상, 3회 반복 최악값, warmup 제외. `PREDICTION_GC_MODE=freeze` 확인 |
| 예측 API 100ms 초과율 | 위 벤치마크의 `predict_keepalive`(연결 재사용) 초과율 | 0.5% 이하 (CURRENT_STATE `slo_alerts` 벤치마크 게이트) | 표본 600 미만은 판정 불가. Wilson 상한을 함께 기록. 새 연결 초과율은 보조 지표로 함께 기록 |
| 예측 API c1·c2·c4 P95 | 위 벤치마크 | 기준 미정. 정본 기록값 c1 15.03ms·c2 19.66ms·c4 32.77ms (`prediction_latency`). 회귀 감시는 `docs/ops/latency_gate_protocol.md` 4.2·4.3 | c10 최적화의 부작용 감시 지점이며 절대 기준이 아님 |
| RAG SSE 첫 토큰 P95 | `uv run python -m scripts.benchmark_sse_gate --concurrency 1 --rounds 60 --round-num <회차>` | 3초 이하 (CURRENT_STATE `slo_alerts`). 정본 기록값 2664.19ms (`rag_sse_latency`) | 순차(c1) 측정값. c2 이상에 3초를 적용하지 않음. 회차당 60 이상 |
| RAG SSE 전체 P95 | 위 SSE 벤치마크 | 20초 이하 (CURRENT_STATE `slo_alerts`). 정본 기록값 3353.98ms (`rag_sse_latency`) | 동시성 수준별 기준은 아직 없음. c1 값만 판정에 씀 |
| RAG 품질 | `uv run python scripts/measure_llm_quality.py --fixture data/eval/llm_quality_fixture_v2.json --model-label <모델 라벨> --expected-model <OLLAMA_MODEL 값> --output <결과 JSON 경로>` | 정본 기록값은 blind_fixture_v2 96요청 numeric 144/144, evidence recall 1.0000, citation 72/72, refusal 24/24, 과잉응답 0 (`rag_quality`) | `--expected-model` 필수. dirty 트리는 canonical=false. proposition 은 자동 채점하지 않음 |
| 웜 비교 통계 | `uv run python scripts/benchmark_compare_stats.py --base-url http://127.0.0.1:8000` | 기준 미정. 정본 기록값 `/api/v1/bids/stats` 3.34ms(P95 3.80ms) (`compare_stats_latency`), compare-stats 종단 4.9ms (`compare_stats_snapshot`) | 콜드 SQL·캐시 미적중은 게이트가 아님(`coldsql_metric`). 버퍼풀 크기와 DB 가동 시간 기록 |
| Servc Champion OOS MAE | `uv run python scripts/eval_servc_oos_champion.py` | 기준 미정. 정본 기록값 3,589건 MAE 1.1825 (`servc_oos`) | 표본 수·컷오프 고정. 특징은 `src/ml/features.py` 단일 함수만 사용 |
| 콜드 SQL 총량 | `uv run python scripts/benchmark_rag_segments.py` 또는 `uv run python scripts/measure_coldsql_attribution.py` | 게이트 아님. 관찰 지표로만 기록 (`coldsql_metric`) | 버퍼풀 크기·DB 연속 가동 시간 명시, 대규모 DDL 직후 측정 금지, 동일 조건 3회 변동폭 기록 |

### 3.1 측정 조건 공통 규칙

- 표본·warmup·반복·대표값 규칙은 [`docs/ops/latency_gate_protocol.md`](../../../docs/ops/latency_gate_protocol.md) 1~3장을 따릅니다. 조건을 만족하지 못한 측정은 **판정 불가**로 기록합니다.
- 계측 활성 측정은 게이트 근거가 아닙니다. 주변 부하를 실측해 기록하고, 임계를 넘은 회차는 버립니다.
- 설정이 서버에 실제로 닿았는지 확인합니다. `${VAR:-기본값}` 표기는 빈 문자열을 기본값으로 되돌리므로 비교 측정에서 설정이 꺼지지 않을 수 있습니다.
- `통과 추정` 같은 표현을 쓰지 않습니다. 근거가 빠지면 `미달` 또는 `판정 불가` 입니다.
- 성능 개선 판정은 쌍대 비교와 홀드아웃 설계를 따릅니다. 절차는 [servc-model-tuning](../servc-model-tuning/SKILL.md) 을 참고합니다.
- 사용자 API 한도(60초 120요청)에 걸리는 측정은 `RATE_LIMIT_EXEMPT_USERNAMES` 에 측정 계정만 넣고 `app` 을 재시작한 뒤 측정합니다. 끝나면 값을 비우고 다시 재시작합니다. `ENVIRONMENT=production` 에서는 이 값이 무시됩니다.
- `benchmark_latency.py` 는 측정 쿠키를 예측 요청에만 붙여 SSE·단발 질의는 익명 한도(60초 30회)에 걸립니다. SSE 판정은 쿠키를 받는 `python -m scripts.benchmark_sse_gate` 로 합니다. 스크립트 경로(`python scripts/benchmark_sse_gate.py`)로 부르면 `scripts` 모듈을 찾지 못해 실행되지 않습니다.
- 초과율은 연결 재사용(`predict_keepalive`)으로, P95 는 새 연결(`predict`)로 판정합니다(2026-11-14 사용자 결정). 브라우저는 연결을 재사용하고, 새 연결 경로의 100ms 초과는 Docker Desktop 호스트 포트 전달 비용(연결당 약 4ms)에서 나오기 때문입니다. P95 는 정본 기록값과의 연속성 때문에 새 연결을 유지합니다. 새 연결 초과율은 환경 변화를 감시하는 보조 지표로 계속 기록합니다.

## 4. 데이터 무손실 점검

| 점검 항목 | 확인 방법 | 통과 기준 |
| --- | --- | --- |
| DB 스키마·행 수 | `make migrate-verify` | 종료 코드 0, 스키마와 행 수가 100% 보존됨 (G1) |
| 모델·서빙 특징 호환 | `make model-verify` | 종료 코드 0, 직렬화 버전과 서빙 특징이 호환됨 |
| 백업 스냅샷 무결성 | `make backup-verify` | 종료 코드 0, 최신 스냅샷 체크섬이 일치함. 스냅샷이 없으면 `make backup` 또는 `make backup-dry-run` 상태를 먼저 기록 |
| G1 자산 테스트 | `make test-data-assets` | 종료 코드 0. 격리 워크트리는 아래 예외 2건만 실패하면 정상으로 기록 |

- 상세 절차와 자산 체크섬 기준은 [data-preservation](../data-preservation/SKILL.md) 과 `docs/migration/db_migration_runbook.md` 를 따릅니다.
- 격리 워크트리에서는 `data/model_files` 와 `chroma_db` 가 없어 `tests/test_data_preservation.py` 의 `test_model_bin_files_exist`·`test_chroma_db_exists` 2건이 실패할 수 있습니다. 이 실패는 정상이며, 주 저장소 자산을 복사하거나 심볼릭 링크로 끌어오지 않습니다.

## 5. 결과 기록 양식

### 5.1 점검 요약

| 기록 항목 | 값 |
| --- | --- |
| 점검일 | |
| 브랜치 / 커밋 | |
| 점검 계기 | 배포 전 / 큰 병합 뒤 / 주간 점검 |
| 실행 환경 | OS, Docker, 모델 |
| 기능 판정 | 통과 / 미달 / 해당 없음 |
| 성능 판정 | 통과 / 미달 / 판정 불가 |
| 데이터 무손실 판정 | 통과 / 미달 / 판정 불가 |
| 종합 판정 | 통과 / 미달 / 판정 불가 |

### 5.2 항목별 기록

| 항목 | 측정값 | 기준값 / 출처 | 판정 | 증거 경로 |
| --- | --- | --- | --- | --- |
| | | | | |

- 판정이 `미달` 이면 실패 항목과 재현 명령을 함께 적습니다.
- 판정이 `판정 불가` 이면 충족하지 못한 측정 조건을 적습니다.
- 증거는 `data/benchmarks/` 의 원시 파일이나 로그 경로로 남깁니다.
- 같은 조건의 직전 기록과 비교해 악화 여부를 적습니다.

## 6. 갱신 규약

- 이 스킬은 기준값을 새로 만들지 않습니다. 기준의 정본은 `CURRENT_STATE.md` 와 `current_state_facts.yaml` 입니다.
- 명령이나 화면 경로가 바뀌면 `Makefile`, `scripts/` 의 argparse, `src/app/api/ui.py` 를 먼저 확인한 뒤 이 문서를 고칩니다.
- 스킬 정본을 고친 뒤 `python3 scripts/sync_skill_mirrors.py` 로 미러를 갱신하고 `--check` 로 일치를 확인합니다.
