# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-09-13
> **source_commit**: `6721981a`
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

- **supply_chain_gate**: 공급망 스캔은 모두 차단 모드로 운영하며, chromadb 3건(만료일 2026-12-31)의 allowlist 한시 예외를 두고 CRITICAL 및 HIGH 차단 게이트를 통과 기준으로 유지합니다.

- **ci_windows**: CI Windows job은 continue-on-error 없이 정규 게이트로 통과 상태를 유지합니다 (GHA Run 33947859707, fa1202f 실측).

- **row_reconciliation**: 행 수 판정은 하한 검사 및 성장 데이터와 이행 원본 reconciliation 분리 대조로 완료 상태를 유지합니다.

- **confirmation_token_redis**: 확인 토큰 소비 기록은 Redis TTL 원자적 단일 소비(SET NX EX)로 완료 상태를 유지합니다.

- **promotion_status_check**: promote_model.py status의 레지스트리 차단 동작은 쌍대 기각 검증 통과 상태를 유지합니다.

- **model_swap_gap**: 서빙 모델 교체는 rename 사이 미세 부재 구간을 해소했고 세대 디렉터리와 LIVE 포인터 os.replace 교체로 완료했습니다.

- **state_budget**: CURRENT_STATE 부팅 요약은 facts.yaml과 history.md를 참조하고 실측 7990자로 8,000자 이하 목표를 통과했습니다.

- **compare_stats_snapshot**: compare-stats 네 집계를 사전 집계 스냅샷으로 옮겨 캐시 미적중 종단이 3,725ms 에서 4.9ms 가 됐고 네 구간은 모두 0.00ms 입니다. 구조 차이는 확정이고 시간 차이는 산포 초과(참고)이며 이 경로 최적화를 완료했습니다.

- **compare_stats_attribution**: compare-stats 캐시 미적중 종단은 기관별 상위 10 집계 2,097ms(56.3%)와 매칭 건수 1,136ms(30.5%)가 87%를 차지하며 비 SQL 구간은 6ms 대입니다. 12회차 전량 유효 표본으로 귀속 측정을 완료했습니다.

- **kb_index_memory**: KB 색인 메모리 폭주는 Wave AP 전량 병합 후 재측정에서 해소를 확인했고 상한을 520,000 으로 올려 최근 1년 505,271건 전량을 삭제 없이 색인했습니다.

- **compare_stats_latency**: GET /api/v1/bids/stats 웜 레이턴시는 3.34ms(P95 3.80ms)입니다. compare-stats 실측을 완료했고 전환 전 웜 31.97초 대비 정상상태 6.5초로 완화를 통과 기준으로 유지합니다.

- **observability**: 관측성 스택은 Collector·Tempo·Grafana 로 확정했고 요청 지연·DB 질의 지연·요청 수 메트릭 계측은 병합했습니다. 2단계 Prometheus 스크랩과 HTTP/DB 지연 대시보드를 넣었고, 메트릭 켜짐 예측 API c10 최악 P95 는 56.74ms 로 100ms 한도를 통과했습니다.

- **slo_alerts**: 예측 API 운영 SLO 는 c10 P95 100ms 와 5xx 비율 0.1% 이며 SSE 전체 P95 20초를 라이브 알람으로 넣었고, SSE 첫 토큰 3초와 100ms 초과율 0.5% 는 벤치마크 게이트로 유지하며 통과 기준으로 둡니다.

- **rpo_rto**: RPO 24시간·RTO 4시간을 확정했고 RPO/RTO와 정기 백업 스케줄은 일 1회 스냅샷으로 충족하며 분기 1회 restore drill 정례화를 야간 점검으로 완료했습니다. 2026-09-11 로컬 단계 나눔 드릴이 통과했고(총 852.83초, G1 파일·DB 분리 검증 통과) 경과 80일 경고 임계와 판정 불가 fail-closed 를 기계로 강제합니다.

- **ssr_e2e**: SSR E2E 는 Playwright 기반으로 Phase 1~4 를 모두 구현했고 전용 CI Job 이 skip 0 을 요구하며 통과합니다. 대상은 인증과 공고·낙찰 화면, 챗봇 SSE 스트리밍, React SPA 이며 32건을 수집합니다.

- **servc_qualification_evaluation**: 일반용역 적격심사 정량평가는 전 계층을 병합했고 화면 범위 배지는 일반용역·기술용역·협상 세 분기를 모두 표시합니다. `src/app/templates/bids/detail.html` 의 `setEvaluationScopeBadge` 가 기본 문구, `negotiation_variant` 보유 시 협상 문구, `rule_id === 'SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT'` 시 기술용역 문구를 설정합니다. 배지 문구를 후속 과제로 두었던 기재는 구현 이후 갱신되지 않은 것이며 2026-09-11 에 코드로 확인해 종결했습니다.

- **ngram_flag**: NGRAM_PREFILTER_ENABLED 는 false 로 고정하며 기각된 선행필터의 영구 차단 스위치입니다. `ngram_prefilter` 사실이 rejected 이고 운영 FULLTEXT 인덱스도 제거된 상태라 true 전환은 승인 대상이 아닙니다. 승인 대기로 두었던 기재는 기각 판정 이후 갱신되지 않은 것이며 2026-09-11 에 종결했습니다.

### active 사실

