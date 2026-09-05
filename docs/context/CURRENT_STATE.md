# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-09-04
> **source_commit**: `9d7fdce`
> **version**: 0.1.0 (`pyproject.toml` 이 SSoT)
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 현재 판정 | 다음 판정 조건 |
| --- | :---: | --- |
| G1 데이터 무손실 | 통과 (불변) | DB·가중치·벡터 무결성 유지 |
| G2 크로스 플랫폼 | 보류 | Windows Docker Desktop 실기 검증 |
| G3 스택 최적화 | 통과 | 전체 컷오버는 G2 확인 후 |

G1~G3의 세부 근거와 수치는 아래 기계 원장 및 보존 이력을 참조하십시오. CI Windows job은 정규 게이트이고 현재 병합 커밋의 결과는 푸시 후 재확인합니다.

## 2. 기계 검증 사실 (Machine Facts)

기계 판정의 입력은 [current_state_facts.yaml](current_state_facts.yaml)입니다. 각 항목은 상태, 주장, 문서 앵커, 증거 경로를 가지며 아래 서술과 원장이 다르면 검증이 실패합니다.

### closed 사실

- **gate_g1**: G1 데이터 무손실은 통과(불변)이며 MySQL 8 스키마·행 수, ML 가중치 체크섬, ChromaDB bidding_kb를 보존합니다.

- **gate_g3**: G3 스택 최적화 레이턴시 게이트는 전 항목 통과이며 전체 컷오버는 G2 확인 후입니다.

- **project_version**: 프로젝트 버전은 0.1.0이며 pyproject.toml이 SSoT이고 버전 표기를 통과 기준으로 유지합니다.

- **features_single_source**: Train/Serve 특징 생성은 src/ml/features.py 단일 함수만 사용하며 단일화 원칙을 통과 기준으로 유지합니다.

- **git_one_person**: 1인 작업 정책은 Pull Request 생성 금지와 main 직접 커밋 금지이며 규칙을 통과 기준으로 유지합니다.

- **prediction_gc_flag**: PREDICTION_GC_MODE=freeze를 정본 측정 설정으로 통과 유지합니다.

- **prediction_latency**: 예측 API 정본 P95는 c1 15.03ms·c2 19.66ms·c4 32.77ms·c10 48.14ms이며 모두 통과입니다.

- **rag_sse_latency**: RAG SSE 정본은 첫 토큰 P95 2664.19ms·전체 P95 3353.98ms로 목표를 통과했습니다.

- **rag_quality**: RAG 품질 정본은 blind_fixture_v2 96요청에서 numeric 144/144·evidence recall 1.0000·citation 72/72·refusal 24/24·과잉응답 0으로 통과했습니다.

- **servc_oos**: Servc Champion OOS 3,589건 MAE는 1.1825이며 즉시 재학습 근거가 없어 현 모델을 통과 상태로 유지합니다.

- **ngram_edge_classes**: ngram 경계값 7 클래스 실측은 완료·종결되었고 보수적 false를 유지합니다.

- **coldsql_metric**: 콜드 SQL 총량은 게이트에서 제외하고 관찰 지표로 강등했습니다.

- **source_commit_protocol**: source_commit은 기본 브랜치 병합 커밋에서 함께 갱신하고 작업 브랜치에서는 경고로 낮추는 규약으로 통과 기준을 유지합니다.

- **premerge_gate**: main 병합 전에는 make check-all와 전량 테스트 증거를 확인하는 규칙을 통과 기준으로 유지합니다.

- **history_preservation**: CURRENT_STATE의 상세 로그와 과거 경위는 current_state_history.md로 보존하고 분리 상태를 통과 기준으로 유지합니다.

- **supply_chain_gate**: 공급망 스캔은 모두 차단 모드로 운영하며 CRITICAL 및 HIGH 취약점 차단 게이트를 통과 기준으로 유지합니다.

### active 사실

- **ci_windows**: CI Windows job은 continue-on-error 없이 정규 게이트로 통과 중이며 병합 후 결과 재확인을 진행합니다.

- **row_reconciliation**: 행 수 판정은 하한 검사이며 성장 데이터와 이행 원본 reconciliation은 미구현으로 개선을 추진합니다.

- **confirmation_token_redis**: 확인 토큰 소비 기록은 프로세스 지역 집합이고 Redis TTL 이전을 추진합니다.

- **model_swap_gap**: 서빙 모델 교체는 rename 사이 미세 부재 구간이 있어 심볼릭 링크 교체를 추진합니다.

- **promotion_status_check**: promote_model.py status의 레지스트리 차단 동작은 병합 후 검증을 진행합니다.

- **lexical_full_rerun**: 정확 제목 lexical 채널은 부분집합 지연을 줄였고 전량 재측정을 진행합니다.

