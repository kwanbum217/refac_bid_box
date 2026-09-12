# 분석 보고서 주제별 인덱스 (Analysis Document Index)

> **작성일**: 2026-09-12
> **상태**: 활성 (Active)
> **대상**: `docs/analysis/` 내 전체 조사·분석·측정·의사결정 문서 (총 394건)
> **원칙**: 주제별 분류, 기한부/미해결 과업 및 활성 문서 분리, 측정/기각 항목 명시, 표 우선, 단일 진실 원천 정합성 보장

---

## 문서 개요

본 문서는 `docs/analysis/` 디렉터리에 축적된 394건의 분석 및 조사 보고서를 주제별로 체계화한 단일 정본 색인입니다. 각 항목은 대표 문서 링크와 한 줄 핵심 판정 내용을 포함하며, 복수 회차나 검토 보고서가 수반된 과업은 대표 문서 하위에 연관 문서를 묶어 가독성을 유지하였습니다.

## 목차

1. [활성 문서 및 미해결 기한부 과업](#1-활성-문서-및-미해결-기한부-과업)
2. [성능 측정 및 벤치마크](#2-성능-측정-및-벤치마크)
3. [기각된 대안 및 접근법](#3-기각된-대안-및-접근법)
4. [머신러닝 예측 모델 및 특징 공학](#4-머신러닝-예측-모델-및-특징-공학)
5. [지식 베이스(KB), RAG 및 벡터 검색](#5-지식-베이스kb-rag-및-벡터-검색)
6. [SSR/HTMX 프론트엔드 및 웹 엔드포인트](#6-ssrhtmx-프론트엔드-및-웹-엔드포인트)
7. [인프라, 비동기 큐(Arq) 및 데이터 정합성](#7-인프라-비동기-큐arq-및-데이터-정합성)
8. [엔지니어링 품질, CI/CD 및 멀티에이전트 오케스트레이션](#8-엔지니어링-품질-cicd-및-멀티에이전트-오케스트레이션)

---

## 1. 활성 문서 및 미해결 기한부 과업

현재 진행 중이거나 만료 기한이 정해진 과업, 후속 착수 대기 조사 문서입니다. chromadb 1.x 업그레이드(2026-12-31 만료) 및 nanoid 취약점(2026-10-31 만료) 관리가 포함됩니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`drift_baseline_source_survey_20260906.md`](drift_baseline_source_survey_20260906.md) | [`task_093efcc53333.md`](task_093efcc53333.md) | 2026-09-06 | - 정의: src/ml/monitoring.py:130-137의 save_baseline_distributions가 target_dir/feature_distributions_v1.json과 target_dir/metadata.... |
| [`task_38b3bb325d8e.md`](task_38b3bb325d8e.md) | [`task_4ff8fb0ca9cd.md`](task_4ff8fb0ca9cd.md)<br>[`task_69142134cabc.md`](task_69142134cabc.md)<br>[`task_a48917d63a07.md`](task_a48917d63a07.md) | 2026-09-03 | 공급망 스캔(pip/npm/Trivy) 차단 모드 전환 및 예외 관리 도입. chromadb 1.x 업그레이드(2026-12-31 만료) 및 nanoid(2026-10-31 만료) 기한부 과업 확정 |
| [`ssr_e2e_scope_survey_20260902.md`](ssr_e2e_scope_survey_20260902.md) | [`task_07bcd5cf94e2.md`](task_07bcd5cf94e2.md) | 2026-09-02 | 본 저장소(refac_bid_box)는 Django 모놀리식 구조에서 FastAPI + MySQL 8 + Redis + Meilisearch + Ollama 기반으로 리팩토링된 공공조달 입찰 예측 및 하이브리드 RAG 챗봇 플랫... |
| [`observability_stack_survey_20260902.md`](observability_stack_survey_20260902.md) | [`bd1_otel_metrics_review_20260911.md`](bd1_otel_metrics_review_20260911.md)<br>[`task_0534350cf9a0.md`](task_0534350cf9a0.md) | 2026-09-02 | 지표를 먼저 정의한 뒤, 1인 운영에 맞는 관측성 선택지를 비교합니다. |

---

## 2. 성능 측정 및 벤치마크

Arq 워커 처리량, /predict 엔드포인트 P95 레이턴시(c1/c2/c4/c10), RAG 질의 지연, 콜드 SQL 귀속 등 시스템 성능 실측 결과입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`bb2_monthly_snapshot_effect_20260911.md`](bb2_monthly_snapshot_effect_20260911.md) | — | 2026-09-11 | **캐시 미적중 종단이 505ms 에서 4.9ms 가 됐습니다.** 최초 기준선 3,725ms 대비 **760배** 입니다. |
| [`ba2_compare_stats_snapshot_effect_20260911.md`](ba2_compare_stats_snapshot_effect_20260911.md) | — | 2026-09-11 | **캐시 미적중 종단이 3,725ms 에서 505ms 가 됐습니다.** **판정은 둘로 나누어 적습니다.** - **구조 차이는 확정입니다.** agency_announce_top10 과 matched_count 두 구간이 |
| [`az3_compare_stats_attribution_20260911.md`](az3_compare_stats_attribution_20260911.md) | — | 2026-09-11 | **GET /api/v1/bids/compare-stats 의 캐시 미적중 종단 시간은 두 쿼리가 87% 를 차지합니다.** |
| [`ay1_compare_stats_endtoend_and_analyze_20260911.md`](ay1_compare_stats_endtoend_and_analyze_20260911.md) | — | 2026-09-11 | GET /api/v1/bids/compare-stats 를 회차마다 Redis 를 비우고 호출했습니다. 캐시 미적중 경로만 측정합니다. |
| [`av1_compare_stats_cost_accounting_20260910.md`](av1_compare_stats_cost_accounting_20260910.md) | [`av1_compare_stats_cost_accounting_review_20260910.md`](av1_compare_stats_cost_accounting_review_20260910.md) | 2026-09-10 | src/app/services/dashboard.py 의 get_compare_stats_data(484행) 캐시 미적중 경로 |
| [`at4_compare_stats_optimization_20260910.md`](at4_compare_stats_optimization_20260910.md) | — | 2026-09-10 | 코디네이터가 측정한 웜 캐시 미적중 정상상태는 약 6.5초입니다. 이 문서의 EXPLAIN은 실제 실행 시간이 아니라 MySQL 옵티마이저의 예상 비용을 보여주므로, |
| [`aq2_servc_scope_extension_survey_20260910.md`](aq2_servc_scope_extension_survey_20260910.md) | [`aq3_evaluation_realuse_scenarios_20260910.md`](aq3_evaluation_realuse_scenarios_20260910.md)<br>[`ar2_tech_servc_realuse_announcements_20260910.md`](ar2_tech_servc_realuse_announcements_20260910.md) | 2026-09-10 | 기존 설계서에 적힌 일반용역 주류 협상에의한계약 16,050건은 같은 기간·같은 일반용역 조건의 첫 번째 문자열과 일치합니다. 다만 협상에의한계약(SW사업) 3,355건도 별도 문자열로 존재하므로, 지원 범위를 넓힐 때 협상 모... |
| [`kb_max_documents_520k_20260909.md`](kb_max_documents_520k_20260909.md) | — | 2026-09-09 | 최근 1년 공고가 **505,271건**인데 상한이 500,000 이라 창의 가장 오래된 **5,271건(1.04%)** 이 색인에서 빠지고 있었습니다. 잘리는 구간은 2025-09-09 ~ 09-12 로 |
| [`kb_index_memory_waveap_verification_20260909.md`](kb_index_memory_waveap_verification_20260909.md) | — | 2026-09-09 | 단일 update_kb_task 1회가 **959초에 정상 완료**했고 worker 컨테이너 피크는 **4,323MB** 입니다. 2026-09-09 오전의 10,762MB 소멸 곡선이 재현되지 않았습니다. |
| [`kb_index_memory_verification_20260909.md`](kb_index_memory_verification_20260909.md) | [`kb_builder_memory_exhaustion_20260908.md`](kb_builder_memory_exhaustion_20260908.md) | 2026-09-09 | bf29f3e 의 청크 스트리밍 수정 이후에도 update_kb_task 단일 1회 실행에서 worker |
| [`dashboard_base_amount_api_latency_20260908.md`](dashboard_base_amount_api_latency_20260908.md) | — | 2026-09-08 | 본 측정은 대시보드 공고 금액 집계가 원본 JSON 파싱(json_extract, replace, cast)에서 base_amount 컬럼 기반 집계(커밋 30aba4e)로 전환된 이후, 대시보드 통계 API(GET /api/v... |
| [`task_a4ee1c96348b.md`](task_a4ee1c96348b.md) | — | 2026-09-07 | scripts/benchmark_rag_segments.py, tests/test_benchmark_rag_segments.py |
| [`task_a40b9309a832.md`](task_a40b9309a832.md) | — | 2026-09-07 | 2026-09-07 동일한 canonical 게이트를 통과한 벤치마크 산출물 두 건에서 콜드 sql_ms 최댓값이 각각 320.3ms와 69.3ms로 크게 갈리는 현상이 확인되었습니다. |
| [`r13_coldsql_timeout_verdict_20260907.md`](r13_coldsql_timeout_verdict_20260907.md) | — | 2026-09-07 | **정본 자격은 얻지 못했으나 미충족 원인이 데이터로 확정됐습니다.** 실패 3건은 전부 클라이언트 타임아웃이며 서비스 결함도 하네스 계수 오류도 아닙니다. 콜드 표본이 |
| [`task_ef0da6612975.md`](task_ef0da6612975.md) | — | 2026-09-06 | - src/tasks/scheduled_tasks.py의 backup_schedule_task에서 사전 측정은 로그로만 남기고, notify 경보는 prune_snapshots 이후 재측정한 값으로만 판정하도록 순서를 바로잡았습니다. |
| [`task_6672607b1c01.md`](task_6672607b1c01.md) | — | 2026-09-05 | 기존 src/tasks/worker.py의 _redis_queue_length()는 Arq 큐의 길이를 측정하기 위해 client.llen(ARQ_QUEUE_KEY)를 호출하였습니다. |
| [`task_6c66e96b551b.md`](task_6c66e96b551b.md) | — | 2026-09-04 | 외부 진단 및 코디네이터 실측에서 확인된 Orca 통제면의 3대 결함을 영구 해소합니다: 1. **역할 혼선(Role Ambiguity)**: 리뷰어에게 빌더 계약(커밋 의무, write scope 준수)을 주입해 읽기 전용 계... |
| [`agency_top10_column_switch_measurement_20260904.md`](agency_top10_column_switch_measurement_20260904.md) | — | 2026-09-04 | **산출값이 완전히 같으면서 26~29배 빨라집니다.** top10 의 기관명, 총액, 건수가 두 경로에서 모두 일치했습니다. |
| [`task_d012a27f6c18.md`](task_d012a27f6c18.md) | — | 2026-09-03 | 2026-09-03 외부 감사에서 기존 복원 리허설 도구인 run_restore_drill이 **이름만 리허설**이고 실제로는 아카이브를 해제하거나 DB 클라이언트를 호출하지 않은 채 계획 검증 및 매니페스트 체크섬 확인만 수행... |
| [`task_1a6eeab35699.md`](task_1a6eeab35699.md) | — | 2026-09-03 | 2026-09-03 운영 DB 실측 결과, bid_announcements의 마지막 수집 시각(collected_at)이 2026-08-27 07:14(수동 실행)에 머물러 있었으며, pipeline_executions의 마지막... |
| [`task_f2d04cab05a2.md`](task_f2d04cab05a2.md) | — | 2026-09-01 | 1. **tests/test_benchmark_latency.py**: - test_benchmark_latency_main_fails_when_container_swapped_during_measurement 에서 10초 대기... |
| [`task_d33cbcec73c1.md`](task_d33cbcec73c1.md) | — | 2026-09-01 | CURRENT_STATE 6.1절이 공고 상세 쿼리를 "실측 미수행"으로 기술하고 있었으나 docs/analysis/detail_query_explain_20260830.md 에 이미 실측 결과가 기록돼 있었습니다. |
| [`rag_llm_segment_and_warmup_20260901.md`](rag_llm_segment_and_warmup_20260901.md) | — | 2026-09-01 | warm 구간 정본에서 llm 은 P50 2,244ms 로 전체의 62.5% 입니다. 후보 넷을 실측으로 확인했고 **모두 여지가 없습니다.** |
| [`ngram_edge_classes_measurement_20260901.md`](ngram_edge_classes_measurement_20260901.md) | — | 2026-09-01 | **7 클래스 중 2 건이 조용한 누락(silent false-negative)을 실제로 일으킵니다.** 나머지 5 건은 표본이 있는 환경에서 ID 집합이 완전히 일치했습니다. |
| [`coldsql_metric_demotion_20260901.md`](coldsql_metric_demotion_20260901.md) | — | 2026-09-01 | 같은 HEAD, 같은 fixture(sha 2c98c636a478), 같은 명령, 같은 32문항 x 3회입니다. |
| [`task_f494424ee328.md`](task_f494424ee328.md) | — | 2026-08-31 | docs/analysis/ 의 수치를 data/benchmarks/*.json 원시 측정에서 기계로 생성하고, |
| [`task_6d21228d563c.md`](task_6d21228d563c.md) | — | 2026-08-31 | F3 선행 와일드카드 실측 조사(task_f3_ngram_fulltext_probe.md) 결과에 따라, 집계 레이턴시가 대폭 개선되는 두 경로(dminstt_nm 18.99배 가속, bidwinnr_nm 2.85배 가속)에만 ... |
| [`task_28970a2c7f37.md`](task_28970a2c7f37.md) | — | 2026-08-31 | Section F3 실측(task_f3_ngram_fulltext_probe.md)에서 10개 대표 표본 키워드와 50개 케이스에 대해 MySQL 8 ngram FULLTEXT 인덱스와 기존 LIKE 결과가 100% 일치함을 확... |
| [`vector_segment_optimization_20260830.md`](vector_segment_optimization_20260830.md) | — | 2026-08-30 | 2026-08-30 정본 구간 레이턴시 측정(data/benchmarks/rag_segments_canonical_20260830.json) 결과, 전체 RAG 지연 중 vector 구간이 33.0% (P50 1,307.88ms... |
| [`task_f50eb8c4d5c0.md`](task_f50eb8c4d5c0.md) | — | 2026-08-30 | **순위 집계 쿼리(계열 A)의 콜드/웜 지배 비용은 손상 필터(exclude_corrupted의 NOT LIKE '%\ufffd%') 때문이 아닙니다.** |
| [`task_f4651d2ec6ef.md`](task_f4651d2ec6ef.md) | — | 2026-08-30 | 2026-08-30 정본 구간 레이턴시 측정에서 vector 구간이 전체 지연의 33.0% (P50 1,307.88ms, P95 2,058.22ms)를 차지함에 따라, retrieve_semantic_context 경로의 시간 ... |
| [`task_f3_ngram_fulltext_probe.md`](task_f3_ngram_fulltext_probe.md) | — | 2026-08-30 | 콜드 SQL 기여도 분석(coldsql_attribution_canonical_20260830.md) 결과, 상위 비용을 유발하는 정형 질의 패턴 중 다수가 LIKE '%keyword%' 형태의 선행 와일드카드 검색을 포함하고 ... |
| [`task_f2_search_delegation.md`](task_f2_search_delegation.md) | — | 2026-08-30 | GET /indexes/bid_records/stats 실측 결과 (2026-08-30): |
| [`task_9afe32007e75.md`](task_9afe32007e75.md) | — | 2026-08-30 | 2026-08-30 LLM 품질 정본 측정에서 fixture v2 32문항 중 q21("2026년 조림지 풀베기사업 2차(동부지구)")만 numeric 0/2, evidence recall 0.0을 기록했습니다. |
| [`task_7ab7d19b1a10.md`](task_7ab7d19b1a10.md) | — | 2026-08-30 | 2026-08-30 정본 측정에서 RAG 구간 계측 하네스의 P99 및 max 지연시간이 프로세스 재기동 직후 첫 요청의 콜드 스타트 비용(ChromaDB 및 임베딩 모델, Ollama 커넥션 초기화)으로 인해 과대 추정(오염)... |
| [`task_4a485df361bd.md`](task_4a485df361bd.md) | — | 2026-08-30 | 2026-08-30 실측에서 Redis 캐시가 만료된 콜드 상태의 RAG 정형 질의가 최대 97초까지 소요되는 현상이 확인되었습니다. |
| [`task_259753e7edee.md`](task_259753e7edee.md) | — | 2026-08-30 | 2026-08-30 RAG 정형 질의 콜드 스타트 조사 과정에서 EXPLAIN 기반 단일 쿼리 추정에 의존하여 실제 97초 비용의 약 15%만 점유하는 쿼리를 수정하는 오류가 발생했습니다. 동일한 실수를 방지하고 실측 기반으로 ... |
| [`task_1618389a316f.md`](task_1618389a316f.md) | — | 2026-08-30 | src/rag/ 와 src/app/ 전체에서 SQLAlchemy .contains() 호출 13건을 전수 조사해 7개 그룹으로 분류하고, 각 그룹의 의도·컴파일 형태·실측 비용·대체 후보·의미 변화 위험을 표와 근거로 정리했다.... |
| [`serial_measurement_20260830.md`](serial_measurement_20260830.md) | — | 2026-08-30 | 전 측정에서 요청 실패 0건, 제외 0건입니다. |
| [`q21_retrieval_miss_20260830.md`](q21_retrieval_miss_20260830.md) | — | 2026-08-30 | 2026-08-30 정본 측정에서 fixture v2 32문항 중 q21만 numeric 0/2, evidence recall 0.0을 기록했습니다. |
| [`detail_query_explain_20260830.md`](detail_query_explain_20260830.md) | — | 2026-08-30 | 2026-08-28 측정 중 관측된 db 컨테이너 175% CPU 의 정체가 이 쿼리로 **확정**됐습니다. |
| [`coldsql_attribution_canonical_20260830.md`](coldsql_attribution_canonical_20260830.md) | [`at2_coldsql_cause_investigation_20260910.md`](at2_coldsql_cause_investigation_20260910.md)<br>[`au2_structured_sql_instrumentation_20260910.md`](au2_structured_sql_instrumentation_20260910.md)<br>[`av2_coldsql_segment_measurement_20260910.md`](av2_coldsql_segment_measurement_20260910.md)<br>[`rag_structured_sql_coldstart_20260830.md`](rag_structured_sql_coldstart_20260830.md) | 2026-08-30 | 32문항 정본 fixture 기준 콜드/웜 SQL 비용 귀속 정본 실측. 웜 상태 0.15초 대비 콜드 상태 223.77초 지연 규명 |
| [`blind_fixture_v2_canonical_20260830.md`](blind_fixture_v2_canonical_20260830.md) | — | 2026-08-30 | **T7 conditional vector bypass 는 품질 회귀를 일으키지 않았습니다. 판정을 종료합니다.** |
| [`task_ca9b69568ca4.md`](task_ca9b69568ca4.md) | — | 2026-08-29 | 2026-08-28 측정 세션에서 --fixture 옵션 기본값(data/eval/llm_quality_fixture_v1.json)으로 인해 v1(24문항) fixture로 측정된 산출물이 정본(canonical=true)으로... |
| [`task_ea8ae09336e5.md`](task_ea8ae09336e5.md) | — | 2026-08-28 | 과거 verify_verification_truth는 모든 검증 재실행 명령에 대해 30초 고정 타임아웃(timeout: int = 30)을 일괄 적용했습니다. 그러나 본 저장소의 전체 테스트 스위트(pytest) 실행은 실측 ... |
| [`task_d90da80dacf3.md`](task_d90da80dacf3.md) | — | 2026-08-28 | scripts/benchmark_provenance.py의 measure_cpu_utilization은 Linux 경로(/proc/stat 차분)에서 의도적 time.sleep(sleep_dur) (기본 0.05 초)을 두 번의... |
| [`task_ac1c2f9da231.md`](task_ac1c2f9da231.md) | — | 2026-08-28 | - **목표**: 벤치마크 리포트에 실제 CPU utilization 계측을 도입하여, 기존 1분 normalized load average 지표와 함께 독립 필드로 기록하고 모니터링 체계를 고도화. |
| [`task_9ac5a04f4eb1.md`](task_9ac5a04f4eb1.md) | — | 2026-08-28 | 벤치마크 호스트 부하 표본에 cpu_utilization_method와 cpu_utilization_probe_ms를 추가했습니다. Linux는 proc_stat_delta, macOS는 ps_process_sum, 미지원 플랫... |
| [`lexical_channel_latency_effect_20260828.md`](lexical_channel_latency_effect_20260828.md) | — | 2026-08-28 | 독립 lexical 채널 도입 시 전체 검색 경로 레이턴시에 미치는 영향 실측 분석 |
| [`cpu_utilization_metric_20260828.md`](cpu_utilization_metric_20260828.md) | — | 2026-08-28 | 기존 벤치마크 하네스는 호스트 부하 지표로 1분 load average를 논리 코어 수로 나눈 normalized_load_1m_percent(하위 호환 per_core_percent)만을 수집·기록했습니다. |
| [`blind_fixture_remeasure_20260828.md`](blind_fixture_remeasure_20260828.md) | — | 2026-08-28 | 2026-08-27 의 e2b/e4b 비교 측정 이후 다음 세 변경이 들어갔으므로, 현 HEAD 의 RAG 품질 기준선이 그 측정과 같은 코드 상태가 아니었습니다. |
| [`task_d87186af3616.md`](task_d87186af3616.md) | — | 2026-08-27 | 외부 재감사에서 벤치마크 호스트 부하 지표 산식인 (os.getloadavg()[0] / cpu_count) * 100을 코드와 문서에서 "코어당 사용률", "CPU 사용률"로 표기하여 지표의 실제 물리적 의미(1분 정규화 lo... |
| [`task_9fe129597faf.md`](task_9fe129597faf.md) | — | 2026-08-27 | - blind fixture v2 측정에서 q21(2026년 조림지 풀베기사업 2차(동부지구))은 벡터 검색 결과 10위에 위치하여 기존 top_k=5 설정 하에서 최종 탈락하는 문제가 있었습니다. |
| [`task_57653494cbff.md`](task_57653494cbff.md) | — | 2026-08-27 | gemma4:e2b 모델의 승격 근거가 24문항 fixture v1(data/eval/llm_quality_fixture_v1.json) 안에서만 성립하여, fixture 밖의 미노출 분포에 대한 일반화 성능 측정이 요구되었습니... |
| [`retrieval_miss_investigation_20260827.md`](retrieval_miss_investigation_20260827.md) | — | 2026-08-27 | KB 재색인 뒤 재측정에서 e2b·e4b 모두 21/24 를 통과했고, 실패한 3문항은 **양쪽 모델에서 동일하게** evidence_recall = 0.0 이었습니다. 모델을 바꿔도 |
| [`llm_generalization_judgment_20260827.md`](llm_generalization_judgment_20260827.md) | — | 2026-08-27 | gemma4:e2b 승격을 유지합니다.** |
| [`task_d1bfaebc6bd3.md`](task_d1bfaebc6bd3.md) | — | 2026-08-26 | 기존 benchmark_arq_container.py / benchmark_arq_throughput.py 가 합성 |
| [`task_a8467bf4c4a5.md`](task_a8467bf4c4a5.md) | — | 2026-08-26 | 2026-08-25 LLM 품질 v3 측정 과정에서 미개찰 공고 관련 질의(fixture q18: 내일 오후 2시 개찰 예정 사업의 사전 확정 예정가격 및 1순위 낙찰업체 질의)에 대해 모델이 근거 없이 가상 정보를 답변하는 과... |
| [`task_2e60da21b7db.md`](task_2e60da21b7db.md) | — | 2026-08-26 | 첫 [[tool.mypy.overrides]] arg-type 블록(16모듈)을 전부 해소했습니다. override 제외 mypy 재측정 후 타입을 좁혔고, 해당 블록 자체를 pyproject.toml에서 제거했습니다. |
| [`task_08afb35c2a9e.md`](task_08afb35c2a9e.md) | — | 2026-08-26 | **목적**: fixture 밖 일반화 측정의 설계서를 작성해, 다음 세션이 문항 제작부터 다시 고민하지 않고 측정만 실행하면 되는 상태로 만든다. |
| [`task_0806b3051833.md`](task_0806b3051833.md) | — | 2026-08-26 | **제거된 override 블록**: 4개 (model_registry, arg-type+assignment 묶음의 3모듈 제외, audit, benchmark_arq, benchmark_provenance) |
| [`llm_quality_v4_e4b_e2b_20260826.md`](llm_quality_v4_e4b_e2b_20260826.md) | — | 2026-08-26 | v3(소스 9516808)에서 e2b 는 numeric 과 지연이 앞섰으나 미개찰 공고 q18 에서 3회 중 |
| [`llm_quality_v3_e4b_e2b_20260825.md`](llm_quality_v3_e4b_e2b_20260825.md) | — | 2026-08-25 | v2 측정은 검색 필터 수정(0559a36) **이전** 소스 1d51d38 에서 했습니다. 근거 적중이 15/16 → **16/16** 으로 오른 뒤 숫자 정확도가 함께 움직이는지 확인하려고 |
| [`task_rag_harness_integrity.md`](task_rag_harness_integrity.md) | — | 2026-08-24 | 기존 scripts/benchmark_rag_segments.py는 base_url과 대상 컨테이너(target_container)의 포트 바인딩 및 이미지 정합성을 엄밀히 결박하지 않았고, 시간 범위(docker logs --... |
| [`task_e3a7054546c4.md`](task_e3a7054546c4.md) | — | 2026-08-24 | 1. 두 Arq 벤치마크 하네스에 복사되어 있는 provenance 헬퍼를 공통 모듈로 단일화. 2. Redis 컨테이너를 이름 접두 일치로 자동 선택하던 provenance 결박을 명시 대상 지정과 fail-closed 로 변경. |
| [`task_benchmark_foundation.md`](task_benchmark_foundation.md) | — | 2026-08-24 | Phase 7 레이턴시 및 처리량 벤치마크 하네스는 실측 데이터의 신뢰성을 보장하기 위해 대상 Docker 컨테이너의 식별자(Container ID, Image ID, Image Digest, RepoDigest, 소스 마운트 ... |
| [`task_arq_harness_integrity.md`](task_arq_harness_integrity.md) | — | 2026-08-24 | 기존 Arq 처리량 및 지연 계측 하네스는 in-process 방식(scripts/benchmark_arq_throughput.py)과 Docker 컨테이너 방식(scripts/benchmark_arq_container.py)으... |
| [`llm_quality_e4b_e2b_20260824.md`](llm_quality_e4b_e2b_20260824.md) | — | 2026-08-24 | 운영 RAG 경로 기반 19문항 fixture로 gemma4:e4b와 e2b 품질을 실측 비교 (e4b 기준선 수립) |
| [`arq_provenance_centralization_20260824.md`](arq_provenance_centralization_20260824.md) | [`arq_harness_blocker_remediation_20260824.md`](arq_harness_blocker_remediation_20260824.md)<br>[`calibration_executability_20260824.md`](calibration_executability_20260824.md) | 2026-08-24 | 외부 감사 항목 P1-1 과 P1-5 입니다. 1. **P1-1 (Provenance 헬퍼 단일화)**: build_provenance_dict, get_git_status, get_host_memory 가 두 Arq 벤치마크 ... |
| [`arq_baseline_calibration_20260824.md`](arq_baseline_calibration_20260824.md) | [`arq_calibration_design_20260824.md`](arq_calibration_design_20260824.md)<br>[`arq_calibration_formula_fix_20260824.md`](arq_calibration_formula_fix_20260824.md)<br>[`arq_executability_closure_20260824.md`](arq_executability_closure_20260824.md)<br>[`arq_threshold_derivation_20260823.md`](arq_threshold_derivation_20260823.md) | 2026-08-24 | scripts/arq_gate.py 의 RepetitionThresholds 는 900 jobs/sec, 600ms P95 였다. 이 값은 |
| [`runtime_source_provenance_20260823.md`](runtime_source_provenance_20260823.md) | — | 2026-08-23 | docker-compose.yml에서 app과 worker 컨테이너는 호스트의 ./src를 컨테이너 내부 /app/src로 bind mount합니다. 따라서 Docker 이미지 SHA가 동일하더라도 컨테이너 내부에서 실행되는 실... |
| [`rag_segments_measure_20260823.md`](rag_segments_measure_20260823.md) | — | 2026-08-23 | 단발 질의 20회 대상 RAG 구간별(임베딩, 벡터검색, LLM 생성) 레이턴시 실측 및 병목 분석 |
| [`rag_segment_harness_20260823.md`](rag_segment_harness_20260823.md) | — | 2026-08-23 | 단발 질의 API 는 총 소요만 알 수 있고 그 내역을 알 수 없었습니다. 2026-08-23 Ollama c4 실측에서 워밍 상태의 단발 질의 10회가 다음과 같이 나왔습니다. |
| [`prov_start_end_invalidation_20260823.md`](prov_start_end_invalidation_20260823.md) | — | 2026-08-23 | 기존 P1 provenance 결박 작업(docs/analysis/p1_provenance_binding_20260823.md)을 통해 측정 시작 시점의 base_url과 Docker 컨테이너 identity/포트 바인딩 결박은... |
| [`p1_provenance_binding_20260823.md`](p1_provenance_binding_20260823.md) | — | 2026-08-23 | docs/handoff/2026-08-22_post_1a45ad5_audit.md에서 지적된 바와 같이, 기존 레이턴시 및 SSE 벤치마크 하네스는 다음과 같은 신뢰 경계(Provenance Boundary) 결함이 존재했습니다: |
| [`p1_2_benchmark_provenance.md`](p1_2_benchmark_provenance.md) | — | 2026-08-23 | 기존 레이턴시 벤치마크 스크립트(scripts/benchmark_latency.py)는 재현성 메타데이터 수집 시 존재하지 않는 Docker Compose 서비스명(backend)을 조회하여 docker_image_id가 항상 ... |
| [`ollama_c4_measure_20260823.md`](ollama_c4_measure_20260823.md) | — | 2026-08-23 | 운영 기본 LLM 경로인 Ollama gemma4:e4b 환경에서 Predict c4, SSE c1, Query c1의 종단 간 레이턴시를 탐색 측정하고 자원 점유 특성과 직렬화 거동을 분석합니다. 주변 부하 게이트를 통과하지 ... |
| [`collection_rounds_observation_20260823.md`](collection_rounds_observation_20260823.md) | — | 2026-08-23 | docs/context/handoff_20260818.md 38줄의 실측 과업 목록 및 docs/context/CURRENT_STATE.md 4.1절의 운영 검증 우선순위 1번에 "수집 2·3회차 관찰"이 명시되어 있습니다. |
| [`arq_container_measure_20260823.md`](arq_container_measure_20260823.md) | [`arq_docker_worker_measure_20260823.md`](arq_docker_worker_measure_20260823.md)<br>[`arq_gate_skeleton_20260823.md`](arq_gate_skeleton_20260823.md)<br>[`arq_raw_provenance_20260823.md`](arq_raw_provenance_20260823.md)<br>[`arq_throughput_20260823.md`](arq_throughput_20260823.md)<br>[`arq_throughput_gate_20260823.md`](arq_throughput_gate_20260823.md) | 2026-08-23 | 본 문서는 운영 워커(src/tasks/worker.py) 및 운영 큐(arq:queue)를 일체 변경하지 않고, 운영과 동일한 Docker 이미지(refac_bid_box-worker:latest)와 운영 동시성 사양(max_... |
| [`task_query_latency_rework.md`](task_query_latency_rework.md) | — | 2026-08-22 | 1차 산출물(query_latency_breakdown.md)에 대해 제기된 결함을 보완하고 근거 수준을 명확히 분리하기 위해 재작업을 수행했습니다. |
| [`task_p95_bench.md`](task_p95_bench.md) | — | 2026-08-22 | 1. scripts/benchmark_latency.py 도구를 사용하여 FastAPI 서비스(http://127.0.0.1:8000)에 대해 30초 이상의 간격을 두고 3회 독립 벤치마크를 수행하였습니다. |
| [`task_coldstart_warmup_rework.md`](task_coldstart_warmup_rework.md) | — | 2026-08-22 | 1차 조사 산출물(predict_coldstart_analysis.md)은 워밍업 위치와 위험 요소를 유효하게 짚었으나, 단계별 계측이 부재한 상태에서 DB 풀·AnyIO 스레드·ML C-Extension 초기화를 383.1ms... |
| [`query_rag_latency_instrumentation.md`](query_rag_latency_instrumentation.md) | — | 2026-08-22 | 기존 단발 질의 API는 전체 P95 레이턴시(6.29초 ~ 10.26초)와 SSE 스트리밍의 완료 시간만 측정되었을 뿐, 내부의 RAG 컨텍스트 준비(SQL, 벡터 검색, KB 상태, 프롬프트 조립)와 LLM 백엔드 생성(ba... |
| [`query_latency_breakdown.md`](query_latency_breakdown.md) | — | 2026-08-22 | POST /api/v1/chatbot/query 호출 시 실행되는 전체 처리 경로는 아래 4단계로 구성됩니다. |
| [`predict_coldstart_instrumentation.md`](predict_coldstart_instrumentation.md) | — | 2026-08-22 | 2026-08-22 실측에서 낙찰가 예측 API는 웜 상태(3~6회차)에서 P95 61.9ms ~ 83.6ms로 목표(100ms)를 충족했으나, 1회차 콜드스타트에서 P95 383.1ms, 2회차 전이 상태에서 P95 122.1... |
| [`predict_coldstart_analysis.md`](predict_coldstart_analysis.md) | — | 2026-08-22 | 2026-08-22 블로킹 I/O 오프로드 후 종단 간 실측에서 낙찰가 예측 API(concurrency=10, rounds=100)는 다음과 같은 레이턴시 분포를 보였습니다. |
| [`c2_disposition_20260822.md`](c2_disposition_20260822.md) | — | 2026-08-22 | 2026-08-22 순차 재측정에서 예측 API c2 동시성의 P95 지연시간이 **22.68ms**로 관측되었습니다. 이는 기존 승격 판정 기준선인 **21.77ms** 대비 **+4.2%(+0.91ms)** 초과한 수치로, ... |
| [`blocking_io_p95_20260822.md`](blocking_io_p95_20260822.md) | [`blocking_io_gate_20260822.md`](blocking_io_gate_20260822.md) | 2026-08-22 | src/tasks/, src/app/api/, src/rag/ 등 12건의 블로킹 I/O 구간을 asyncio.to_thread 로 오프로드한 이후, 실제 기동 중인 FastAPI HTTP 서버(http://127.0.0.1:8... |
| [`arq_throughput_harness.md`](arq_throughput_harness.md) | — | 2026-08-22 | src/tasks/ 디렉터리의 8개 Arq 백그라운드 태스크(scheduled_tasks.py, automation_tasks.py, retrain_task.py)에 동기 I/O 오프로드(asyncio.to_thread)가 적용... |
| [`task_w1_windows_fixture_delay.md`](task_w1_windows_fixture_delay.md) | — | — | Windows 환경 pytest fixture 지연 현상 원인 분석 및 플레이스홀더 기록 |
| [`task_ba5614889a6f.md`](task_ba5614889a6f.md) | — | — | 2026-09-04 코디네이터 실측에 따르면, 공고 금액 집계 오버플로우 교정 코드(961a871)가 적용되었음에도 운영 DB의 bid_dataset_summaries의 announcement 행에는 이전 오버플로우 음수 값(-... |
| [`task_a1af58140a39.md`](task_a1af58140a39.md) | — | — | 본 작업은 단발 RAG 질의의 내부 세그먼트(계획, SQL, 벡터, 어셈블리, 사전준비, LLM 추론, 가드레일) 지연시간을 정밀 계측하는 하네스(scripts/benchmark_rag_segments.py)를 정본 측정 기준에... |
| [`task_44eb5fa51a0c.md`](task_44eb5fa51a0c.md) | — | — | 2026-08-30 RAG v2 32문항 정본 실측(docs/analysis/blind_fixture_v2_canonical_20260830.md)에서 신규 정본(6210ee1)의 Citation 지표가 100.0%(70/70)... |
| [`task_2d639c0bc1c6.md`](task_2d639c0bc1c6.md) | — | — | 테스트 경고를 통제 가능한 상한으로 묶었다. 베이스라인(-W default) 138 warnings → 필터 적용 후 **0 warnings**. 상한은 실측값에 근거해 5로 잡았다. |
| [`p2_3r_strict_json_evidence.md`](p2_3r_strict_json_evidence.md) | — | — | 기존 scripts/benchmark_latency.py에만 국소적으로 적용되어 있던 strict JSON 직렬화(dump_strict_json, sanitize_nan_to_none)를 공용 모듈 scripts/_strict_... |

---

## 3. 기각된 대안 및 접근법

실측 및 쌍대 비교를 통해 기각되었거나 롤백/폐기된 모델, 알고리즘, 아키텍처 대안의 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`ax2_plan_instability_20260911.md`](ax2_plan_instability_20260911.md) | [`ax1_measurement_design_20260911.md`](ax1_measurement_design_20260911.md)<br>[`ax1_measurement_design_review_20260911.md`](ax1_measurement_design_review_20260911.md)<br>[`ax2_plan_instability_review_20260911.md`](ax2_plan_instability_review_20260911.md)<br>[`ax2_plan_instability_review_20260911.md`](ax2_plan_instability_review_20260911.md)<br>[`az1_compare_stats_instrumentation_20260911.md`](az1_compare_stats_instrumentation_20260911.md)<br>[`az1_compare_stats_instrumentation_review_20260911.md`](az1_compare_stats_instrumentation_review_20260911.md) | 2026-09-11 | src/app/services/dashboard.py 의 get_compare_stats_data(484행) 안 매칭 건수 EXISTS 쿼리 |
| [`task_x4_model_swap_atomic.md`](task_x4_model_swap_atomic.md) | — | 2026-09-05 | 기존 승격은 서빙 디렉터리를 백업 자리로 shutil.move 한 뒤, staging 을 서빙 이름으로 다시 shutil.move 했습니다. 롤백도 target → holding, backup → target, holding →... |
| [`task_w2_catchup_ledger.md`](task_w2_catchup_ledger.md) | — | 2026-09-05 | 워커 기동 시 스케줄 따라잡기는 asyncio.create_task(_run_catchup_background) 가 run_schedule_catchup_task 를 직접 호출했다. 이 경로는 Arq max_jobs = 4 밖에... |
| [`servc_missing_lwlt_policy_20260902.md`](servc_missing_lwlt_policy_20260902.md) | [`servc_api_path_remeasurement_20260826.md`](servc_api_path_remeasurement_20260826.md)<br>[`servc_lwlt_missing_20260830.md`](servc_lwlt_missing_20260830.md)<br>[`servc_lwlt_path_reconfirmation_20260901.md`](servc_lwlt_path_reconfirmation_20260901.md) | 2026-09-02 | 본 보고서는 Servc 낙찰가 예측에서 낙찰하한율(lwlt_rate)이 결측인 missing_lwlt 집단(1,356건, 37.78%)을 운영 환경에서 안전하게 다루기 위한 정책안을 제시한다. **모델 성능을 올리는 방법은 없음... |
| [`vector_metadata_prefilter_verdict_20260901.md`](vector_metadata_prefilter_verdict_20260901.md) | — | 2026-09-01 | ChromaDB 메타데이터 사전 필터 최적화 실험 결과 쿼리 지연 개선 효과 없어 기각 |
| [`task_k3_dispatch_test_regression.md`](task_k3_dispatch_test_regression.md) | — | 2026-09-01 | - **목적**: main 브랜치에 유입되었던 tests/test_orca_taskctl.py 26건 및 tests/test_measure_agent_bootstrap_cost.py 1건(총 27건)의 테스트 실패를 시정하고, ... |
| [`ngram_prefilter_paired_verdict_20260901.md`](ngram_prefilter_paired_verdict_20260901.md) | [`task_i_h_ngram_edge_assertions.md`](task_i_h_ngram_edge_assertions.md)<br>[`task_u2_ngram_ci_contract.md`](task_u2_ngram_ci_contract.md) | 2026-09-01 | ngram 선행 필터 도입 시 검색 재현율 손실 대비 속도 개선 미미하여 최종 기각 판정 |
| [`task_49975ee8d7ea.md`](task_49975ee8d7ea.md) | — | 2026-08-26 | - **대상 브랜치**: integrate/arq-worker-cutover (커밋 12개, merge-base: 45faa8f) |
| [`task_14ca214849b4.md`](task_14ca214849b4.md) | — | 2026-08-26 | 본 Task는 저장소 내 마지막으로 남아 있던 2개의 미판정 브랜치(feat/p1-reliability-lock, kwanbum217/orca-w1-concurrency-2)를 감사하여 회수 가치 여부를 판정하고 문서화하는 작업... |
| [`llm_quality_v2_e4b_e2b_20260825.md`](llm_quality_v2_e4b_e2b_20260825.md) | [`llm_model_comparison_e4b_e2b_20260824.md`](llm_model_comparison_e4b_e2b_20260824.md)<br>[`measurement_triple_20260824.md`](measurement_triple_20260824.md) | 2026-08-25 | e2b 양자화 모델 품질 열화(BLEU/정밀도 미달) 확인으로 승격 기각, gemma4:e4b 모델 유지 |
| [`task_4190ee358120.md`](task_4190ee358120.md) | — | — | 코디네이터는 같은 과제를 여러 모델에 태운 베이크오프 산출물 9 개 ( b2- 5 + bakeoff- 4 ) 가 미병합 상태로 남아 있음을 확인하고, 회수할 구현이 있는지 혹은 전량 폐기해도 되는지를 판정하는 보고서를 요청했습니... |

---

## 4. 머신러닝 예측 모델 및 특징 공학

용역/물품 낙찰률 예측 모델, LightGBM/CatBoost 특징 단일화, 손실함수 튜닝 및 OOS 성능 평가 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`ng2a_negotiation_price_score_survey_20260910.md`](ng2a_negotiation_price_score_survey_20260910.md) | — | 2026-09-10 | category='Servc', bid_ntce_dt >= '2026-05-26', sucsfbidMthdNm가 협상에의한계약으로 시작하는 공고 |
| [`task_e08405bf8ce1.md`](task_e08405bf8ce1.md) | — | 2026-09-06 | src/tasks/scheduled_tasks.py의 drift_monitor_task는 카테고리별로 baseline을 조회한 뒤(541행), baseline이 없으면 다음 분기로 들어갑니다(542행). |
| [`task_74712e3bf4ad.md`](task_74712e3bf4ad.md) | — | 2026-09-06 | scripts/generate_drift_baseline.py 를 신설했습니다. 지정한 데이터 구간으로 drift baseline 을 |
| [`task_y1_muse_register.md`](task_y1_muse_register.md) | — | 2026-09-05 | Meta Muse Spark 1.3 모델을 opencode 무료 경로(opencode/muse-spark-1.3-contributor-free)를 통해 Orca 모델 풀(scripts/orca_model_router.py)에 등... |
| [`task_x5_live_pointer_impl.md`](task_x5_live_pointer_impl.md) | — | 2026-09-05 | 선행 구현(902a046)은 서빙 경로의 디렉터리 부재 구간을 제거했으나 파일별 os.replace로 인한 세트 원자성 결함이 있었으며, 1차 세대 디렉터리 구현(task_x5_live_pointer_impl 1차안)에서는 동일... |
| [`task_sonnet5_routing_review.md`](task_sonnet5_routing_review.md) | — | 2026-09-04 | 커밋 be9160a를 읽기 전용으로 독립 검토했다. 대상 acceptance 6항목은 모두 충족이며, review_checklist 5항목은 모두 결함 없음이다. G1 데이터 무손실 위반, train/serve 특징 분리, 동시... |
| [`task_801947f162b6.md`](task_801947f162b6.md) | — | 2026-09-04 | SuperGrok 구독의 로컬 Grok CLI(/opt/homebrew/bin/grok)를 Orca 모델 풀(scripts/orca_model_router.py), 독립 리뷰어 실행 경로(scripts/orca_run_revie... |
| [`task_dd5fa6c22bab.md`](task_dd5fa6c22bab.md) | — | 2026-09-03 | 2026-09-03 Antigravity(agy) CLI 환경에서 gemini-3.8-flash-high, gemini-3.8-flash-medium, gemini-3.8-flash-low 세 가지 추론 등급이 정식 지원되었으며... |
| [`task_7aecb23da179.md`](task_7aecb23da179.md) | — | 2026-09-03 | 2026-09-03 외부 감사에서 P1 결함으로 지적된 사항을 조치했습니다: 1. drift_monitor_task에서 evaluation_window_days=7 인자가 로그와 결과 JSON에만 기록되고, 실제 데이터 조회 함... |
| [`task_9988e8a4f332.md`](task_9988e8a4f332.md) | — | 2026-09-02 | 기존 재학습 파이프라인(src/tasks/scheduled_tasks.py의 weekly_retrain_task 및 src/tasks/retrain_task.py)은 카테고리(category_code) 없이 호출될 수 있는 구조... |
| [`task_4ad3aa7470df.md`](task_4ad3aa7470df.md) | — | 2026-09-02 | 본 과업은 servc_missing_lwlt_policy_20260902.md 6.2절 및 psi_drift_wiring_20260902.md 설계를 바탕으로, 낙찰하한율(lwlt_rate)이 제도적으로 결측된 취약 하위 집단(... |
| [`task_345e27ea2812.md`](task_345e27ea2812.md) | — | 2026-09-02 | 본 작업은 2026-09-02 보완점 분석 보고서 3.2 다 항목에 따라, **MySQL 운영 DB**, **ChromaDB 지식베이스**, **서빙 모델 및 MLOps 레지스트리**를 단일 복구 단위(Unified Recove... |
| [`task_323bfebce1e9.md`](task_323bfebce1e9.md) | — | 2026-09-02 | 본 과업은 Servc 낙찰가 예측 모델에서 낙찰하한율(lwlt_rate)이 제도적으로 부재한 missing_lwlt 취약 집단(OOS 1,356건, 37.8%)의 안전한 운영 대응을 서빙 및 UI 단에 구현한 작업입니다. |
| [`task_15b11c894c87.md`](task_15b11c894c87.md) | — | 2026-09-02 | v_20260807_110637_435 는 운영 쌍대검정에서 기각된 버전이다 (docs/changelogs/work_log.md 2026-08-07 절). |
| [`psi_drift_wiring_20260902.md`](psi_drift_wiring_20260902.md) | — | 2026-09-02 | 현재 src/ml/monitoring.py 에 calculate_psi() 와 check_feature_drift() 가 구현돼 있으나, **운영 스케줄에 등록된 호출자가 0건**이고 TRIGGER_RETRAIN 액션을 소비하는... |
| [`task_j1_reviewer_json_recovery.md`](task_j1_reviewer_json_recovery.md) | — | 2026-09-01 | - **목적**: qwen3.7-plus 리뷰어 등 모델이 다중 JSON 또는 앞뒤 부가 텍스트를 반환할 때 파싱 실패로 인한 무작위 반려를 방지하고, 파싱 실패 시 정확히 1회 재시도하며, 실패 시 원문(.raw)을 재현 가능... |
| [`task_1da9f2a7d41f.md`](task_1da9f2a7d41f.md) | — | 2026-09-01 | - **목적**: qwen3.7-plus 리뷰어 등 모델이 다중 JSON 또는 앞뒤 부가 텍스트를 반환할 때 파싱 실패로 인한 무작위 반려를 방지하고, 파싱 실패 시 정확히 1회 재시도하며, 실패 시 원문(.raw)을 재현 가능... |
| [`task_fcf76f789b4d.md`](task_fcf76f789b4d.md) | — | 2026-08-31 | 2026-08-31 외부 감사에서 AGENTS.md, docs/ops/orca_worker_model_pool.md, scripts/orca_model_router.py의 모델 배정 정책이 세 갈래로 갈라졌던 사실이 확인되었습니... |
| [`task_d73439117217.md`](task_d73439117217.md) | — | 2026-08-31 | 2026-08-31 외부 감사 및 교차 검증 결과 확인된 운영 정본 문서 3종의 상호 모순 4건을 해소하고 실행 정본으로 수렴시켰습니다. |
| [`task_d36931fe938b.md`](task_d36931fe938b.md) | — | 2026-08-31 | 기존 리뷰어 실행기(../../scripts/orca_run_reviewer.py)는 CLI 실행 명령어가 agy로 하드코딩되어 있어, TIER_POLICY에서 리뷰어 주 모델로 지정한 qwen-plus(qwen3.7-plus)... |
| [`task_3e2372d0400c.md`](task_3e2372d0400c.md) | — | 2026-08-31 | 2026-08-31 외부 감사에서 확인된 결함에 따라, 빌더와 리뷰어가 동일한 모델 계열(Provider)로 배정되어 상호 검증의 독립성이 훼손되는 문제를 원천 차단하는 작업을 수행하였습니다. |
| [`task_e4761891ba38.md`](task_e4761891ba38.md) | — | 2026-08-30 | 2026-08-27 에 유효 OOS 가 3,589건으로 재계수되어 재학습 판단 게이트(3,098건)를 491건 초과했습니다. |
| [`task_75eda04c0e78.md`](task_75eda04c0e78.md) | — | 2026-08-30 | - **목적**: 1. orca_taskctl.py 의 dispatch 경로가 orca_model_router 의 배정표(select_model, TIER_POLICY)를 실제로 연동하여, Task 의 역할(role)과 위험도(... |
| [`task_2f833663090f.md`](task_2f833663090f.md) | — | 2026-08-30 | Servc Champion OOS 3,589건 평가에서 낙찰하한율 결측 1,356건의 성능(MAE 2.0943, 0.5%p 적중률 35.25%)이 보유 2,233건(MAE 0.6288, 적중률 79.36%) 대비 극단적으로 저조... |
| [`task_5650d22846b3.md`](task_5650d22846b3.md) | — | 2026-08-27 | 하이브리드 RAG 엔진의 낙찰금액·낙찰률 수치 누락 검출기(check_numeric_omissions)는 컨텍스트에 포함된 수치가 최종 답변에 올바르게 포함되었는지를 결정론적으로 진단하는 관측 기능입니다. |
| [`task_154f97c11673.md`](task_154f97c11673.md) | — | 2026-08-27 | 기존 scripts/audit_model_inventory.py는 모델 실재 여부를 단순 조회/감사하기만 해도 data/model_inventory_history.json의 카운터를 즉시 갱신하거나 초기화했습니다. 이로 인해 검... |
| [`task_102090cd8d52.md`](task_102090cd8d52.md) | — | 2026-08-27 | RAG 응답 생성 파이프라인의 낙찰금액·낙찰률 수치 누락 검출기(check_numeric_omissions)는 컨텍스트에 존재하는 핵심 수치가 최종 답변에서 누락되었는지를 결정론적으로 진단하는 관측 기능입니다. |
| [`task_eab38e36551f.md`](task_eab38e36551f.md) | — | 2026-08-26 | 2026-08-26 v4 분석 결과, RAG numeric 오답의 83~85%가 검색 실패가 아닌 LLM 생성 답변에서의 진술 누락(낙찰금액·낙찰률 미언급)으로 판명되었습니다. |
| [`task_cd74b709edb0.md`](task_cd74b709edb0.md) | — | 2026-08-26 | pyproject.toml의 [[tool.mypy.overrides]] 20개 블록, 55개 모듈. |
| [`task_a2001db0f587.md`](task_a2001db0f587.md) | — | 2026-08-26 | 거절 기대 문항(refusal_expected: true)이 3개뿐이라 q18 단일 문항이 모델 승격 판정을 좌우하는 표본 부족 문제를 해소한다. |
| [`task_89a6734a0df5.md`](task_89a6734a0df5.md) | — | 2026-08-26 | 본 작업은 2026-08-26 베이크오프 브랜치 판정에서 회수 후보로 확정된 두 변경 사항을 main 브랜치의 scripts/audit_model_inventory.py에 이식하고 회귀 테스트를 구축하는 작업입니다. |
| [`task_1032a244f885.md`](task_1032a244f885.md) | — | 2026-08-26 | 2026-08-26 v4 오답 분류 분석 결과, numeric 오답의 83~85%는 검색 실패가 아니라 검색된 근거 내 낙찰금액 또는 낙찰률 중 어느 한쪽만 답변에 출력하고 다른 한쪽을 누락하는 진술 누락 현상으로 판명되었습니다... |
| [`numeric_error_taxonomy_20260826.md`](numeric_error_taxonomy_20260826.md) | — | 2026-08-26 | - **e2b**: numeric 67/102 적중(65.7%), 오답 35건. 그중 29건(83%)이 **Omission(답변에서 진술 누락)**, 6건(17%)이 **Wrong-value-from-context(근거는 검색되... |
| [`mypy_mixed_blocks_20260826.md`](mypy_mixed_blocks_20260826.md) | — | 2026-08-26 | 1. src.ml.model_registry — assignment 2. arg-type+assignment 묶음 — kb_builder, automation_tasks (trainer·llm·eval_servc_predicti... |
| [`task_76587799510f.md`](task_76587799510f.md) | — | 2026-08-25 | - src/rag/query_planning.py의 build_retrieval_plan에서 use_sql과 use_vector가 상호 배타적으로 계산되어, 낙찰률 등 통계 키워드가 포함된 단건 공고 개체 조회 질의(q03, q... |
| [`llm_quality_fixture_20260824.md`](llm_quality_fixture_20260824.md) | — | 2026-08-24 | 본 문서는 gemma4:e4b 와 gemma4:e2b 간 LLM 승격 판정을 정량적·객관적으로 수행하기 위한 기계 판독 가능(machine-readable) 품질 평가 fixture v1의 설계 근거, ChromaDB 지식베이스... |
| [`t3.md`](t3.md) | — | 2026-08-18 | retrain_task.py의 run_retrain_pipeline_task는 비동기 Arq 워커 환경에서 실행되는 재학습 파이프라인 태스크입니다. |
| [`task_intent_w4_model_registry.md`](task_intent_w4_model_registry.md) | — | 2026-08-17 | src/ml/model_registry.py (종전 1,091줄)를 동작 보존 원칙에 따라 기계적으로 분할하였습니다. |
| [`task_z1_windows_remaining.md`](task_z1_windows_remaining.md) | — | — | macOS 13 / Python 3.12.14 / uv run pytest <파일> -q --durations=5 기준. |
| [`task_d90898d8f04f.md`](task_d90898d8f04f.md) | — | — | - src/ml/promotion.py에 compute_artifact_checksum() 단일 체크섬 함수를 |
| [`task_80f95ece9335.md`](task_80f95ece9335.md) | — | — | ModelRegistry의 이미 로드된 wrapper 메타데이터와 서빙 디렉터리의 metadata.json을 읽기 전용으로 비교합니다. 조회 경로는 /api/v1/health/served-version이며, 모델별 인메모리 버전... |
| [`task_67e934d9fa15.md`](task_67e934d9fa15.md) | — | — | SSR 브라우저 폼인 /accounts/login/, /accounts/signup/, /accounts/logout/ 화면에 서명 토큰을 발급하고, 세 상태 변경 POST를 모두 서버에서 검증합니다. 검증 플래그가 켜져 있을 ... |
| [`task_4a11c91c25e4.md`](task_4a11c91c25e4.md) | — | — | - **목표**: mypy 전역 비활성 오류 코드 5종 중 실제 위반이 없거나 적은 3종(return-value, attr-defined, union-attr)을 복구하여 타입 게이트의 실효성을 높인다. |
| [`task_2851e07d864d.md`](task_2851e07d864d.md) | — | — | - **배경**: taskctl dispatch의 런처 경로가 Antigravity(scripts/orca_agy_launch.py)로 고정되어 있어 다른 CLI 워커 기동 시 매번 수동으로 --launcher 경로를 적어야 했... |

---

## 5. 지식 베이스(KB), RAG 및 벡터 검색

ChromaDB 벡터 저장소, bge-m3 임베딩, 증분 색인, Meilisearch 하이브리드 검색 및 정합성 검증 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`aw1_skipped_marker_always_20260910.md`](aw1_skipped_marker_always_20260910.md) | [`aw1_skipped_marker_always_review_20260910.md`](aw1_skipped_marker_always_review_20260910.md)<br>[`aw1_skipped_marker_always_review_20260910.md`](aw1_skipped_marker_always_review_20260910.md)<br>[`aw2_probe_removal_effect_20260911.md`](aw2_probe_removal_effect_20260911.md) | 2026-09-10 | src/app/services/ranking_snapshots.py, src/rag/structured_data.py |
| [`task_7ff48226be33.md`](task_7ff48226be33.md) | — | 2026-09-07 | 격리 워크트리에는 gitignore 대상인 data/model_files/*/model.bin 및 chroma_db/ 디렉터리가 존재하지 않으므로, tests/test_data_preservation.py의 2건 테스트(test... |
| [`task_ef2f12867e6a.md`](task_ef2f12867e6a.md) | — | 2026-09-06 | 세 과제 중 코드를 바꾼 것은 없습니다. 바꾸지 않은 것이 아니라 바꿀 수 없음을 확인한 것입니다. 각 과제의 판정은 다음과 같습니다. |
| [`task_2e5e76ac2508.md`](task_2e5e76ac2508.md) | — | 2026-09-06 | verify_reconciliation이 낙찰 기준 단일 집합을 공고 기준 ChromaDB 색인과 차집합하던 모집단 불일치를 제거하고 저장소마다 그 저장소가 실제로 담는 도메인과 1:1로 대조하게 만들었습니다. 4장 후보 1을 ... |
| [`task_09a352270a13.md`](task_09a352270a13.md) | — | 2026-09-05 | scripts/run_data_reconciliation.py의 4단계 정합성 검사(verify_reconciliation)에서 DB 낙찰결과 식별자 집합(BidResult.bid_ntce_no)을 ChromaDB bidding... |
| [`task_1a3b7d392b3e.md`](task_1a3b7d392b3e.md) | — | 2026-09-03 | src/tasks/automation_tasks.py(717줄)와 src/ml/monitoring.py(664줄)를 chatbot API 분할 관례와 동일하게 형제 모듈로 기계 이동했습니다. 함수 본문·이름·시그니처는 변경하지 ... |
| [`task_56972f3284cb.md`](task_56972f3284cb.md) | — | 2026-09-02 | 2026-09-02 분석 보고서(3.8)에 따라 다음 두 가지 핵심 개선 과업을 수행하였습니다: 1. **정형 질의 캐시 키별 Single-Flight 도입**: Redis cold miss 시 동일 캐시 키에 대한 동시 대량 ... |
| [`task_d8f51c794b48.md`](task_d8f51c794b48.md) | — | 2026-09-01 | CI run 33494985187 의 mysql-ngram-integration (MySQL 8 ngram Integration Test) 잡이 실패하는 결함이 발생했습니다. |
| [`task_1584401ebfcf.md`](task_1584401ebfcf.md) | — | 2026-09-01 | Section I-H에서 추가된 7개 특수 경계값 클래스의 fail-closed 안전 판정(is_safe_for_ngram: false) 및 ID 집합 동등성 검증 하네스를 로컬 main 최신 상태(5f09059) 위로 reba... |
| [`task_fe40e063a6d9.md`](task_fe40e063a6d9.md) | — | 2026-08-31 | 기존 CI 파이프라인에서는 mysql_integration 마커가 붙은 MySQL 전용 테스트(tests/test_ngram_prefilter_equivalence.py)가 실제 MySQL 인스턴스 부재로 인해 skip 처리되었... |
| [`task_e5_live_path_hint.md`](task_e5_live_path_hint.md) | — | 2026-08-30 | Wave E1(a53b01a)에서는 콜드 스타트 시 최대 27.6초를 소모하던 corrupted_probe(LIKE '%\ufffd%' 선행 와일드카드 풀스캔)를 제거하고, 스냅샷 테이블의 손상 마커(rank=SKIPPED_MA... |
| [`task_26056df2c840.md`](task_26056df2c840.md) | — | 2026-08-30 | 실시간 집계 경로에서 손상값 제외 사실이 사용자 안내(insufficiency_hints)로 전달되지 않던 회귀를 시정했습니다. |
| [`contains_scan_survey_20260830.md`](contains_scan_survey_20260830.md) | — | 2026-08-30 | 1. src/rag/ 와 src/app/ 전체에서 \.contains\( 정규식 검색 (Grep). |
| [`task_dd956f60809d.md`](task_dd956f60809d.md) | — | 2026-08-28 | 2026-08-28 외부 감사에서 지적된 P2 이슈를 해결하기 위해, RAG 질의 처리 구간별 소요 시간 계측치(segment_metrics)를 AnswerBundle의 정식 선택 필드로 승격하고 비스트리밍 REST 응답(POS... |
| [`task_792ae782ed49.md`](task_792ae782ed49.md) | — | 2026-08-28 | - **작업 목적**: scripts/build_generalization_fixture.py의 ChromaDB 근거 검증 경로에 남아 있던 fail-open 결함을 제거하고, 조회 실패 시 즉시 fixture 생성을 중단하는 ... |
| [`task_57b62635a363.md`](task_57b62635a363.md) | — | 2026-08-28 | - **목적**: RAG 질의 처리 시간을 검색(vector / lexical / sql)과 LLM 생성 구간으로 분해 계측하여, 특정 긴 질의(예: q03, q08, q25 등)가 수십 초를 소모하거나 타임아웃되는 원인을 명확... |
| [`rag_segment_metrics_20260828.md`](rag_segment_metrics_20260828.md) | — | 2026-08-28 | RAG(Retrieval-Augmented Generation) 파이프라인에서 특정 질의가 수십 초를 소모하거나 타임아웃되는 현상이 발생할 때, 병목이 검색 단계(SQL / Vector / Lexical)인지, 컨텍스트 조립인지... |
| [`exact_title_lexical_channel_survey_20260828.md`](exact_title_lexical_channel_survey_20260828.md) | [`task_0c19e7f85c83.md`](task_0c19e7f85c83.md) | 2026-08-28 | src/rag/vector_store.py:140-176에 정의된 _rerank_by_exact_title 함수는 질의(semantic_query)와 각 문서의 공고명(doc_title)을 정규화 키로 변환한 후 상호 일치 여부... |
| [`exact_title_lexical_channel_impl_20260828.md`](exact_title_lexical_channel_impl_20260828.md) | — | 2026-08-28 | - 기존 정확 공고명 검색은 ChromaDB 임베딩 검색 시 후보 풀을 30개로 강제 확대(DEFAULT_CANDIDATE_POOL_SIZE = 30)한 뒤, 본문 공고명을 파싱하여 _rerank_by_exact_title()로... |
| [`conditional_vector_bypass_survey_20260828.md`](conditional_vector_bypass_survey_20260828.md) | — | 2026-08-28 | 현재 하이브리드 RAG 엔진의 컨텍스트 준비 함수(HybridRAGEngine._prepare_context, src/rag/engine.py:740-908)는 사용자 질의에 대해 계획을 수립한 후 고정된 순서로 검색 채널들을 ... |
| [`conditional_vector_bypass_impl_20260828.md`](conditional_vector_bypass_impl_20260828.md) | — | 2026-08-28 | 기존 하이브리드 RAG 엔진(src/rag/engine.py)은 검색 채널 실행 순서가 SQL -> Vector (ChromaDB 30개 후보 조회) -> Lexical (Meilisearch) 순서로 고정되어 있었습니다. |
| [`llm_quality_fixture_v2_confirmation_20260827.md`](llm_quality_fixture_v2_confirmation_20260827.md) | — | 2026-08-27 | docs/ops/llm_generalization_measurement_design.md 3.3 절은 fixture 문항을 사람이 |
| [`task_bbe173506d13.md`](task_bbe173506d13.md) | — | 2026-08-26 | bidding_kb ChromaDB 벡터 컬렉션의 메타데이터에는 category, has_result, type, id, doc_hash, fmt 6개 키만 존재하여, 자연어 질의 플래너가 추출한 institution_name(... |
| [`task_fea75d942a16.md`](task_fea75d942a16.md) | — | 2026-08-25 | 기존 scripts/validate_llm_quality_fixture.py는 로컬 및 CI 환경에서 ChromaDB SQLite 파일(chroma.sqlite3)을 찾을 수 없으면 "실재 검증 건너뜀"으로 처리하고 종료 코드 ... |
| [`task_5df3f4d1da4f.md`](task_5df3f4d1da4f.md) | — | 2026-08-25 | 기존 src/rag/vector_store.py의 retrieve_semantic_context는 collection.query(query_texts=[semantic_query], n_results=plan.top_k)만 호출... |
| [`task_cd8421ddd466.md`](task_cd8421ddd466.md) | — | 2026-08-24 | 수정일**: 2026-08-24 (1차 반려 조치 및 ChromaDB 실재 근거 결박 완료) |
| [`task_s2.md`](task_s2.md) | — | 2026-08-18 | src/tasks, src/ml, src/rag 디렉터리 내의 모든 소스 코드를 대상으로 예외 처리, 기본값 반환, 반환 타입 불일치, 상태 승격 로직을 전수 조사하였습니다. |
| [`t1.md`](t1.md) | — | 2026-08-18 | src/tasks/automation_tasks.py, tests/test_task_offload_automation.py |
| [`b1.md`](b1.md) | — | 2026-08-18 | - **목적**: src/rag/structured_data.py의 최장 함수인 retrieve_structured_data의 반복 및 세부 로직 블록을 동일 모듈 내 내부 헬퍼 함수로 추출하여 가독성과 유지보수성을 높이고 함수... |
| [`s3.md`](s3.md) | — | 2026-08-17 | 기존 src/app/services/kb_builder.py(560줄)에서 문서 생성과 공고 해석 묶음의 책임을 분리하여 src/app/services/kb_document_builder.py로 이식하였습니다. 이를 통해 두 파... |
| [`task_da6671df0347.md`](task_da6671df0347.md) | — | — | 운영 Compose의 네트워크를 internal과 egress로 분리했습니다. db, redis, meilisearch는 internal: true 네트워크에만 두고, app과 worker는 두 네트워크에 연결했습니다. prox... |
| [`task_7ba76bc4cb71.md`](task_7ba76bc4cb71.md) | — | — | - Lexical 어휘 검색(Meilisearch)에서 정확 공고명 일치(_normalize_match_key)가 확인되었을 때 ChromaDB 후보 풀 30 조회를 생략하는 **Conditional Vector Bypass**... |
| [`task_5c9b902db68f.md`](task_5c9b902db68f.md) | — | — | - Lexical 어휘 검색(Meilisearch)에서 정확 공고명 일치(_normalize_match_key)가 확인되었을 때 ChromaDB 후보 풀 30 조회를 생략하는 **Conditional Vector Bypass**... |
| [`task_2c66139a4a75.md`](task_2c66139a4a75.md) | — | — | 상세는 task_z1_windows_remaining.md 2절. |
| [`task_22fb73627e8c.md`](task_22fb73627e8c.md) | — | — | Wave AJ2에서 워커 런처 고지문의 역할별 분기(빌더용 COMMIT_NOTICE vs 리뷰어용 REVIEWER_NOTICE)가 도입되었으나, 실제 Dispatch 경로에서 리뷰어 워커에게 여전히 COMMIT_NOTICE(커밋... |
| [`task_033ef1fb805d.md`](task_033ef1fb805d.md) | [`bd2_restore_drill_prep_review_20260911.md`](bd2_restore_drill_prep_review_20260911.md)<br>[`task_z1_backup_retention.md`](task_z1_backup_retention.md) | — | scripts.backup_recovery_core.REQUIRED_BACKUP_ASSETS에 database, chroma_db, |

---

## 6. SSR/HTMX 프론트엔드 및 웹 엔드포인트

Django/React에서 FastAPI SSR+HTMX로의 화면 이관, E2E 테스트(Playwright), compare-stats 및 템플릿 구현 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`ba1_compare_stats_snapshot_review_20260911.md`](ba1_compare_stats_snapshot_review_20260911.md) | [`bb1_monthly_snapshot_review_20260911.md`](bb1_monthly_snapshot_review_20260911.md) | 2026-09-11 | 스냅샷 경로와 실시간 폴백 경로는 같은 질의·같은 금액 상한·같은 정렬·같은 상위 10 절단·같은 기관명 미제외 규칙을 쓴다. 스냅샷이 없거나 2일을 넘거나 payload 형태가 리스트/정수 규약을 벗어나면 실시간으로 돌아가며,... |
| [`au1_compare_stats_exists_verification_20260910.md`](au1_compare_stats_exists_verification_20260910.md) | — | 2026-09-10 | src/app/services/dashboard.py의 캐시 미적중 매칭 건수 조건을 BidResult.id를 상관하는 EXISTS로 바꿨습니다. 공고번호가 같은 낙찰 결과가 |
| [`task_6da3b6252944.md`](task_6da3b6252944.md) | — | 2026-09-08 | - Orca 조율 환경에서 orca_taskctl.py는 시도 단위 격리를 보장하기 위해 preamble_{task_id}_{dispatch_id}_{nonce}.txt 형태의 고유 파일명으로 preamble 지시문을 생성합니다. |
| [`task_234b47cdddc7.md`](task_234b47cdddc7.md) | — | 2026-09-08 | 2026-09-07 세션 종료 점검 과정에서 이미 회수된 워커 터미널을 대상으로 하는 scripts/orca_auto_approve.py 프로세스가 17개 누적되어 있는 현상이 발견되었습니다. |
| [`task_1b92e3a1f7fb.md`](task_1b92e3a1f7fb.md) | — | 2026-09-08 | 선행 Task에서 Claude Code 런처(scripts/orca_claude_launch.py)의 --dangerously-skip-permissions 플래그를 제거하고 --permission-mode 인자로 교체하였으나,... |
| [`task_8a3ab0739044.md`](task_8a3ab0739044.md) | — | 2026-09-07 | 본 작업은 Orca 워커가 Task Capsule 의 search_scope(deny_by_default)와 allowed_read_files 범위를 벗어난 경로를 실제로 읽었거나 접근했는지 터미널 버퍼(또는 버퍼 텍스트 파일)... |
| [`task_76e874acc927.md`](task_76e874acc927.md) | — | 2026-09-07 | 2026-09-07 세션에서 상시 감시기(scripts/orca_worker_watch.py)가 정상 작업 중인 워커를 "Antigravity 부팅이 인증 단계에서 정체"로 표시하는 오판이 발생했습니다. 코디네이터가 터미널을 직... |
| [`task_0f4bd17b8384.md`](task_0f4bd17b8384.md) | — | 2026-09-07 | 워커 터미널의 권한 자동 승인 감시기(scripts/orca_auto_approve.py)에서 $( ) 명령 치환과 while read / for in 루프가 섞인 안전한 읽기 전용 조사 명령이 화이트리스트를 벗어나 통째로 보류... |
| [`task_f1cbfc0d73c2.md`](task_f1cbfc0d73c2.md) | — | 2026-09-06 | 사용자가 2026-09-06에 확정한 복구 목표 RPO 24시간·RTO 4시간을 docs/ops/rpo_rto_policy.md로 신설했습니다. 정본 상태 원장 docs/context/current_state_facts.yaml... |
| [`task_d9dca35fbf0f.md`](task_d9dca35fbf0f.md) | — | 2026-09-06 | tests/e2e/test_ssr_auth.py, tests/e2e/conftest.py |
| [`task_cc9d7da6e8e4.md`](task_cc9d7da6e8e4.md) | — | 2026-09-05 | Wave U 및 이전 운영에서 발생한 Level 1 기계 검증 게이트의 구조적 구멍 2건 및 expand 연동 결함을 해소합니다: |
| [`task_c7da7b57943f.md`](task_c7da7b57943f.md) | — | 2026-09-05 | 정기 백업 스케줄의 보존 정책이 실제 디스크 정리를 수행하도록 수정하여 디스크 상한을 강제하고(R-08), 삭제 전 안전장치 및 디스크 여유 공간 경보 체계를 연결했습니다. |
| [`task_7f0659b4d4fc.md`](task_7f0659b4d4fc.md) | — | 2026-09-05 | 승격·롤백의 서빙 디렉터리 두 번 이동을 없앴습니다. 같은 볼륨 파일 단위 os.replace 로 서빙 경로 이름을 유지하고, Windows 심볼릭 링크와 Docker 바인드 마운트 링크 교체는 채택하지 않았습니다. 중간 실패는... |
| [`task_3e6c7d5bf5c1.md`](task_3e6c7d5bf5c1.md) | — | 2026-09-05 | 2026-09-05 외부 진단 보고서 R-01에 따라, 백업 스냅샷 검증기(verify_snapshot) 및 복원 사전 점검(execute_restore)의 결함을 해결했습니다. |
| [`task_ca4426a52f9b.md`](task_ca4426a52f9b.md) | — | 2026-09-04 | 공고 금액 집계를 질의 시점 JSON 파싱에서 base_amount 컬럼 기반으로 전환 및 Decimal 통일 |
| [`task_7970dc7606b8.md`](task_7970dc7606b8.md) | — | 2026-09-04 | 로컬 Claude Code CLI(/opt/homebrew/bin/claude 2.1.259)의 Claude Pro 구독 기반으로 claude-sonnet-5 (effort medium) 워커를 안전하게 probe하고, Orca... |
| [`task_fd3bcd11531f.md`](task_fd3bcd11531f.md) | — | 2026-09-03 | Wave J의 Phase 2a에서 구축된 임시 SQLite 격리 DB 및 get_db 의존성 오버라이드, 세션 쿠키(bidbox_session) 주입 픽스처를 기반으로, Jinja2 SSR 핵심 4대 영역(인증 플로우, 공고 목... |
| [`task_d892eca5b0c4.md`](task_d892eca5b0c4.md) | — | 2026-09-03 | 본 과업은 refac_bid_box의 프론트엔드 실시간 인터랙션 및 SPA 화면에 대한 브라우저 E2E 테스트 체계를 구축하는 것을 목적으로 합니다. |
| [`task_cabad8162fd7.md`](task_cabad8162fd7.md) | — | 2026-09-03 | 이벤트 루프에서 생성된 SQLAlchemy Session 객체를 asyncio.to_thread를 통해 워커 스레드로 넘겨 사용하던 구조적 결함을 전면 해소했습니다. |
| [`task_89889f5622f0.md`](task_89889f5622f0.md) | — | 2026-09-03 | 기존 CI 환경에서는 브라우저 E2E 테스트(31개 시나리오)가 cross-platform-test의 Ubuntu 3.11 매트릭스 내부에서 전량 pytest와 혼합 실행되었습니다. 이로 인해 다음과 같은 문제점이 존재했습니다: |
| [`task_7fb5dc887992.md`](task_7fb5dc887992.md) | — | 2026-09-03 | - 기존 CI 환경(.github/workflows/ci.yml)에는 Playwright Chromium 브라우저 설치 단계가 존재하지 않아 E2E 테스트가 조용히 skip 되었습니다. |
| [`task_4b88e29dc3f9.md`](task_4b88e29dc3f9.md) | — | 2026-09-03 | 선행 작업(task_0bba466af5f3)에서 Redis SET NX EX 기반의 단일 실행 claim 및 fail-closed 정책을 구현하였으나, 코디네이터 Level 3 아키텍처 심층 검토에서 다음과 같은 3대 분산 환경... |
| [`task_0bba466af5f3.md`](task_0bba466af5f3.md) | — | 2026-09-03 | 선행 작업(task_1a6eeab35699)에서 기동 시 스케줄 따라잡기(Startup Catch-up)를 구현하고 독립 리뷰(task_794ea3b9cf87)는 통과(Pass) 판정을 내렸으나, 코디네이터 Level 3 아키텍... |
| [`task_007ee54eee22.md`](task_007ee54eee22.md) | [`task_15176df9c06f.md`](task_15176df9c06f.md) | 2026-09-03 | Antigravity(agy) TUI는 orca terminal create --command "agy ..." 형태로 직접 기동할 경우 스플래시 화면에서 정체되는 문제가 반복되었습니다. 이를 해결하기 위해 정본 런처인 scri... |
| [`task_d263b92822bb.md`](task_d263b92822bb.md) | — | 2026-09-02 | T1(task_ac156735df14) 작업을 통해 인증된 사용자 간 대화 상태의 교차 접근(IDOR)과 user: 접두사 메모리 키 위조가 차단되었습니다. 그러나 user_id 가 None 인 익명 사용자 요청 간에는 None... |
| [`task_bedb4b8bf44b.md`](task_bedb4b8bf44b.md) | — | 2026-09-02 | Capsule objective 가 요구한 대로, 실제 MySQL 8 인스턴스에서 동시 실행과 실패 복구를 검증하는 통합 테스트를 5건 추가했습니다. 모든 테스트는 mysql_integration 마커로 묶고, 격리된 concu... |
| [`task_817dbd6a2a28.md`](task_817dbd6a2a28.md) | — | 2026-09-02 | src/app/api/v1/chatbot.py:185-187은 confirmation_token이 비어 있으면 검증을 생략하고 텍스트 확인 분기로 넘어간다. 이번 변경은 automation_tokens.py의 resolve_co... |
| [`task_7e2759654663.md`](task_7e2759654663.md) | — | 2026-09-02 | 본 작업은 refac_bid_box 서비스의 인증 경계를 보강하고 서비스 거부(DoS) 및 교차 사이트 요청 위조(CSRF) 위험을 차단하기 위해 수행되었습니다. |
| [`task_4d362235e897.md`](task_4d362235e897.md) | — | 2026-09-02 | 코디네이터가 Orca 정본 스킬(orca skills get orchestration)을 확인하지 않고 워커를 띄우거나 낡은 지침을 기준으로 저수준 경로를 수동 조립하는 실패를 기계적으로 차단하기 위해 **2층 방어 체계(2-L... |
| [`task_1310a624a067.md`](task_1310a624a067.md) | — | 2026-09-02 | 본 과업은 2026-09-02 보완점 분석 보고서 3.4절(동기 SQLAlchemy Session 소유권 및 예외 경로 복구)과 3.5절(수집 오류 로깅 시 G2B 서비스 키 마스킹)에 대응하는 작업입니다. |
| [`task_u3_approval_and_reviewer.md`](task_u3_approval_and_reviewer.md) | — | 2026-09-01 | 2026-09-01 외부 보안 및 정합성 감사에서 확인된 두 가지 취약점을 원천 차단하고 보강하였습니다. 1. **취약점 1 (약한 DB 판정 자동 승인)**: |
| [`task_j3_if_review.md`](task_j3_if_review.md) | — | 2026-09-01 | 리뷰어**: Qwen Code (task_cb09b06aa7ac) |
| [`task_58593d56ea19.md`](task_58593d56ea19.md) | — | 2026-08-30 | 2026-08-29 세션에서 코디네이터가 다중 워커 기동 후 감시를 수행하기 위해 셸 스크립트로 임의의 감시 루프를 직접 작성해야 했습니다. scripts/orca_worker_watch.py 가 호출 시점의 1회성 스냅샷만 반... |
| [`worker_done_verification_truth_20260828.md`](worker_done_verification_truth_20260828.md) | — | 2026-08-28 | 2026-08-28 1차 게이트 승격 작업(docs/analysis/worker_done_v2_gate_promotion_20260828.md)을 통해 commit SHA 실존성, 브랜치 실존성, changed_files dif... |
| [`worker_done_v2_gate_survey_20260828.md`](worker_done_v2_gate_survey_20260828.md) | — | 2026-08-28 | 대상 Task**: task_28394bf3d41f |
| [`worker_done_v2_gate_promotion_20260828.md`](worker_done_v2_gate_promotion_20260828.md) | — | 2026-08-28 | 외부 감사에서 ORCA_WORKER_DONE_V2가 형식 검증기는 존재하나 실제 병합을 막는 차단 게이트로 동작하지 않는다는 지적이 제기되었습니다. 특히 2026-08-28 Run 에서 일부 Task가 worker_done.js... |
| [`task_ea688271d62b.md`](task_ea688271d62b.md) | — | 2026-08-28 | - **목표**: worker_done 보고의 진실성(커밋 SHA 실존, 브랜치 실존, 변경 파일 일치)을 기계로 검증하고, 보고 파일이 없으면 Level 1 게이트가 PASS 할 수 없도록 실행 게이트로 승격. |
| [`task_dda88e2e6fe3.md`](task_dda88e2e6fe3.md) | — | 2026-08-28 | - 2026-08-28 운영 세션에서 Antigravity 워커 3대가 Accept this file edit? 파일 편집 승인 대화창에서 대기하며 멈췄으나, 기존 scripts/orca_worker_watch.py 감시 도구는... |
| [`task_7ff9116d6561.md`](task_7ff9116d6561.md) | — | 2026-08-28 | 기존 scripts/orca_auto_approve.py는 SAFE_PREFIXES 튜플을 기반으로 명령 문자열 접두사를 단순 매칭하여 자동 승인을 수행했습니다. |
| [`task_109829469d92.md`](task_109829469d92.md) | — | 2026-08-28 | 2026-08-28 세션 중 기존 워크트리(path: 선택자)에 워커를 부착하려 할 때 기동이 실패하는 현상이 발생했습니다. 당시 출력된 오류 메시지는 "Creation and setup options apply only to ... |
| [`task_1049283686bf.md`](task_1049283686bf.md) | — | 2026-08-28 | - **목표**: worker_done 보고의 verification 배열 진실성을 검증하고, 워커가 적어 낸 검증 명령과 결과가 실제 실행 결과와 일치하는지 대조하는 게이트를 추가. |
| [`task_e8950ca99974.md`](task_e8950ca99974.md) | — | 2026-08-26 | 2026-08-25 base.html 로컬화 이후 잔여 외부 CDN 참조 4건(Chart.js 3곳, marked 1곳)을 src/app/static/vendor/ 로 이관하여 애플리케이션 Jinja2 템플릿의 외부 자산 참조를... |
| [`task_bdf61eec4069.md`](task_bdf61eec4069.md) | — | 2026-08-26 | 브라우저 JIT(vendor/tailwindcss/3.4.16/tailwindcss.js + 인라인 tailwind.config)를 제거하고, tailwind.config.js + npm run build:css 산출물 src/... |
| [`task_ffe453b30f9d.md`](task_ffe453b30f9d.md) | — | 2026-08-25 | 1. src/app/templates/base.html의 외부 CDN 참조 7종 및 Google Fonts preconnect 태그 2종을 제거하고, 로컬 정적 디렉터리(src/app/static/vendor/) 서빙 경로로 변... |
| [`cdn_asset_localization_20260825.md`](cdn_asset_localization_20260825.md) | — | 2026-08-25 | 본 작업은 refac_bid_box 프로젝트의 SSR(서버 사이드 렌더링) 템플릿인 src/app/templates/base.html에서 외부 CDN(jsdelivr, cdnjs, Google Fonts, Tailwind Pla... |
| [`task_orca_capsule_contract_rework.md`](task_orca_capsule_contract_rework.md) | — | 2026-08-24 | 본 작업은 Orca 다중 에이전트 환경에서 발생한 두 가지 Task Capsule 생성 계약 결함을 해결하기 위해 수행되었습니다. |
| [`task_8f19bd20b52a.md`](task_8f19bd20b52a.md) | — | 2026-08-24 | 외부 감사 P1 지적 중 코드 수정 없이 문서만으로 닫히는 4건을 정정했습니다. 1. **Arq provenance 기술 정정** — docs/analysis/gpt_audit_reverification_20260824.md 감... |
| [`task_1bf1ed2c2acc.md`](task_1bf1ed2c2acc.md) | — | 2026-08-24 | 외부 감사 P2-3(감사 증거 문서 링크 무결성 확보)의 일환으로 아래 작업을 수행하였습니다. 1. **표준 라이브러리 기반 검증기 작성 (scripts/validate_doc_links.py)**: |
| [`p1_1_merge_target_sha_pinning.md`](p1_1_merge_target_sha_pinning.md) | — | 2026-08-23 | 기존 scripts/merge_verified_branch.py는 finalize evidence의 source_branch, target_branch, commit(source ref SHA), level1, reviewer ... |
| [`s1.md`](s1.md) | — | 2026-08-17 | src/ml/trainer.py (838줄)의 복잡도를 완화하고 모듈별 단일 책임을 부여하기 위해 사양에 정의된 고정 경계에 따라 세 개의 모듈(splitters.py, training_config.py, conformal.py... |
| [`task_x2_residual_cleanup.md`](task_x2_residual_cleanup.md) | — | — | 명령: ```bash docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.12.5 |
| [`task_s1.md`](task_s1.md) | — | — | 2026-08-18 중간 상태(실패, 미검증, 절단, 부분, 미도달, 알 수 없음)가 SUCCESS 또는 정상 응답으로 부당하게 승격되는 fail-open 패턴을 src/app/services와 src/app/api 전역에서 전... |
| [`task_cb09b06aa7ac.md`](task_cb09b06aa7ac.md) | — | — | **PASS** -- 모든 required_change 8개 항목 구현 완료, acceptance 6개 항목 모두 충족. |
| [`task_c8e14bf8d6cd.md`](task_c8e14bf8d6cd.md) | — | — | Dockerfile, docker-compose.prod.yml |
| [`task_b7f70a86d03e.md`](task_b7f70a86d03e.md) | — | — | 2026-09-07 Wave AH 인수인계(8.1절 후속 과제)에서 확인된 바와 같이, 기존 규약 문서(docs/ops/git_branching_strategy.md 3장)는 "영어 또는 한국어 가능"으로 기술되어 있어 규약 정... |
| [`task_b6cef03e3887.md`](task_b6cef03e3887.md) | — | — | src/tasks/worker.py 는 읽기만 했다. ```text docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.12.5 |
| [`task_8cf66bb59ade.md`](task_8cf66bb59ade.md) | — | — | POST /api/v1/chatbot/chat, POST /api/v1/chatbot/chat/stream, |
| [`task_82b9a808dc6a.md`](task_82b9a808dc6a.md) | — | — | +-------------------------------------------------------------------------+ |
| [`task_7db7ea0df02a.md`](task_7db7ea0df02a.md) | — | — | 2026-09-07 Wave AH 인수인계 후속 과제에 따라, scripts/orca_worker_watch.py의 terminal_tail 함수 및 screen_tail 매개변수 이름을 실제 동작에 부합하도록 정리하였습니다. |
| [`task_78b8425799bd.md`](task_78b8425799bd.md) | — | — | - Wave AI 조율 중 정상 작업 중인 워커 화면에 Dispatch 지시문(preamble) 템플릿이 남아있을 때, 감시기(scripts/orca_worker_watch.py)가 이를 실제 worker_done 보고로 오인하... |
| [`task_4465d5c617a0.md`](task_4465d5c617a0.md) | — | — | - Python·npm 의존성 취약점 스캔을 CI에 추가했습니다. - Trivy 컨테이너 이미지 스캔과 SPDX JSON SBOM 생성·아티팩트 업로드를 추가했습니다. |
| [`task_3329e9d1bebd.md`](task_3329e9d1bebd.md) | — | — | 외부 재감사에서 지적된 generalization 설계서 내부의 판정 기준 충돌(55.0% 절대선 대 e4b 61.8% 상대선)과 문서·코드 간의 소규모 드리프트 3건을 정정하였습니다. |
| [`task_27d0434b9814.md`](task_27d0434b9814.md) | — | — | 외부 보안 감사에서 지적된 P1 결함(자동화 실행 확인 토큰 단일 소비 부재 및 동시성 중복 큐잉 가능성)을 해결하기 위해, 인메모리 집합 기반 소비 기록을 전면 제거하고 Redis SET NX EX 원자적 명령과 DB 조건부 ... |
| [`task_0efb961554ff.md`](task_0efb961554ff.md) | — | — | orca terminal create --command "agy --model <id>" 로 Antigravity TUI 를 띄우면 |

---

## 7. 인프라, 비동기 큐(Arq) 및 데이터 정합성

DB 마이그레이션(MySQL 8), Arq 백그라운드 태스크, 백업/복구 및 G1 데이터 무손실 검증 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`task_6304378e4a69.md`](task_6304378e4a69.md) | — | 2026-09-07 | 런처 경로 Dispatch는 대상 터미널이 사전에 런처 스크립트(scripts/orca_agy_launch.py 등)를 실행하여 preamble 파일 생성을 기다리고 있는 상태를 전제로 동작합니다. |
| [`task_fd161cb69264.md`](task_fd161cb69264.md) | — | 2026-09-06 | 애플리케이션 계측은 이미 끝나 있었다. src/app/core/observability.py 에 OTel SDK 초기화, |
| [`task_f7bde5d00f87.md`](task_f7bde5d00f87.md) | — | 2026-09-06 | Level 1 게이트 3 docker 검증 허용 목록 |
| [`task_bd846f86dc0b.md`](task_bd846f86dc0b.md) | — | 2026-09-06 | - 매니페스트 없는 하위 디렉터리도 목록에 포함하되 valid=False, created_at/head_commit 은 "unknown", 사유는 error 키(매니페스트 파일 없음)로 구분해 표시한다. |
| [`task_2a088c8fd07b.md`](task_2a088c8fd07b.md) | — | 2026-09-06 | - scripts/backup_recovery_core.py의 get_db_config가 DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME을 읽으므로 backup 서비스에 전부 전달하며 컨테이... |
| [`task_29305aa797b8.md`](task_29305aa797b8.md) | — | 2026-09-06 | scripts/backup_snapshots.py 매니페스트 부재 구간 해소 |
| [`task_d9527d72e596.md`](task_d9527d72e596.md) | — | 2026-09-05 | startup catch-up 을 Arq 큐의 정규 잡으로 넣고, 기존 record_catchup_attempt 에 대상·실행·실패·건너뜀 원장을 확장했으며, 쿨다운 키 SET NX 로 동시 기동 중복 실행을 막았다. 워커 기동... |
| [`task_af4d7316b2d3.md`](task_af4d7316b2d3.md) | — | 2026-09-05 | 2026-09-04 외부 진단 보고서 T-01에 따르면, OpenTelemetry 분산 추적이 활성화되어 있는 환경에서도 Arq 비동기 배치 작업이 예외로 비정상 종료되었을 때 Datadog/Jaeger 등 수집기 상에서 해당 ... |
| [`task_943261d27926.md`](task_943261d27926.md) | — | 2026-09-05 | - **목표**: 백업 행 수 조회에서 조회 실패와 실제 0행을 명확히 구분(R-09)하여 증거 없는 백업이 정상 백업으로 둔갑하는 정합성 결함을 해결. |
| [`task_82b3c4587fbe.md`](task_82b3c4587fbe.md) | — | 2026-09-05 | 2026-09-05 T-01 작업의 Level 2 리뷰에서 지적된 잔여 리스크로, OpenTelemetry 분산 추적이 활성화된 환경에서 Arq 비동기 작업이 취소(asyncio.CancelledError)되었을 때 최상위 sp... |
| [`task_36bfb6975d21.md`](task_36bfb6975d21.md) | — | 2026-09-04 | - **목적**: 대시보드 요약 통계 조회 경로(get_bid_dataset_summary)에서 477초 소요되는 동기 전체 재집계 호출을 제거하고, 읽기(스냅샷 즉시 반환)와 쓰기(Arq 백그라운드 워커 재집계)를 분리. |
| [`task_0dfc2f73ee31.md`](task_0dfc2f73ee31.md) | — | 2026-09-04 | GitHub Actions CI 환경에서 tests/test_task_offload_scheduled.py의 두 테스트가 AssertionError: assert 'failed' == 'success'로 실패하며 main CI ... |
| [`mypy_24_classification_20260904.md`](mypy_24_classification_20260904.md) | — | 2026-09-04 | uv run mypy src scripts/backup_recovery.py 실행 시 7개 파일에서 총 24건의 오류가 검출되었습니다. |
| [`base_amount_column_mismatch_343_20260904.md`](base_amount_column_mismatch_343_20260904.md) | — | 2026-09-04 | 집계를 JSON 파싱에서 컬럼 기반으로 바꿀 때 공고 총액이 달라지는 폭은 **최대 107원**입니다. 현재 총액 2,125,507,790,559,697원(약 2,126조) 대비 |
| [`task_f435b4db3710.md`](task_f435b4db3710.md) | — | 2026-09-03 | - .github/workflows/release.yml: 준비 상태 게이트, 태그 push, GitHub Release 생성 순서를 정의했습니다. |
| [`task_60f2062df7f7.md`](task_60f2062df7f7.md) | — | 2026-09-03 | 커밋 1957073에서 구현된 스케줄 claim 소유 토큰 원자 해제 및 실패 시 claim 유지 로직을 유지하면서, 다음 두 가지 결함을 최소 변경으로 보완하고 회귀 테스트로 고정했습니다. |
| [`task_34f464043a1f.md`](task_34f464043a1f.md) | — | 2026-09-03 | 기존 tests/conftest.py의 _reset_login_rate_limit autouse fixture는 매 테스트 전후 실제 Redis 연결을 맺고 RATE_LIMIT_IP_PREFIX 및 RATE_LIMIT_ACCOU... |
| [`task_a2659e1332c4.md`](task_a2659e1332c4.md) | — | 2026-09-02 | 기존 G1 데이터 무손실 검증(scripts/verify_migration.py)은 테이블 존재 여부(EXPECTED_TABLES)와 2개 핵심 테이블의 최소 행 수 하한 비율(MIN_ROW_COUNT_RATIO)만 확인하여, ... |
| [`task_085277f3ab30.md`](task_085277f3ab30.md) | [`task_072fc411a3dc.md`](task_072fc411a3dc.md)<br>[`task_z2_rowcount_truth.md`](task_z2_rowcount_truth.md)<br>[`task_z2_state_structuring.md`](task_z2_state_structuring.md) | 2026-09-02 | scripts/verify_migration.py 의 5단계 verify_row_counts 는 bid_announcements·bid_results 두 테이블의 **누적 행 수**가 BASELINE_ROW_COUNTS 대비 M... |
| [`task_8512dbfc034b.md`](task_8512dbfc034b.md) | — | 2026-08-30 | 2026-08-29 워커 운영 세션에서 Antigravity 워커 2대가 CLI 만족도 설문 프롬프트(How's the CLI experience so far? ... [0] Skip)에 걸려 진행이 정체되는 문제가 관측되었습니... |
| [`task_3a6355447a9d.md`](task_3a6355447a9d.md) | — | 2026-08-26 | 인벤토리에서 오류 1건으로 확인된 17개 모듈의 mypy 오류를 코드 수정으로 해소하고, pyproject.toml의 [[tool.mypy.overrides]] 목록에서 해당 모듈을 제거한다. |
| [`mypy_special_blocks_20260826.md`](mypy_special_blocks_20260826.md) | — | 2026-08-26 | 11블록 13모듈 전부 제거. 상세는 task_8a0cca3400f6.md 참조. |
| [`mypy_argtype_block_20260826.md`](mypy_argtype_block_20260826.md) | — | 2026-08-26 | pyproject.toml 첫 arg-type override 블록에 16모듈이 등재되어 있었습니다. 해당 블록 전체를 제거했습니다. 16모듈 모두 override 없이 uv run mypy 를 통과합니다. |
| [`task_5674e5f5008a.md`](task_5674e5f5008a.md) | — | 2026-08-25 | 2026-08-24 정식 캘리브레이션으로 경로별 기준선이 확정됐으나, 세 가지 잔여 결함이 있었다. 1. RepetitionThresholds 의 min_throughput_tasks_per_sec(900.0)와 |
| [`task_orca_ops_boundary.md`](task_orca_ops_boundary.md) | — | 2026-08-24 | 본 작업은 Orca 다중 에이전트 환경에서 발생한 두 가지 핵심 경계 결함을 해결하기 위해 수행되었습니다. 1. **신뢰 잠금(Trust Lock)의 지원 부재 시 Fail-Open 및 Windows 비정상 종료 회귀**: |
| [`task_ef39109bd5a5.md`](task_ef39109bd5a5.md) | — | 2026-08-24 | Arq 캘리브레이션 설계서를 운영자 수동 절차 없이 실행 가능하게 만든다. 1. Frozen baseline 디렉터리 자동 생성 (MANUAL 해소) — --frozen-baseline |
| [`task_e860cec0fde5.md`](task_e860cec0fde5.md) | — | 2026-08-24 | 1. arq_calibration_design_20260824.md 6장의 퇴화 산식(max(Q_p(T, 0.05), min(T) * 0.95), max(Q_p(P, 0.95), max(P) * 1.05))을 제거하고, 중앙값 ... |
| [`task_22512afde3d9.md`](task_22512afde3d9.md) | — | 2026-08-24 | Arq 정식 캘리브레이션 실행을 막던 하네스 자동화 결손 3건(BLOCKER)을 닫는다. 1. 주변 부하 규약 자동 강제 (중앙값 30%, 최대 50% 초과 시 strict 에서 중단) |
| [`mypy_debt_phase1_20260824.md`](mypy_debt_phase1_20260824.md) | — | 2026-08-24 | pyproject.toml의 [tool.mypy] 설정에 전역 비활성화(disable_error_code)되어 있던 5종 오류 코드 중 실제 위반이 없거나 적은 3종(return-value, attr-defined, union-... |
| [`trust_lock_hardening_20260823.md`](trust_lock_hardening_20260823.md) | — | 2026-08-23 | Antigravity CLI 워커 생성 전 워크스페이스 경로를 신뢰 목록(settings.json, trustedFolders.json)에 사전 등록하는 과정에서 두 가지 결함이 식별되었습니다. |
| [`task_current_state_cleanup_rework.md`](task_current_state_cleanup_rework.md) | — | 2026-08-22 | 1차 산출물에서 발생했던 1~3장 및 5~7장의 불필요한 문장·표 재서식을 main 원본 기준으로 완전 복구하고, 과업 범위에 맞춰 4장(진행 과업) 및 4.1절(종결 계열 요약)만을 중심적으로 정비했습니다. |
| [`task_a650d904b80a.md`](task_a650d904b80a.md) | — | — | 기준선 부재 시 현재 손상 상태가 정답으로 저장되는 경로 제거 |
| [`task_4962455374cc.md`](task_4962455374cc.md) | — | — | - Redis CacheLayer를 통해 워커 식별자와 마지막 heartbeat 시각을 기록합니다. - heartbeat 시점의 arq:queue 대기 건수를 함께 기록합니다. |
| [`task_1a63a0432aea.md`](task_1a63a0432aea.md) | — | — | 운영 전용 docker-compose.prod.yml 파일을 신설하여 개발용 설정(docker-compose.yml)과 분리하였습니다. 최소 권한 DB 계정, 내부 전용 네트워크, non-root 실행, 자원 제한과 로그 회전을... |
| [`task_0cbd2032fc8b.md`](task_0cbd2032fc8b.md) | — | — | - 운영 Compose에 Caddy 공식 이미지를 proxy 서비스로 추가했습니다. - 앱의 호스트 포트 게시를 제거하고 Caddy의 443만 게시했습니다. |
| [`task_0a181c70b200.md`](task_0a181c70b200.md) | — | — | SQLite와 MySQL에서 결과 또는 실행 가능성이 실제로 달라지는 SQL 의미만 선정했습니다. 콜레이션, 숫자 나눗셈, ONLY_FULL_GROUP_BY, 날짜 버킷 함수, JSON 스칼라 추출을 각각 한 건씩 검증합니다. |
| [`t2.md`](t2.md) | — | — | refac_bid_box의 비동기 태스크 큐인 Arq 워커(src/tasks/worker.py)는 max_jobs=4 설정 하에 비동기 이벤트 루프 기반으로 동작합니다. |
| [`p2_2_stale_lock_ownership.md`](p2_2_stale_lock_ownership.md) | — | — | docs/handoff/2026-08-22_post_1a45ad5_audit.md P2-2: 기존 _settings_lock은 lock 파일에 보유 PID만 기록하고 finally 블록에서 소유권 확인 없이 같은 경로를 unli... |

---

## 8. 엔지니어링 품질, CI/CD 및 멀티에이전트 오케스트레이션

mypy 정적 검사 부채 해소, 크로스 플랫폼 CI(macOS/Windows), OpenTelemetry 계측 및 Orca 다중 에이전트 오케스트레이션 기록입니다.

| 대표 문서 | 관련 회차 및 보충 | 일자 | 판정 및 핵심 결과 |
| --- | --- | --- | --- |
| [`bm1_negotiation_price_source_recount_20260911.md`](bm1_negotiation_price_source_recount_20260911.md) | — | 2026-09-11 | **차단 사유는 그대로 유효합니다.** 협상에의한계약 공고 **121,052건 전부**에서 sucsfbidMthdAppStd 가 비어 있습니다. 기간은 2025-01-05 부터 2026-09-09 까지 |
| [`task_d20d24872128.md`](task_d20d24872128.md) | — | 2026-09-08 | 기존 저장소에는 agy, qwen, kimi, codex 런처만 구비되어 있어 claude, opencode, grok 세 CLI 는 워커 런처 경로를 사용할 수 없었습니다. 이에 따라 선행 조사(am5_launcher_gap_... |
| [`task_40fc30422c75.md`](task_40fc30422c75.md) | — | 2026-09-08 | 2026-09-07 세션 종료 점검에서 수동 게이트 실행 및 직접 병합으로 인해 finalize 경로를 타지 않고 회수된 워커 세션의 자동 승인 감시기 프로세스 17개가 정리되지 않은 채 남아 있는 문제가 확인되었습니다. |
| [`task_60ec2a1417ac.md`](task_60ec2a1417ac.md) | — | 2026-09-07 | 2026-09-07 Wave AI1에서 리뷰어 워커가 커밋할 변경사항이 없는 상태에서 커밋 강제 고지문(COMMIT_NOTICE)을 수신하여 리뷰어 계약(커밋 금지, 소스 수정 금지)과 충돌하며 작업이 정체되는 현상이 발생했습니... |
| [`task_5954f49f25a0.md`](task_5954f49f25a0.md) | — | 2026-09-07 | scripts/orca_read_scope_audit.py는 워커 터미널의 출력을 분석하여 Capsule의 allowed_read_files 및 search_scope.allowed_globs 범위를 벗어난 비인가 파일 접근을 ... |
| [`task_af2_opencode_delivery.md`](task_af2_opencode_delivery.md) | — | 2026-09-06 | Muse Spark(OpenCode) 워커를 터미널 부착 경로로 Dispatch 하면 워커는 지시를 받고 일하는데도 사후 도달 확인이 not_observed 로 끝나 종료 코드 3 |
| [`task_af1_gate_retry.md`](task_af1_gate_retry.md) | — | 2026-09-06 | 2026-09-06 Wave AA~AD에서 게이트가 테스트 실패를 네 번 보고했고 네 번 모두 단독 재실행에서 통과했습니다. 원인은 워커와 리뷰어와 게이트가 같은 머신에서 전량 스위트를 겹쳐 돌린 부하 오탐입니다. 게이트 3은 ... |
| [`task_a9888187277a.md`](task_a9888187277a.md) | — | 2026-09-06 | - scripts/orca_taskctl.py: 도달 표지 판정에서 ANSI 제거·공백 무시 재비교, 사후 확인에 terminal_read 전체 버퍼 fallback, 고지문 뒤 짧은 probe 확인문 |
| [`task_93d4fd925462.md`](task_93d4fd925462.md) | — | 2026-09-06 | 2026-09-06 세션에서 워커와 리뷰어 여덟 대 이상이 첫 worker_done 전송에서 capability 누락으로 거부됐다. Capsule 지시문에 토큰 위치를 명시해도 재발했으므로 |
| [`task_931b1e6c5a1e.md`](task_931b1e6c5a1e.md) | — | 2026-09-06 | scripts/orca_worker_done_guard.py 의 --send 경로는 --from 과 --dispatch-id 가 |
| [`task_217271924829.md`](task_217271924829.md) | — | 2026-09-06 | 2026-09-06 Wave AA~AD에서 게이트가 테스트 실패를 네 번 보고했고 네 번 모두 단독 재실행에서 통과했습니다. 원인은 워커와 리뷰어와 게이트가 같은 머신에서 전량 스위트를 겹쳐 돌린 부하 오탐입니다. 게이트 3은 ... |
| [`task_63f8823e4969.md`](task_63f8823e4969.md) | — | 2026-09-05 | 2026-09-04 외부 진단 보고서 S-02에서 지적된 바와 같이, CI 공급망 보안 게이트가 아무리 fail-closed로 강화되어도 워크플로에서 참조하는 액션과 도구가 이동 가능한 태그(v5, v4 등)나 동적 최신 버전(... |
| [`task_5e66c4c224d4.md`](task_5e66c4c224d4.md) | — | 2026-09-05 | **채택안: 불변 세대 디렉터리 + 파일 하나(LIVE)의 원자적 교체.** 승격·롤백은 완성된 트리 전체를 data/model_files/<model>/generations/<version>/ 에 올린 뒤에야 LIVE 한 줄을... |
| [`task_4fcf2a95ff6f.md`](task_4fcf2a95ff6f.md) | — | 2026-09-05 | 2026-09-04 외부 진단 보고서의 P1 항목 중 Wave T에서 해결된 O-01, O-02, O-03에 이어 남아 있던 3건의 결함을 코드로 닫고 단일 진실 원천(Single Source of Truth)을 확립했습니다: |
| [`task_490d6d4f7d1f.md`](task_490d6d4f7d1f.md) | — | 2026-09-05 | 2026-09-05 세션 및 이전 독립 리뷰(O-05, O-06)에서 드러난 Orca 제어 평면의 세 가지 진실성 결함을 해소하였습니다: |
| [`task_687f4a0d683c.md`](task_687f4a0d683c.md) | — | 2026-09-04 | 공급망 보안 판정 스크립트(scripts/filter_npm_audit.py, scripts/filter_trivy_results.py)가 단순 JSON 구문 유효성만 확인할 뿐 스키마 및 입력 계약을 엄격히 검증하지 못해, 스... |
| [`task_304f542fefbd.md`](task_304f542fefbd.md) | — | 2026-09-04 | CI의 lint-and-validate job을 차단하고 있던 mypy 24건 오류를 # type: ignore 부착이나 pyproject.toml 설정 완화 없이 실제 소스코드 및 타입 좁히기 리팩터링으로 전량(0건) 해소했습니다. |
| [`task_b6a22676a8af.md`](task_b6a22676a8af.md) | — | 2026-09-02 | 본 작업은 2026-09-02 보완점 분석 보고서 4.2 다 항목에 따라, CI의 사각지대를 해소하고 커버리지 게이트를 구축하여 지속적 통합 신뢰도를 강화하는 것을 목적으로 수행되었습니다. |
| [`task_ac156735df14.md`](task_ac156735df14.md) | — | 2026-09-02 | 본 조치는 2026-09-02 보완점 분석 보고서 2.1 항목에 해당하는 대화 상태 관리 모듈의 교차 사용자 접근(IDOR, Insecure Direct Object References) 취약점을 차단하기 위해 수행되었습니다. |
| [`task_5428a2df9fe9.md`](task_5428a2df9fe9.md) | — | 2026-09-02 | 2026-09-02 익명 API 쿼터 변경(커밋 e1d589e)이 src/app/api/v1/chatbot.py의 라인 수를 560줄에서 565줄로 증가시켜 tests/test_chatbot_api_split.py::test_c... |
| [`windows_ci_soft_fail_20260901.md`](windows_ci_soft_fail_20260901.md) | — | 2026-09-01 | pytest 가 2,090 건을 통과한 뒤 KeyboardInterrupt 로 끊깁니다. 특정 테스트의 |
| [`task_v1_windows_subprocess.md`](task_v1_windows_subprocess.md) | — | 2026-09-01 | Windows 환경은 프로세스 생성(fork/spawn) 비용이 Unix 계열보다 현저히 큽니다. 직전 시정(a63c347)으로 폴링 sleep 문제가 닫혔으나, 일부 단위 테스트가 내부 검증을 위해 subprocess.run(... |
| [`task_u1_windows_ci_hang.md`](task_u1_windows_ci_hang.md) | — | 2026-09-01 | GitHub Actions 의 Windows CI 환경(Test windows-latest, py3.11 job)에서 전체 테스트 2,076건 통과 후 scripts/orca_taskctl.py:1464 (time.sleep(m... |
| [`task_k4_supervision_hardening.md`](task_k4_supervision_hardening.md) | — | 2026-09-01 | 2026-09-01 세션에서 코디네이터가 워커 상태를 수동 폴링으로만 확인하여 워커 중단을 뒤늦게 인지하는 문제가 발생하였으며, 유사 사례가 2026-08-26 및 2026-08-31 세션에서도 반복되었습니다. scripts/o... |
| [`task_ad2486bbb6bc.md`](task_ad2486bbb6bc.md) | — | 2026-09-01 | 2026-09-01 세션에서 코디네이터가 워커 상태를 수동 폴링으로만 확인하여 워커 중단을 뒤늦게 인지하는 문제가 발생하였으며, 유사 사례가 2026-08-26 및 2026-08-31 세션에서도 반복되었습니다. scripts/o... |
| [`g3_cutover_verdict_20260901.md`](g3_cutover_verdict_20260901.md) | — | 2026-09-01 | **G3 스택 최적화의 레이턴시 게이트는 전 항목 통과입니다.** 전 동시성에서 **100ms 초과 0건 / 7,200 요청**입니다. |
| [`task_b39d478921fd.md`](task_b39d478921fd.md) | — | 2026-08-31 | Orca 환경에서 CLI 워커(Antigravity, Kimi Code, Qwen Code)를 기동할 때 터미널 생성 후 Preamble 주입 순서 문제를 해결하기 위해 전용 런처 스크립트(orca_agy_launch.py, o... |
| [`task_22541627a79a.md`](task_22541627a79a.md) | — | 2026-08-31 | 본 작업은 Orca 다중 에이전트 오케스트레이션에서 발생할 수 있는 계약 위반(무작업 완료, 범위 초과 커밋, 누락된 사양 복사본 간 drift, report 누락 완료 선언 등)을 사람의 주의에 의존하지 않고 실행 단계에서 기... |
| [`task_aaa3793b55f9.md`](task_aaa3793b55f9.md) | — | 2026-08-30 | 본 작업은 워커 기동 후 준비 절차(메타데이터 기록, 신뢰 확인 대화창 승인, 권한 자동 승인 감시기 부착, 파일 편집 승인 모드 전환)를 런처 경로와 직접 Dispatch 경로가 공통으로 사용하는 단일 상태 기계(prepare... |
| [`task_971c2f56f882.md`](task_971c2f56f882.md) | — | 2026-08-29 | 공고 상세 페이지의 유사 공고 조회(get_announcement_detail)는 대상 공고와 동일한 카테고리(category) 및 발주/수요기관(dminstt_nm)을 갖는 공고 5건을 조회합니다. |
| [`task_dc563d276c5a.md`](task_dc563d276c5a.md) | — | 2026-08-28 | terminal_map() 이 worktreePath 를 키로 단일 항목만 유지해, 같은 워크트리에 워커 터미널과 빈 셸 터미널이 함께 있으면 orca terminal list 순서에 따라 잘못된 터미널이 선택되었다. |
| [`task_95b03278c33b.md`](task_95b03278c33b.md) | — | 2026-08-28 | Antigravity 등 터미널 기반 워커 CLI는 첫 파일 편집 또는 생성 시 확인 대화창(Accept this file edit?, Allow creation of this file?)을 띄워 사용자 입력을 대기합니다. |
| [`task_7bd2943e69b5.md`](task_7bd2943e69b5.md) | — | 2026-08-28 | 2026-08-28 세션에서 워커가 네트워크 오류로 턴이 종료되어 유휴 상태였으나, orca_worker_watch.py는 CLI 설문만 탐지했습니다. 승인 대화창 신호만으로는 키 입력으로 풀리지 않는 실패 정체를 표현할 수 없... |
| [`task_6c4678a375c2.md`](task_6c4678a375c2.md) | — | 2026-08-28 | scripts/orca_kimi_launch.py 가 os.execvpe 로 현재 프로세스를 kimi 에 넘기고, kimi -p 단발 모드가 끝나면 터미널 창까지 함께 닫혔습니다. cursor·Antigravity 워커는 대화형... |
| [`task_49b8bc065322.md`](task_49b8bc065322.md) | — | 2026-08-28 | verify_verification_truth 의 검증 수준을 pass/fail 진위 대조에서 결과 동일성 대조로 승격합니다. |
| [`task_2af7054896d0.md`](task_2af7054896d0.md) | — | 2026-08-28 | 2026-08-28 외부 감사에서 지적된 자동 승인 감시기 관련 두 가지 P1 결함을 해결하였습니다. 1. **감시기 프로세스 누적 및 고아 프로세스 발생**: start_auto_approve()가 터미널에 중복 호출될 때마다... |
| [`task_8a0cca3400f6.md`](task_8a0cca3400f6.md) | — | 2026-08-26 | 소유한 11개 [[tool.mypy.overrides]] 블록(13모듈)을 **전부 제거**했습니다. 국소 타입 보강만으로 uv run mypy src/ scripts/ 가 통과하며, 존치 override 는 0건입니다. |
| [`task_2bfaf7089ba5.md`](task_2bfaf7089ba5.md) | — | 2026-08-26 | - **유일 정본**: .orca/capsules/task_2bfaf7089ba5/capsule.yaml (capsule schema ORCA_TASK_CAPSULE_V2 / v2.1.0). |
| [`task_0ef63b963bf8.md`](task_0ef63b963bf8.md) | — | 2026-08-25 | 독립 감사에서 보고된 docs/README.md 인덱스 누락을 보완해, 다른 정본이 참조하는 문서를 인덱스에서 찾을 수 있게 한다. |
| [`task_8915e5d1e53f.md`](task_8915e5d1e53f.md) | — | 2026-08-24 | GPT 외부 감사가 제기한 13개 지적 항목을 현재 통합 브랜치 코드에서 재검증하여 보고서 작성. |
| [`gpt_audit_reverification_20260824.md`](gpt_audit_reverification_20260824.md) | — | 2026-08-24 | 외부 감사(GPT)가 제기한 13개 지적 항목을 현재 통합 브랜치 코드에서 근거를 찾아 항목별 판정했습니다. **13개 전부 해소**되었으며, 잔여 결함은 없습니다. |
| [`doc_link_validation_20260824.md`](doc_link_validation_20260824.md) | — | 2026-08-24 | docs/context, docs/analysis, docs/handoff, docs/ops는 프로젝트 리팩토링의 의사결정과 성능/품질 감사 근거 체계의 핵심입니다. 문서 간 링크가 깨질 경우 감사 근거의 추적성이 단절되므로, ... |
| [`audit_items_8_9_12_verification_20260824.md`](audit_items_8_9_12_verification_20260824.md) | [`audit_doc_reconcile_20260824.md`](audit_doc_reconcile_20260824.md)<br>[`docs_consistency_audit_20260823.md`](docs_consistency_audit_20260823.md) | 2026-08-24 | 이전 감사 재검증 보고서(gpt_audit_reverification_20260824.md)에서 13개 전부 해소로 판정했으나, 코디네이터가 표본 대조하지 않은 3항목(8, 9, 12번)을 코드로 직접 검증했습니다. **3항목 ... |
| [`task_wt_prepare.md`](task_wt_prepare.md) | — | 2026-08-22 | 2026-08-22 병렬 워커 운용 과정에서 다음과 같은 세 가지 반복 결함이 확인되었습니다. 1. **.env 누락**: .env는 Git 미추적 대상이므로 새 워크트리 생성 시 자동 복사되지 않아 수동 cp가 필요했고, 누락... |
| [`task_s3.md`](task_s3.md) | — | 2026-08-18 | 2026-08-18 외부 지적 사항(중간 상태의 SUCCESS 승격 기전)과 관련하여 scripts/ 디렉터리 내 전체 스크립트(Orca 제어 평면 9종 및 검증/감사 스크립트 83종, 총 92개 파일)를 대상으로 fail-op... |
| [`s2.md`](s2.md) | — | 2026-08-17 | 기존 src/app/services/planner.py(644줄)에서 1단계 질의 해석(interpretation) 책임 묶음을 분리하여 src/app/services/planner_interpreter.py로 이식하였습니다. ... |
| [`task_d535721d10d9.md`](task_d535721d10d9.md) | — | — | 병합 게이트 훅이 설치되지 않은 상태를 로컬 검증에서 즉시 검출 |
| [`task_619c731fee76.md`](task_619c731fee76.md) | — | — | CURRENT_STATE.md를 부팅용 요약과 기계 검증 사실 원장 중심으로 정규화했습니다. 판정에 쓰이는 게이트, CI, 버전, 활성 플래그, 성능 판정, 잔여 위험을 current_state_facts.yaml의 33개 사실... |
| [`task_50768bf0d9de.md`](task_50768bf0d9de.md) | — | — | - 2026-08-31 에 qwen3.7-plus 리뷰어가 JSON 이 아닌 응답을 두 번 연속 돌려주어 실패했다. |
| [`task_36dff76c2464.md`](task_36dff76c2464.md) | — | — | 워커가 .orca/ 같은 gitignore 대상 경로를 git add -f 로 강제 커밋해도 Level 1 게이트가 실패하지 않았습니다. |
| [`task_28394bf3d41f.md`](task_28394bf3d41f.md) | — | — | ORCA_WORKER_DONE_V2 계약이 문서 규칙에 머무는지 실행 게이트인지를 저장소 코드 근거로 판정하는 조사 보고서 작성 |

---