- **negotiation_contract_support**: 협상 공고를 NEGOTIATION_CONTRACT 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율과 변종 식별자를 화면에 제공합니다. 가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했습니다.

- **mysql_stats_refresh_policy**: 영속 통계 신선도는 읽기 전용 점검 실행기로 판정하며 갱신 주기 채택은 코디네이터 결정 사항으로 남았습니다. innodb_stats_auto_recalc 가 ON 이고 테이블별 재정의가 없는데도 139.8% 편차가 열흘을 간 것을 확인했으며 주기 채택을 추진합니다.

- **lexical_full_rerun**: 정확 제목 lexical 채널은 부분집합 지연을 줄였고 전량 재측정을 진행합니다.

- **missing_lwlt_intervals**: missing_lwlt 집단은 MAE 2.0943으로 결측 집단 전용 예측구간 관리를 추진합니다.

- **drift_job**: 드리프트 감시는 Servc baseline(b_20260906_servc_post_regime) 기준으로 진행 중(ML_DRIFT_MONITOR_ENABLED 기본값 True)이며, Thng baseline은 없어 해당 모델만 예외 없이 건너뛰고 INSUFFICIENT_DATA로 기록합니다.

- **coldsql_rerun**: RAG 정형 질의 cold SQL 재측정(2026-09-06, 버퍼풀 콜드)은 sql 구간 콜드 P50 86,539.54ms·콜드 max 101,496.91ms·웜 P50 62.02ms·웜 max 1,015.64ms이며 콜드 표본 2건으로 측정 상태는 partial이고 이전 관찰치 97,087.81ms와 같은 계열이 재현됐으나 canonical 게이트 4건 미충족이라 정본 수치가 아니며 정본 측정을 추진합니다.

### blocked 사실

- **gate_g2**: G2 크로스 플랫폼은 보류이며 Windows Docker Desktop 실기 검증은 미검증입니다.

### rejected 사실

- **ngram_prefilter**: ngram 선행필터 자체가 기각되고 운영 FULLTEXT 인덱스도 제거되었습니다.

- **servc_lwlt_imputation**: 낙찰하한율 추정 대입은 오차가 7~12%p 폭증해 기각되었고 결측 집단은 별도 모집단입니다.

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- **Windows Docker Desktop 실기 (2026-09-03, 미검증)**: 장비 확보 후 Compose healthy, 예측 API, 마이그레이션을 확인합니다.
- **RAG cold SQL (2026-09-13, 원인 확정·개선 합의 대기)**: 날짜 없는 기관명 LIKE 가 31.6GB 공고 본문을 콜드로 읽습니다. 2단계 해석이 콜드 4배 빠름 ([rag_coldsql_root_cause_20260913.md](../analysis/rag_coldsql_root_cause_20260913.md)). 타임아웃 120초 유지.
- **손상 탐침 제거 (2026-09-11, 구조적 제거 확정·효과 크기 미확정)**: corrupted_probe 0ms 달성을 확정했습니다. 잔여 분산으로 효과 크기는 미확정입니다.
- **측정 설계와 실행계획 조사 (2026-09-11, 도구 완비·원인 미확정)**: 계측 도구를 완비했습니다. 영속 통계 노후를 확인했으나 계획 전환 원인은 미확정입니다.
- **ChromaDB 1.x 업그레이드 (2026-09-13, 보류)**: 1.5.9 까지 CVE 미수정, 1.x 는 1건 추가. 서버 미노출로 예외 유지, 12-31 재확인 ([chromadb_1x_upgrade_plan.md](../analysis/chromadb_1x_upgrade_plan.md)).
### 6.2 정본 갱신 규약 (Update Protocol)

- 운영 지표·게이트·불변 사실이 바뀌면 같은 커밋에서 [CURRENT_STATE.md](CURRENT_STATE.md)와 [current_state_facts.yaml](current_state_facts.yaml)을 함께 갱신합니다.
- 상세 측정 로그와 과거 경위는 [current_state_history.md](current_state_history.md)로 옮기며 사실을 삭제하지 않습니다.
- **정규화 목표: 문자 수 8,000자 이하**입니다. 상세 로그는 이력으로 분리했습니다. 12,000바이트 목표는 2026-09-12 에 폐기했습니다. 한국어에서 8,000자는 13,000바이트를 넘어 두 목표가 양립하지 않습니다.
- 진실 우선순위는 실제 코드·실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff입니다.

## 7. 증거 경로 참조 (Evidence Pointers)

- 기계 원장: [docs/context/current_state_facts.yaml](current_state_facts.yaml)
- 상세 로그·과거 경위: [current_state_history.md](current_state_history.md)
- 컷오버·레이턴시 규약: [latency_gate_protocol.md](../ops/latency_gate_protocol.md), [phase7_cutover_declaration_20260901.md](../ops/phase7_cutover_declaration_20260901.md)
- 현재 잔여 과업: [handoff_20260911_wave_bf_bm_session_close.md](../ops/handoff_20260911_wave_bf_bm_session_close.md) (6장이 남은 항목입니다)
- 공고 금액 이상치·오버플로우: [announcement_amount_outliers_20260904.md](../ops/announcement_amount_outliers_20260904.md)
- 데이터·특징 불변성: [db_migration_runbook.md](../migration/db_migration_runbook.md), [features.py](../../src/ml/features.py)
