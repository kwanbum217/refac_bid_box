# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-09-10
> **source_commit**: `bbe9e69`
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

- **kb_index_memory**: KB 색인 메모리 폭주는 Wave AP 전량 병합 후 재측정에서 해소를 확인했고 상한을 520,000 으로 올려 최근 1년 505,271건 전량을 삭제 없이 색인했습니다.

- **compare_stats_latency**: GET /api/v1/bids/stats 웜 레이턴시는 3.34ms(P95 3.80ms)입니다. compare-stats 실측을 완료했고 전환 전 웜 31.97초 대비 정상상태 6.5초로 완화를 통과 기준으로 유지합니다.

### active 사실

- **negotiation_contract_support**: 협상 공고를 NEGOTIATION_CONTRACT 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율과 변종 식별자를 화면에 제공합니다. 가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했습니다.

- **servc_qualification_evaluation**: 일반용역 적격심사 정량평가 기능은 규칙·계산·저장·API·화면 전 계층을 병합했고 기술용역은 공고 하한율 판별까지 넣었으며 화면 배지 문구는 후속으로 추진합니다.

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
- **자동 승인 화이트리스트 (2026-09-10, 확장 완료)**: 워커가 매번 사람 승인을 기다리던 명령을 열었습니다. `git add` 는 **명시 경로만** 허용하고 `-A`, `--all`, `-u`, 점 경로, 인자 없음을 거부합니다. 다른 작업의 미커밋 산출물을 삼키는 것을 막기 위함입니다. `git commit` 은 `-m`, `--message`, `-F`, `--file` 만 허용하고 **`--no-verify` 와 `-n` 을 절대 거부**합니다. 열리면 premerge 전량 테스트 게이트와 커밋 메시지 검증이 통째로 우회되기 때문이며, `--amend`, `--allow-empty`, `--author`, `--date`, `--reset-author` 도 같습니다. `pgrep` 과 임의 명령의 `--help`/`-h`, `orca orchestration send` 를 열었고 `orca` 의 다른 서브커맨드는 여전히 보류입니다. `git reset`, `push`, `checkout`, `restore`, `merge`, `rebase`, `worktree add/remove` 는 그대로 보류입니다.
- **관측성 2단계 Prometheus (2026-09-06, 미착수)**: 1단계 Collector·Tempo·Grafana 배선은 `docker-compose.prod.yml` 에 들어갔고, 2단계는 메트릭 계측이 선행 조건입니다.
- **RAG cold SQL (2026-09-07, 정본 확보·1차 원인 미규명)**: 버퍼풀을 실제로 비운 뒤(121,120 -> 1,192 페이지) 타임아웃 300초로 측정해 96요청 전량 성공으로 canonical 게이트를 통과했습니다(`rag_segments_coldpool_20260907.json`, sql 구간 콜드 P50 11.9ms·max 69.3ms). 콜드 버퍼풀 실행이 가장 빨라 1차의 10만 ms 대 값은 버퍼풀로 설명되지 않으며 원인은 미규명입니다. 재현 가능한 두 조건에서 근거가 없으므로 타임아웃 기본값 120초는 유지합니다.
- **RAG cold SQL 원인 조사 (2026-09-10, 가설 좁힘·미확정)**: 1차의 10만 ms 대 값을 코드 판독으로 조사해 가설 다섯을 순위와 근거로 정리했습니다(`docs/analysis/at2_coldsql_cause_investigation_20260910.md`). **그 값을 쿼리 실행 시간이라 부르면 안 됩니다.** 타이머가 SQL 실행만 감싸는지 캐시 조회와 세션 checkout 과 결과 조립까지 감싸는지 미확정이므로 정형 SQL 구간 계측값이 정확한 표현입니다. 유력 후보는 캐시 miss 시 선행 와일드카드 `LIKE` 와 `GROUP BY` 를 포함한 실시간 집계, 그리고 연결 획득 대기가 `sql_ms` 에 함께 계상되는 계측 범위 둘입니다. warmup 하네스는 직렬 1회 호출이라 직접 원인으로는 약하나 캐시와 연결 상태 교란 후보로 남습니다. 동시 요청 경합 가설은 하네스가 `concurrency=1` 직렬이라 이번 측정의 설명으로는 기각에 가깝습니다. 실행 가능한 다음 실험을 판정 기준과 함께 보고서 6장에 남겼습니다. **같은 날 코드 판독으로 셋을 확정했습니다.** 네 문항의 공통점은 날짜 범위나 카테고리가 아니라 기관명 필터를 가진 개체 지정 낙찰 질의라는 점이며, 기관명 필터가 `_snapshot_scope` 를 `None` 으로 만들어 live 경로를 선택합니다(`src/rag/structured_data.py:191-204`). `sql_ms` 는 `retrieve_structured_data` 호출 직전부터 반환 직후까지를 감싸므로 Redis 캐시 조회, lazy checkout 대기, 다중 SQL, 결과 조립, `corrupted_probe` 가 전부 그 안에 들어갑니다(`src/rag/engine.py:743-747`). 정형 DB 호출은 `asyncio.to_thread` 로 오프로드되므로 이벤트 루프 블로킹 가설은 부정됐고, 스레드풀과 DB 풀 경합은 별도 가설로 남습니다(`src/rag/engine.py:1177-1185`). 남은 것은 개별 SQL 시간 구성비의 후속 계측입니다.
- **lexical 전량 재측정 (2026-09-10, 완료·콜드 SQL 재현)**: 전량 fixture 32문항 repetitions 3 으로 96요청을 측정해 canonical 게이트를 통과했습니다(`data/benchmarks/rag_segments_lexical_full_20260910.json`, trace 96/96 중복 0, `git_sha` `df602cd`). 구간은 `llm_ms` P50 2,529ms, `vector_ms` P50 291ms, `total_ms` P50 3,176ms 입니다. **부수적으로 콜드 SQL 지연을 재현했습니다.** `sql_ms` 는 P50 9.51ms 인데 max 90,415ms 이고, cold 32건에서만 P95 79,632ms 로 폭발합니다. 10초를 넘긴 문항은 **q03, q08, q25, q31 넷뿐**이며 2026-08-30 에 지목된 그 문항과 정확히 같습니다. 각 문항의 warm 회차는 8에서 17ms 로 정상입니다. 이로써 기관명 필터가 `_snapshot_scope` 를 `None` 으로 만들어 live 집계 경로를 타는 것이 원인이라는 판정이 코드 판독과 재현 실험 양쪽에서 뒷받침됐습니다.
- **KB 색인 메모리 폭주 (2026-09-09, 해소)**: Wave AP 다섯 Task 를 병합한 뒤 두 조건에서 실측해 해소를 확인했습니다. 16GiB 조건 피크 4,323MB, 14GiB 원복 조건 피크 1,027MB 이며 컨테이너 소멸이 없었습니다. 이어서 `HEAVY_TASK_NAMES` 에 `run_schedule_catchup_task` 를 추가해 3시간 타임아웃을 적용했고(`nightly_schedule_task` 는 cron 에서 이미 받고 있어 대상 아님), catchup 로그가 안내한 수집 공백은 실재하지 않음을 `--dry-run` 으로 확인했으며, 색인 상한을 500,000 에서 **520,000** 으로 올려 최근 1년 505,271건 전량을 **삭제 0건**으로 색인했습니다(14GiB 조건 피크 4,051.8MB, 243.66초). 상한 정의가 두 모듈에 중복돼 있던 구조도 단일 정의로 통일했습니다.
- **스케줄 따라잡기 (2026-09-08, 해소)**: 이미 지난 매일 02:00 크론 슬롯을 놓쳤으면 기동 시 한 번 보충하도록 판정을 슬롯 기준으로 바꿨습니다(`80d7cb0`). 종전에는 경과 24시간 임계치만 봐서 19시간 경과 시점에 `threshold_not_exceeded` 로 거부했습니다. 쿨다운은 유지하며 재시작 반복 발화를 막습니다. 운영 발화를 실측 확인했습니다(`reason=missed_schedule`, `last_cron_slot=2026-09-08T02:00:00`).
- **적격심사 정량평가 (2026-09-10, 동작)**: 공고 상세 페이지에 공고 기준 분석 카드를 붙였습니다. 일반용역은 별표 14종 하한율을 DB 실측으로 확정했고 `B`·`k`·`T` 는 사용자 입력입니다. 기술용역은 `srvceDivNm=기술용역` 이고 `sucsfbidMthdNm`에 적격심사가 있으면 공고 하한율만 쓰며 44개 문자열을 공통 배점표로 묶지 않습니다. 하한율이 없으면 `TECH_SERVICE_MISSING_LWLT` 로 차단합니다. 실사용 표본은 `docs/analysis/ar2_tech_servc_realuse_announcements_20260910.md` 에 14건입니다. 화면 범위 배지는 응답마다 일반용역·기술용역·협상 셋 중 하나로 다시 설정하며 기술용역일 때 공고 하한율을 쓴다는 사실을 표시합니다. 차단 사유 문구 사전에 `TECH_SERVICE_MISSING_LWLT` 를 넣었고, 서버가 `코드: 메시지` 형태로 보내는 `blocked_reason` 에서 코드 접두를 분리하도록 고쳤습니다. 종전에는 사전 키가 순수 코드라 어떤 코드에도 매칭되지 않아 다섯 항목이 전부 죽어 있었습니다. `BLOCK_CODE` 상수 8종이 모두 접두 분리에 걸리는 것을 확인했습니다.
- **금지 패키지 산출물 게이트 (2026-09-10, 동작)**: 이 저장소는 npm 이 정본이고 pnpm 과 yarn 을 금지하는데 그 금지를 검사하는 장치가 없어 두 번 새어 들어왔습니다. Level 1 게이트에 게이트 9 를 추가해 `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `yarn.lock`, `bun.lockb` 가 작업 트리에 있으면 병합을 차단합니다. 커밋 여부와 무관하게 파일 시스템을 직접 보며, 루트와 `frontend/` 의 `package-lock.json` 은 정본이라 허용하고 `node_modules/` 아래는 검사하지 않습니다. 11GB 주 저장소에서 1.45초입니다. `orca_worker_watch.py` 는 같은 집합을 비차단 경고로 알리되 전체 순회 대신 이미 실행한 `git status` 의 untracked 목록을 재사용하므로 추가 비용이 없습니다. 그 대신 gitignore 대상은 감시기 검출에서 빠지며 병합을 막는 정본 판정은 게이트 9 입니다. 집합 정의는 `scripts/orca_forbidden_artifacts.py` 단일 원천입니다. 감시기는 `git status` 가 `core.quotePath` 로 큰따옴표와 C 스타일 이스케이프를 씌운 비ASCII 경로도 해석하며, 디코딩할 수 없는 줄은 경고 후 건너뛰어 상시 감시가 멈추지 않습니다.
- **워크트리 setup 의 pnpm 오염 (2026-09-10, 원인 확정·절차로 회피)**: 산출물을 만드는 것은 워커가 아니라 Orca 프로젝트 setup 스크립트입니다. `orca project setups` 의 `hookSettings.scripts.setup` 이 `pnpm install` 이라 워크트리를 만들 때마다 실행됩니다. 이 값은 저장소 밖 설정이고 CLI 로 바꿀 수 없습니다(`setup-update` 의 `--setup` 은 대상 id 이며 정책이 아닙니다). `orca worktree create --setup skip` 으로 호출 단위 회피가 가능하며 실측으로 확인했습니다. **워크트리를 만들 때 반드시 `--setup skip` 을 붙이십시오.** 빠뜨리면 게이트 9 가 그 Task 의 Level 1 을 막습니다.
- **compare-stats 병목 규명 (2026-09-10, 실측으로 뒤집힘)**: 선행 조사(`at4`)는 `EXPLAIN` 추정으로 매칭 건수 쿼리를 최우선 병목으로 지목하며 `bid_results` 약 311만 행 전체 스캔(`ALL`)을 근거로 들었습니다. **2026-09-10 실측이 이 전제를 재현하지 못했습니다.** `EXPLAIN ANALYZE` 3회 교차 실행에서 원형 `IN` 은 903/943/896ms, `EXISTS` 는 960/892/854ms 였고 **양쪽 모두 `ix_bid_results_dt_cat` range 스캔**이었습니다. 원형도 `ALL` 이 아니었고, 이 쿼리는 6.5초가 아니라 약 0.9초입니다. 평균 914.0ms 대 902.0ms 로 개선은 확인되지 않았습니다. COUNT 는 양쪽 327,686 으로 동일합니다. `EXISTS` 전환은 의미 보존과 회귀 안전을 근거로 병합했으나 **성능 개선 근거로 인용해서는 안 됩니다.** 추정과 실측이 갈린 원인은 미확정이며 bind 값 차이와 버퍼풀 설명은 리뷰에서 기각됐습니다. 6.5초의 실제 구성은 다시 규명해야 합니다. 근거는 `docs/analysis/au1_compare_stats_exists_verification_20260910.md` 입니다.
- **금액 집계 성능 (2026-09-10, 측정 완료)**: `GET /api/v1/bids/stats` 웜 레이턴시는 3.34ms(P95 3.80ms)입니다. `GET /api/v1/bids/compare-stats` 는 실측했습니다. 콜드(버퍼풀 빈 상태, 캐시 없음) 147.7초, 웜 캐시 미적중 회차별 25.2/11.3/9.8/8.9/9.1/6.3/6.8초로 **정상상태 약 6.5초**, Redis 캐시 적중 0.004~0.06초입니다. 전환 전 웜 31.97초 대비 약 4.9배 개선이며 **해소가 아니라 완화**로 읽어야 합니다. 6.5초는 여전히 느리고 24시간 TTL 캐시가 체감을 덮고 있을 뿐입니다. 측정 조건은 컨테이너 내부 `innodb_buffer_pool_size` 2048MB 이며 콜드 값은 회차 1건이라 게이트로 쓰지 않습니다.
- **협상에의한계약 지원 (2026-09-10, 동작)**: 협상 공고를 `NEGOTIATION_CONTRACT` 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율(`techAbltEvlRt`, `bidPrceEvlRt`)과 변종 식별자를 화면에 제공합니다. 변종은 기본·SW사업·엔지니어링·건설엔지니어링 넷이며 `다수공급자계약-적격성평가 및 가격협상` 은 대상이 아닙니다. **가격점수는 계산하지 않습니다.** 계수 `k` 와 통과점수 `T` 가 공고 데이터에 없고 `sucsfbidMthdAppStd` 가 20,077건 전부 빈 문자열이며, `bid_results` 에 낙찰자 한 명만 있어 경쟁 투찰가 의존 산식은 사후 재현도 불가능하기 때문입니다. 대신 변종별 과거 낙찰률 실측 분포를 참고값으로 제시하며 Redis 24시간 캐시를 거칩니다(콜드 1.6~2.6초, 캐시 0.0003초). 순위와 낙찰 여부는 계산 불가로 명시했습니다.

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
