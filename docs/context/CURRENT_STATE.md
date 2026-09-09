# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-09-09
> **source_commit**: `2a4eac0`
> **version**: 0.1.0 (`pyproject.toml` 이 SSoT)
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 현재 판정 | 다음 판정 조건 |
| --- | :---: | --- |
| G1 데이터 무손실 | 통과 (불변) | DB·가중치·벡터 무결성 유지 |
| G2 크로스 플랫폼 | 보류 | Windows Docker Desktop 실기 검증 |
| G3 스택 최적화 | 통과 | 전체 컷오버는 G2 확인 후 |

G1~G3의 세부 근거와 수치는 아래 기계 원장 및 보존 이력을 참조하십시오. CI Windows job은 정규 게이트로 통과 상태를 유지합니다(Run 33947859707, fa1202f).

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

- **rag_segments_canonical**: RAG 구간 정본은 버퍼풀을 비운 콜드 조건 96요청 전량 성공으로 canonical 게이트를 통과했고 1차의 10만 ms 대 값은 버퍼풀로 설명되지 않습니다.

- **source_commit_protocol**: source_commit은 기본 브랜치 병합 커밋에서 함께 갱신하고 작업 브랜치에서는 경고로 낮추는 규약으로 통과 기준을 유지합니다.

- **premerge_gate**: main 병합 전에는 make check-all와 전량 테스트 증거를 확인하는 규칙을 통과 기준으로 유지합니다.

- **history_preservation**: CURRENT_STATE의 상세 로그와 과거 경위는 current_state_history.md로 보존하고 분리 상태를 통과 기준으로 유지합니다.

- **supply_chain_gate**: 공급망 스캔은 모두 차단 모드로 운영하며 CRITICAL 및 HIGH 취약점 차단 게이트를 통과 기준으로 유지합니다.

- **ci_windows**: CI Windows job은 continue-on-error 없이 정규 게이트로 통과 상태를 유지합니다 (GHA Run 33947859707, fa1202f 실측).

- **row_reconciliation**: 행 수 판정은 하한 검사 및 성장 데이터와 이행 원본 reconciliation 분리 대조로 완료 상태를 유지합니다.

- **confirmation_token_redis**: 확인 토큰 소비 기록은 Redis TTL 원자적 단일 소비(SET NX EX)로 완료 상태를 유지합니다.

- **promotion_status_check**: promote_model.py status의 레지스트리 차단 동작은 쌍대 기각 검증 통과 상태를 유지합니다.

- **model_swap_gap**: 서빙 모델 교체는 rename 사이 미세 부재 구간을 해소했고 세대 디렉터리와 LIVE 포인터 os.replace 교체로 완료했습니다.

- **state_budget**: CURRENT_STATE 부팅 요약은 facts.yaml과 history.md를 참조하고 8,000자 이하 목표를 통과했습니다.

### active 사실

- **kb_index_memory**: KB 색인 메모리 폭주는 Wave AP 전량 병합(4e40bd1) 후 재측정에서 단일 색인 피크 4,323MB 로 959초에 정상 완료해 AP4 판정 기준 3항을 모두 충족했습니다.

- **lexical_full_rerun**: 정확 제목 lexical 채널은 부분집합 지연을 줄였고 전량 재측정을 진행합니다.

- **missing_lwlt_intervals**: missing_lwlt 집단은 MAE 2.0943으로 결측 집단 전용 예측구간 관리를 추진합니다.

- **rpo_rto**: RPO 24시간·RTO 4시간을 확정했고 RPO/RTO와 정기 백업 스케줄은 일 1회 스냅샷으로 충족하며 분기 1회 restore drill 실시를 추진합니다.

- **drift_job**: 드리프트 감시는 Servc baseline(b_20260906_servc_post_regime) 기준으로 진행 중(ML_DRIFT_MONITOR_ENABLED 기본값 True)이며, Thng baseline은 없어 해당 모델만 예외 없이 건너뛰고 INSUFFICIENT_DATA로 기록합니다.

- **coldsql_rerun**: RAG 정형 질의 cold SQL 재측정(2026-09-06, 버퍼풀 콜드)은 sql 구간 콜드 P50 86,539.54ms·콜드 max 101,496.91ms·웜 P50 62.02ms·웜 max 1,015.64ms이며 콜드 표본 2건으로 측정 상태는 partial이고 이전 관찰치 97,087.81ms와 같은 계열이 재현됐으나 canonical 게이트 4건 미충족이라 정본 수치가 아니며 정본 측정을 추진합니다.

### blocked 사실

- **gate_g2**: G2 크로스 플랫폼은 보류이며 Windows Docker Desktop 실기 검증은 미검증입니다.

- **ngram_flag**: NGRAM_PREFILTER_ENABLED=false이며 true 전환과 운영 FULLTEXT 인덱스 생성은 사용자 승인 전 보류입니다.

- **ssr_e2e**: SSR E2E Phase 2~4는 범위 조사만 끝났고 착수는 사용자 합의 대기입니다.

- **observability**: 관측성 스택은 Collector·Tempo·Grafana 로 확정했고 2단계 Prometheus 는 메트릭 계측 후 착수합니다.

### rejected 사실

- **ngram_prefilter**: ngram 선행필터 자체가 기각되고 운영 FULLTEXT 인덱스도 제거되었습니다.