- **missing_lwlt_intervals**: missing_lwlt 집단은 MAE 2.0943으로 결측 집단 전용 예측구간 관리를 추진합니다.

- **state_budget**: CURRENT_STATE 부팅 요약은 facts.yaml과 history.md를 참조하고 8,000자 이하를 목표로 진행합니다.

### blocked 사실

- **gate_g2**: G2 크로스 플랫폼은 보류이며 Windows Docker Desktop 실기 검증은 미검증입니다.

- **ngram_flag**: NGRAM_PREFILTER_ENABLED=false이며 true 전환과 운영 FULLTEXT 인덱스 생성은 사용자 승인 전 보류입니다.

- **ssr_e2e**: SSR E2E Phase 2~4는 범위 조사만 끝났고 착수는 사용자 합의 대기입니다.

- **rpo_rto**: RPO/RTO와 정기 백업 스케줄·restore drill은 미정이며 담당자 결정을 대기합니다.

- **observability**: 관측성 스택은 후보만 있고 담당자 결정을 대기합니다.

- **drift_job**: 드리프트 job은 baseline이 생길 때까지 꺼져 있으며 재학습 후 활성화를 대기합니다.

- **coldsql_rerun**: RAG 정형 질의 cold SQL은 최대 97,087.81ms이며 재측정을 대기합니다.

### rejected 사실

- **ngram_prefilter**: ngram 선행필터 자체가 기각되고 운영 FULLTEXT 인덱스도 제거되었습니다.

- **servc_lwlt_imputation**: 낙찰하한율 추정 대입은 오차가 7~12%p 폭증해 기각되었고 결측 집단은 별도 모집단입니다.

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- **Windows Docker Desktop 실기 (2026-09-03, 미검증)**: 장비 확보 후 Compose healthy, 예측 API, 마이그레이션을 확인합니다.
- **SSR E2E Phase 2~4 (2026-09-03, 대기)**: 사용자 합의 후 DB 격리와 시나리오를 착수합니다.
- **RPO/RTO·백업 (2026-09-03, 대기)**: 주기와 restore drill 담당자 결정을 기다립니다.
- **관측성 스택 (2026-09-03, 대기)**: 후보 중 하나를 확정해야 합니다.
- **RAG cold SQL (2026-09-03, 미검증)**: 최대 97,087.81ms 경로의 재측정이 필요합니다.
- **lexical 전량 재측정 (2026-09-03, 진행)**: 부분집합 효과를 전량 fixture로 확인합니다.
- **금액 집계 성능 (2026-09-04, 진행)**: `agency_top10` 웜 31.97초. `base_amount` 컬럼 전환 시 6초로 줄지만 컬럼과 파싱값 불일치 343건의 정체 확인이 남았습니다.
- **KB 정합성 검사 기준 (2026-09-04, 미결)**: 검사는 낙찰 기준, 색인은 공고 기준이라 대응 공고가 없는 103건이 구조적으로 실패합니다.

### 6.2 정본 갱신 규약 (Update Protocol)

- 운영 지표·게이트·불변 사실이 바뀌면 같은 커밋에서 [CURRENT_STATE.md](CURRENT_STATE.md)와 [current_state_facts.yaml](current_state_facts.yaml)을 함께 갱신합니다.
- 상세 측정 로그와 과거 경위는 [current_state_history.md](current_state_history.md)로 옮기며 사실을 삭제하지 않습니다.
- **정규화 목표 바이트 수: 12,000바이트 이하(문자 수 8,000자 이하)**입니다. 현재 문서는 7,930바이트·5,013자이며, 기존 50,692바이트에서 판정 사실만 부팅 요약에 남기고 상세 로그를 이력으로 분리했습니다.
- 진실 우선순위는 실제 코드·실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff입니다.

## 7. 증거 경로 참조 (Evidence Pointers)

- 기계 원장: [docs/context/current_state_facts.yaml](current_state_facts.yaml)
- 상세 로그·과거 경위: [current_state_history.md](current_state_history.md)
- 컷오버·레이턴시 규약: [latency_gate_protocol.md](../ops/latency_gate_protocol.md), [phase7_cutover_declaration_20260901.md](../ops/phase7_cutover_declaration_20260901.md)
- 현재 잔여 과업: [handoff_20260904_docker_check_and_amount_integrity.md](../ops/handoff_20260904_docker_check_and_amount_integrity.md)
- 공고 금액 이상치·오버플로우: [announcement_amount_outliers_20260904.md](../ops/announcement_amount_outliers_20260904.md)
- 데이터·특징 불변성: [db_migration_runbook.md](../migration/db_migration_runbook.md), [features.py](../../src/ml/features.py)