- **servc_lwlt_imputation**: 낙찰하한율 추정 대입은 오차가 7~12%p 폭증해 기각되었고 결측 집단은 별도 모집단입니다.

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- **Windows Docker Desktop 실기 (2026-09-03, 미검증)**: 장비 확보 후 Compose healthy, 예측 API, 마이그레이션을 확인합니다.
- **SSR E2E Phase 2~4 (2026-09-03, 대기)**: 사용자 합의 후 DB 격리와 시나리오를 착수합니다.
- **RPO/RTO 복구 목표 (2026-09-06, 확정)**: RPO 24시간·RTO 4시간을 확정했습니다. 분기 1회 restore drill 실시가 남았습니다.
- **워커 런처 계열 (2026-09-08, 해소)**: 런처 테스트의 실제 프로세스 부작용, 자동 승인 감시기 자기 종료, preamble 인계 규약 공용화, claude/opencode/grok 런처 신설, dispatch 런처 자동 선택을 Wave AM/AN 8건으로 닫았습니다. 사용 CLI 7종 중 6종이 `dispatch --launcher` 정규 경로에 있습니다(codex 는 구조가 달라 대상 아님).
- **자동 승인 화이트리스트 (2026-09-08, 판단 대기)**: `pgrep`, 환경변수 접두 명령, `git add`/`git commit`, `orca orchestration send`, CLI `--help` 가 화이트리스트 밖이라 워커마다 사람 승인이 필요합니다. 열지 여부는 사용자 결정 사항입니다.
- **관측성 2단계 Prometheus (2026-09-06, 미착수)**: 1단계 Collector·Tempo·Grafana 배선은 `docker-compose.prod.yml` 에 들어갔고, 2단계는 메트릭 계측이 선행 조건입니다.
- **RAG cold SQL (2026-09-07, 정본 확보·1차 원인 미규명)**: 버퍼풀을 실제로 비운 뒤(121,120 -> 1,192 페이지) 타임아웃 300초로 측정해 96요청 전량 성공으로 canonical 게이트를 통과했습니다(`rag_segments_coldpool_20260907.json`, sql 구간 콜드 P50 11.9ms·max 69.3ms). 콜드 버퍼풀 실행이 가장 빨라 1차의 10만 ms 대 값은 버퍼풀로 설명되지 않으며 원인은 미규명입니다. 재현 가능한 두 조건에서 근거가 없으므로 타임아웃 기본값 120초는 유지합니다.
- **lexical 전량 재측정 (2026-09-03, 진행)**: 부분집합 효과를 전량 fixture로 확인합니다.
- **KB 색인 메모리 폭주 (2026-09-09, 해소)**: Wave AP 다섯 Task(AP1 청크 스트리밍, AP2 keyset 페이징과 세션 expunge, AP3 모듈 분할, AP4 실측, AP5 재시도 폭풍 차단)를 병합한 뒤 재측정해 단일 색인 피크가 10,762MB 에서 **4,323MB** 로 떨어졌고 959초에 정상 완료했습니다. `knowledge_base_status` 가 `ready` 로 갱신되어 증분 판정과 삭제 대상 계산이 실데이터에서 처음 검증됐습니다. 남은 것은 Docker Desktop 메모리 원복 후 재확인, `HEAVY_TASK_NAMES` 에 `run_schedule_catchup_task` 와 `nightly_schedule_task` 포함 검토, catchup 이 겹치지 않은 단독 조건 측정입니다.
- **스케줄 따라잡기 (2026-09-08, 해소)**: 이미 지난 매일 02:00 크론 슬롯을 놓쳤으면 기동 시 한 번 보충하도록 판정을 슬롯 기준으로 바꿨습니다(`80d7cb0`). 종전에는 경과 24시간 임계치만 봐서 19시간 경과 시점에 `threshold_not_exceeded` 로 거부했습니다. 쿨다운은 유지하며 재시작 반복 발화를 막습니다. 운영 발화를 실측 확인했습니다(`reason=missed_schedule`, `last_cron_slot=2026-09-08T02:00:00`).
- **금액 집계 성능 (2026-09-08, 실측 대기)**: 불일치 343건은 총액 차이 최대 107원으로 안전 판정됐고 코드는 `30aba4e` 에서 `base_amount` 컬럼으로 전환됐습니다. 전환 전 API 웜은 31.97초입니다. 전환 후 `GET /api/v1/bids/stats` 웜 레이턴시 실측만 남았습니다.

### 6.2 정본 갱신 규약 (Update Protocol)

- 운영 지표·게이트·불변 사실이 바뀌면 같은 커밋에서 [CURRENT_STATE.md](CURRENT_STATE.md)와 [current_state_facts.yaml](current_state_facts.yaml)을 함께 갱신합니다.
- 상세 측정 로그와 과거 경위는 [current_state_history.md](current_state_history.md)로 옮기며 사실을 삭제하지 않습니다.
- **정규화 목표 바이트 수: 12,000바이트 이하(문자 수 8,000자 이하)**입니다. 현재 문서는 7,930바이트·5,013자이며, 기존 50,692바이트에서 판정 사실만 부팅 요약에 남기고 상세 로그를 이력으로 분리했습니다.
- 진실 우선순위는 실제 코드·실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff입니다.

## 7. 증거 경로 참조 (Evidence Pointers)

- 기계 원장: [docs/context/current_state_facts.yaml](current_state_facts.yaml)
- 상세 로그·과거 경위: [current_state_history.md](current_state_history.md)
- 컷오버·레이턴시 규약: [latency_gate_protocol.md](../ops/latency_gate_protocol.md), [phase7_cutover_declaration_20260901.md](../ops/phase7_cutover_declaration_20260901.md)
- 현재 잔여 과업: [handoff_20260908_wave_am_an_session_close.md](../ops/handoff_20260908_wave_am_an_session_close.md) (10장이 남은 항목입니다)
- 공고 금액 이상치·오버플로우: [announcement_amount_outliers_20260904.md](../ops/announcement_amount_outliers_20260904.md)
- 데이터·특징 불변성: [db_migration_runbook.md](../migration/db_migration_runbook.md), [features.py](../../src/ml/features.py)
