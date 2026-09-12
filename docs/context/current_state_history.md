# CURRENT_STATE 상세 이력 보존본

> 정규화 전 CURRENT_STATE.md의 전체 본문입니다. 사실·측정 로그·과거 경위를 삭제하지 않고 부팅 요약과 분리해 보존합니다.
> 현재 판정에 사용할 값은 current_state_facts.yaml과 CURRENT_STATE.md를 우선하고, 이 문서는 상세 근거가 필요할 때 조회합니다.

---

## 정규화 전 원본 (2026-09-03)

# 프로젝트 현재 운영 상태 정본 (CURRENT_STATE)

> **updated_at**: 2026-09-03
> **source_commit**: `9a5a76e`
> **version**: 0.1.0 (`pyproject.toml` 이 SSoT)
> 코디네이터가 부트스트랩 시 가장 먼저 읽는 **현재 운영 상태 정본**입니다. 과거 handoff 는 증거이며, 즉시 판단과 정책 결정은 본 문서를 기준으로 합니다.

---

## 1. 3대 목표 게이트 상태 (Gates)

| 게이트 | 목표 정의 | 현재 판정 | 상세 상태 및 조건 |
| --- | --- | :---: | --- |
| **G1** | 데이터 무손실 | **통과 (불변)** | MySQL 8 스키마·행 수 보존, ML 가중치 체크섬 일치, ChromaDB `bidding_kb` 무결성 |
| **G2** | 크로스 플랫폼 | **보류 (Windows 실기 미수행)** | MySQL ngram job 은 **green 복귀**했고 Ubuntu 3종·macOS·Docker·lint 도 green 입니다. Windows job 은 네 층을 닫아 342초를 212.90초로 줄여 green 을 회복했고, 2026-09-02 실측에서는 Windows job 이 **정규 게이트로 통과** 중이며 워크플로에 `continue-on-error` 가 없습니다(과거 게이트 제외 기술은 오기였습니다, [`windows_ci_soft_fail_20260901.md`](../analysis/windows_ci_soft_fail_20260901.md)). **게이트 제외를 통과로 올리지 않습니다.** Windows Docker Desktop 실기 미수행은 여전히 별개 항목입니다 |
| **G3** | 스택 최적화 | **통과** | 2026-09-01 `cee7463` 동결 재측정에서 **레이턴시 게이트 전 항목 통과**입니다([`g3_cutover_verdict_20260901.md`](../analysis/g3_cutover_verdict_20260901.md)). 예측 c1 15.03ms, c2 **19.66ms**, c4 32.77ms, c10 48.14ms, SSE 첫 토큰 2,664.19ms, 전체 3,353.98ms (전부 3회 최악, >100ms 0건/7,200요청). 종전 유일 미달이던 c2 는 **오염된 측정**이었고(당시 호스트 부하 42.45% 로 규약 임계 초과) 규약 안에서 재측정하니 통과했습니다. 콜드 SQL 총량은 관찰 지표로 강등했습니다. **전체 컷오버는 G2 Windows 실기 방침 확정 후 선언합니다** |

> **주의**: G3 는 일괄 통과로 선언하지 않고 항목별 실측 상태로 기록합니다.

> **2026-09-02 정정**: 위 CI RED 기술은 **사실과 달랐습니다.** 실측 확인 결과
> `576cf51`, `578a613`, `b3744b1` 세 커밋의 CI 가 모두 success 이며(HEAD run
> `33524159395`), `.github/workflows/` 전체에 `continue-on-error` 가 **0건**입니다.
> Windows job 은 게이트에서 제외된 상태가 아니라 정규 게이트로 통과 중입니다.
> 본 문서가 반대로 기록하고 있어 코디네이터 판단을 오도했으므로 여기서 바로잡습니다.
> **다만 본 병합 시점(`5d8ad97`)의 CI 는 아직 돌지 않았으므로 green 을 단정하지
> 않습니다.** 푸시 후 결과로 재확인합니다.

> **컷오버 선언 (2026-09-01)**: 위 3대 목표 판정에 따라 **Phase 7 컷오버를 선언**했습니다
> ([`../ops/phase7_cutover_declaration_20260901.md`](../ops/phase7_cutover_declaration_20260901.md)).
> **조건부**이며 Windows Docker Desktop 실기 검증이 후속 과업으로 남습니다. 그 검증이
> 실패하면 G2 를 미통과로 되돌리고 선언을 철회합니다. **컷오버는 최적화의 종료가 아니며
> G3 는 계속 상시 과제입니다.**

---

## 1.5 웨이브별 해소 이력

2026-09-02 까지의 보안 P0, P1 Wave A~C, P2 Wave D, Wave E~G 해소 내역과 각 항목의
병합 커밋은 [`../ops/wave_resolution_history_20260902.md`](../ops/wave_resolution_history_20260902.md)
로 옮겼습니다. 완료된 이력이므로 근거가 필요할 때만 조회하십시오.

현재 열려 있는 잔여 항목은 본 문서 4장과
[`../ops/handoff_20260903_wave_h_close.md`](../ops/handoff_20260903_wave_h_close.md)
4장·5장을 정본으로 씁니다. **다음 착수는 SSR E2E Phase 2 이며 2a(DB 격리)와
2b(시나리오)로 쪼개서 진행합니다.** 2026-09-02 Wave G 인계는
[`../ops/handoff_20260902_wave_g_session_close.md`](../ops/handoff_20260902_wave_g_session_close.md)
이며 4.1·4.2 항목은 Wave H 인계가 갱신했습니다.

2026-09-07 에 6.1 에서 두 항목을 내렸습니다. **KB 정합성 검사 기준**은 검사가 낙찰
기준 집합을 공고 기준 ChromaDB 와 그대로 차집합해 대응 공고가 없는 103건이 구조적으로
실패하던 것이며, R-05 시정(`5d93ec6`)으로 저장 도메인별 모집단을 분리해 닫혔습니다.
**관측성 스택**은 후보 미확정으로 대기하던 것이며, Collector·Tempo·Grafana 확정과
1단계 배선(`d7c468f`)으로 닫히고 2단계 Prometheus 만 6.1 에 남았습니다.

Wave H 는 병합 전 전량 테스트 게이트와 정본 스킬 영수증 게이트를 도입했습니다.
**세션 시작 시 훅 설치와 영수증 발급을 먼저 하십시오.** 절차는 Wave H 인계 1장입니다.

---

**CSRF 는 SSR 폼에만 걸려 있습니다.** JSON API 소비자는 토큰 없이 동작합니다. 그 경로의 보호는 세션 쿠키의 `samesite=lax` 와 인증에 의존합니다.

**MySQL 통합 테스트는 로컬에서 skip 됩니다.** 실제 검증 게이트는 CI 입니다. 로컬에서 확인하려면 CI 와 같은 `mysql:8.0` 컨테이너를 띄우고 `MYSQL_TEST_URL` 을 지정하십시오.

**워커가 쓴 값은 실측으로 확인하십시오.** `9e48194` 에서 MySQL 오류 코드를 추정값 1140 으로 넣어 CI 가 실패했습니다. 실제는 `OperationalError` 1055 이며 코디네이터가 컨테이너를 띄워 확인했습니다. skip 되는 테스트는 값이 틀려도 드러나지 않습니다.

---

**RPO 와 RTO 는 공란이고 정기 백업 스케줄과 restore drill 도 아직 없습니다.** 도구와 절차만 마련된 상태입니다. 근거 없는 값을 넣지 않고 담당자 기입 공란으로 둡니다. 스케줄 주기가 RPO 를 사실상 결정하므로 주기를 정할 때 함께 판단하십시오.

**관측성 스택은 담당자 결정 대기입니다.** 조사 보고서의 권고는 후보이며 확정이 아닙니다.

**GitHub Actions 액션 버전은 실존을 조회해 확인하십시오.** `40e1721` 에서 존재하지 않는 trivy 버전 때문에 공급망 job 이 실패했습니다. actionlint 는 버전 실존을 검사하지 않습니다.

**푸시 전에 `source_commit` 을 갱신하십시오.** `c5c35f3` 에서 이 누락 하나로 CI 의 job 여섯 개가 실패했습니다. 2026-09-02 에도 같은 누락으로 `main` 이 두 번 적색이 됐습니다.

**조율 시작 전 정본 스킬 영수증이 필요합니다.** `scripts/orca_taskctl.py` 의 `create` 와 `dispatch` 는 `.orca/skill_receipt.json` 이 없거나 정본 sha256 또는 Orca appVersion 이 달라지면 종료 코드 4 로 거부합니다. 해소는 `python3 scripts/orca_skill_receipt.py issue` 하나이며, 이 명령은 정본 본문 전체를 표준출력으로 방출한 경우에만 영수증을 씁니다. `--json` 같은 우회로로 주입 없이 영수증만 받을 수 없습니다. 우회는 `--skip-skill-receipt` 하나뿐이고 쓰면 경고가 남습니다. 세션 시작 훅이 같은 명령을 실행해 정본을 문맥에 넣습니다.

**`main` 병합은 전량 테스트 증거를 요구합니다.** 작업 브랜치에서 `python3 scripts/premerge_full_suite_gate.py --record` 로 증거를 남긴 뒤 병합하십시오. 게이트는 `prepare-commit-msg` 단계에서 커밋 소스가 `merge` 일 때만 동작하며, 증거의 커밋이 병합 대상과 다르거나 전량 대상이 아니면 fail-closed 로 거부합니다. `pre-merge-commit` 단계는 그 시점에 `MERGE_HEAD` 가 아직 없어 쓸 수 없습니다. 훅 설치는 주 저장소에서 `uv run pre-commit install --hook-type prepare-commit-msg` 입니다.

**벽시계 단언은 대비를 크게 두십시오.** `7d18005` 에서 readiness 타임아웃 테스트가 0.08초 단언 때문에 CI 러너에서만 실패했습니다. 커버리지 계측이 추가되면서 오버헤드가 커진 것이 계기입니다. 행 시간과 통과 기준의 차이를 20배 이상으로 두었습니다.

---

**문서 버전 표기는 `pyproject.toml` 의 0.1.0 을 따릅니다.** 릴리스 판단은 아직 서지 않은 상태입니다. 상세는 [`../ops/versioning.md`](../ops/versioning.md) 를 보십시오.

**공급망 스캔은 아직 게이트가 아닙니다.** 기존 취약점 규모를 모르는 상태에서 실패로 걸면 CI 가 상시 red 가 되므로 보고 전용으로 두었습니다. 승격 조건을 충족하면 올리십시오.

**병합 전 검증에 `make check-all` 을 포함하십시오.** `1364b46` 에서 mypy 오류가 CI 까지 흘러갔습니다. `typecheck` 와 `lint-workflows` 가 그 타깃에 있는데 pytest 와 규칙 검증만 돌린 것이 원인이었습니다. Wave D 에서는 같은 종류의 오류 4건을 병합 전에 잡았습니다.

---

**드리프트 job 은 꺼져 있습니다.** baseline 이 축적되기 전에 켜면 매일 무의미한 알림이 나갑니다. 최소 한 번의 재학습으로 baseline 이 생긴 뒤 켜십시오.

**`latest_version` 불변식을 명시화했습니다.** baseline 디렉터리가 모델 디렉터리 아래 생기면서 모든 하위 디렉터리를 버전으로 취급하던 코드가 위험해져, `v_` 접두사만 버전으로 보도록 고쳤습니다.

**3.10 의 집단별 드리프트 연계는 남았습니다.** 정책 문서 6절이며 PSI 구현과 같은 파일을 다뤄 이번에 분리했습니다.

---

**행 수 판정은 여전히 하한 검사입니다.** 수집이 계속 돌아 행이 늘기 때문에 의도된 설계이며 정확 일치로 바꾸지 마십시오. 성장 데이터와 이행 원본을 구분하는 reconciliation 은 아직 없습니다.

**검증 절차를 바꿨습니다.** `0295e3e` 푸시에서 CI 의 Test job 5개가 전부 실패했는데, 원인은 readiness 가 warmup 과 LLM 을 보게 되면서 Ollama 없는 CI 에서 `degraded` 가 된 것이었습니다. **로컬에 Ollama 가 떠 있어 코디네이터와 워커의 전량 테스트가 모두 통과했고 Level 1 게이트와 리뷰어도 놓쳤습니다.** 이후 병합 전 검증은 `.env` 를 제거하고 Ollama 와 Redis 를 미가용으로 만든 CI 모사 환경에서 수행합니다.

**리뷰 체크리스트에 이모지 항목을 넣으십시오.** Wave B 에서 문서 이모지 위반 2건이 리뷰어를 통과했고 코디네이터 검토에서 발견됐습니다.

---

**시도 제한의 프록시 전제입니다.** IP 축은 `TRUSTED_PROXY_IPS` 에 등록된 피어에서만 `X-Forwarded-For` 를 해석합니다. **리버스 프록시나 로드밸런서를 앞에 두면서 이 값을 비워 두면 모든 요청이 프록시 IP 하나로 보여 전체 사용자가 잠깁니다.** 3.7 운영 Compose 작업과 반드시 함께 처리하십시오.

**검증 체계의 한계를 기록합니다.** qwen 풀이 2026-09-06 까지 소진되어 Level 2 리뷰어를 빌더와 같은 Gemini 계열로 배정했습니다. 이 웨이브에서 발견된 결함 3건(`_flight_locks` 무한 증가, `os.getenv` 계약 위반, 실패 요약의 서비스 키 노출)은 **모두 리뷰어가 아니라 코디네이터 검토에서 나왔습니다.** 세 번째는 리뷰어가 `service_key_leak` 를 통과 판정한 항목입니다. 동일 계열 리뷰어의 독립성이 실제로 약하다는 실측 근거입니다.

---

**남은 후속 과업입니다.**

- 확인 토큰의 일회성 소비 기록이 프로세스 지역 인메모리 집합입니다. `WEB_CONCURRENCY` 를 올리면 워커마다 별도 집합이라 재사용 여지가 있습니다. 실질 방어선은 `confirm_automation_request` 의 DB 기반 `confirmed_at` 멱등 가드이며, Redis TTL 로 옮기는 것이 정공법입니다.
- 서빙 모델 교체는 실패 잔재가 없지만 rename 2회 사이에 마이크로초 단위 부재 구간이 남습니다. 완전 무중단은 심볼릭 링크 교체가 필요합니다.
- `promote_model.py status` 가 실제 레지스트리에서 기각 버전을 차단하는지는 병합 후 주 저장소에서 확인해야 합니다.

---

## 2. 최신 성능 지표 정본 (Current Metrics)

[`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 규약(표본 수, warmup 제외, 3회 최악값, 주변 부하 기록)에 따른 실측값만 유효합니다.

### 2.1 예측 API 레이턴시 지표

- **동결 HEAD**: `cee7463` (2026-09-01 재측정, `git_dirty=false`)
- **운영 설정**: `PREDICTION_GC_MODE=freeze`, **DB 버퍼풀 2GB**, DB 연속 가동 1,307초
- **부하 조건**: warmup 제외, 회차당 600표본, 3회 반복 중 최악 대표값, 주변 부하 15.4~15.8%

| 동시성 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 100ms 초과 | 회귀 판정선 (P95 +10% 및 쌍대 예산) |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| **c1** | 12.00 | **15.03** | 16.97 | 37.30 | 0건 (1,800회) | **통과**: 17.02ms |
| **c2** | 16.60 | **19.66** | 24.46 | 29.50 | 0건 (1,800회) | **통과**: 21.77ms (종전 22.68ms 미달은 부하 42.45% 오염 측정) |
| **c4** | 27.53 | **32.77** | 37.53 | 45.03 | 0건 (1,800회) | **통과**: 36.81ms |
| **c10** | **38.77** | **48.14** | **52.38** | **55.98** | **0건 (1,800회)** | **통과**: 100ms 이하 |

> **구형 기록 주의**: 루트 `README.md` 에는 해당 수치가 없으며 과거 handoff 및 이력 문서에만 남아 있는 199.18ms 는 구형입니다. c10 정본 기준선은 **56.45ms** (재측정 최악 47.77ms).

### 2.2 하이브리드 RAG SSE 스트리밍 지표

- **부하 조건**: 회차당 60표본, 3회 반복, warmup 제외, 주변 부하 중앙 13.8% / 최대 27.8% (규약 통과)

| 지표 | 정본 대표값 (3회 최악) | 목표 기준 | 판정 | 회귀 판정선 (+10%) |
| --- | ---: | ---: | :---: | ---: |
| 첫 토큰 P95 (c1) | **2664.19ms** | 3,000ms 이하 | **통과** | 2930.61ms |
| 전체 스트리밍 P95 (c1) | **3353.98ms** | 20,000ms 이하 | **통과** | 3689.38ms |
| c4 첫 토큰 P95 | 18086.00ms | 기준 없음 | 판정 불가 | Ollama 직렬화 |

### 2.3 RAG 품질 정본 (2026-08-30)

- **측정 조건**: `blind_fixture_v2` 32문항 x 3회 = 96요청, HEAD `2a1f72c` 동결, `canonical=true`, 요청 실패 0건
- **산출물**: [`blind_fixture_v2_e2b_20260830_v2.json`](../../data/benchmarks/blind_fixture_v2_e2b_20260830_v2.json)

| 지표 | 이전 정본 | **현 정본** | 변화 |
| --- | ---: | ---: | :---: |
| numeric 정답 | 138/144 | **144/144 (100%)** | +6 |
| evidence recall | 0.9583 | **1.0000** | +0.042 |
| citation | 70/72 | **72/72 (100%)** | +2 |
| refusal 정확 | 21/24 | **24/24 (100%)** | +3 |
| 과잉응답 | 3 | **0** | -3 |
| 검색 미스 | q21 | **0건** | 해소 |

q21 재순위 결함이 닫혔습니다. 공통 96건 중 근거 ID 변경은 q21·q08·q02 3문항뿐이며 나머지 21문항은 순서까지 동일해 회귀가 없습니다.

> **주의**: Lexical 채널은 `dataset = "announcement"` 만 조회해 낙찰 결과 필드를 담지 않습니다. 포함 매칭 문서를 벡터 결과 상위로 승격하면 결과 보유 문서가 `top_k` 절단선 밖으로 밀려 낙찰 질의가 답을 잃습니다. 이때 evidence recall 과 citation 은 만점을 유지하므로 **검색 지표만으로는 회귀가 드러나지 않습니다.** 상세는 [`serial_measurement_20260830.md`](../analysis/serial_measurement_20260830.md) 3장.

### 2.4 RAG 구간 레이턴시 정본 (2026-08-30, warm/steady-state 한정)

- **측정 조건**: 동일 fixture 96요청, HEAD `a81f2d5` 동결, `canonical=true`, trace 1:1 상관 검증 통과 (Redis/DB 캐시가 활성화된 warm/steady-state 조건)
- **산출물**: [`rag_segments_canonical_20260830.json`](../../data/benchmarks/rag_segments_canonical_20260830.json)

| 구간 | P50 (ms) | P95 (ms) | 비중 |
| --- | ---: | ---: | ---: |
| **vector** | **1,307.88** | **2,058.22** | **33.0%** |
| **llm** | **2,610.34** | **3,125.34** | **65.8%** |
| sql | 7.39 | 17.61 | 0.19% |
| residual | 27.84 | 59.89 | 0.70% |
| plan / assembly / guard | 0.14 / 0.09 / 0.12 | 0.29 / 0.18 / 0.35 | 합계 0.01% 미만 |
| **total** | **3,969.43** | **6,318.07** | 100% |

**warm/steady-state 조건**에서 지연의 **98.8%가 vector 와 llm** 두 구간에 몰려 있으며, 캐시 적중 상태의 최적화 대상은 이 둘입니다. 단, 본 구간 정본은 직전 측정이 캐시를 데워 놓은 warm 상태에 한정되며, 캐시가 식은 cold 상태에서는 SQL 구간 지연이 최대 97초까지 치솟습니다(상세는 [2.6절](#26-rag-정형-질의-콜드-스타트-결함-2026-08-30-부분-시정재측정-대기) 참조).

> **주의**: 이 산출물의 **P99 와 max 를 게이트 판정선으로 쓰지 마십시오.** `benchmark_rag_segments.py` 에 warmup 단계가 없어 프로세스 재기동 직후 첫 요청 비용이 그대로 실립니다. 두 측정에서 교차 확인했습니다(M2 q01 cold 벡터 26,097ms = 전 구간 max, M1 q01 r1 28,646ms 후 r2 19,620 -> r3 11,746 단조 감소). 구간별 비중은 워밍업과 무관하므로 유효합니다.

### 2.5 Servc Champion OOS 정본 (2026-08-30)

- **측정 조건**: 유효 OOS 3,589건 전량(차이 0, 제외 0), 표본 키 sha256 `e913080c`, Champion `servc_institution_v1` 가중치 sha256 `53630e49`, objective `quantile(0.5)`
- **산출물**: [`servc_oos_champion_20260830.json`](../../data/benchmarks/servc_oos_champion_20260830.json)

| 지표 | 3,589건 OOS | 기존 300건 | 판정 |
| --- | ---: | ---: | :---: |
| MAE | **1.1825** | 1.2686 | 개선 |
| 0.5%p 적중률 | **62.69%** | 63.33% | 동등 |
| 피복률 | **90.25%** | 89.67% | 개선 |
| RMSE / 편향 / 중앙 절대오차 | 2.6290 / -0.0955 / 0.2412 | - | 신규 |

| 집단 | 건수 | MAE | 0.5%p 적중 |
| --- | ---: | ---: | ---: |
| `with_lwlt` | 2,233 (62.2%) | **0.6288** | **79.36%** |
| `missing_lwlt` | 1,356 (37.8%) | **2.0943** | **35.25%** |

**재학습 게이트 3,098건을 491건 초과했으나 성능 저하가 없어 즉시 재학습 근거는 없습니다.**
전체 MAE 는 성질이 다른 두 집단의 평균입니다.

> **2026-09-01 정정**: 종전에 개선 경로를 "낙찰하한율 결측 보전" 으로 적었으나
> **그 경로는 없습니다.** 결측 1,356건은 100% 제도적 개념 부재(수의시담·규격가격동시·
> 협상·최저가)이고 수집 누락은 0건이며, DB 내 대체와 외부 API 보강 모두 0건입니다.
> 추정 대입은 오차가 7~12%p 폭증해 기각됐습니다
> ([`servc_lwlt_missing_20260830.md`](../analysis/servc_lwlt_missing_20260830.md)).
> 두 집단은 실제 낙찰률 분포가 다른 **별도 모집단**입니다(결측 94.95%/SD 5.19,
> 보유 88.67%/SD 2.62). 값을 채워서 될 문제가 아닙니다.
> **계약방식별 분리 모델링도 대안이 아닙니다.** 2026-08-03 실측에서 세 세그먼트
> 전부 분리가 단일보다 나빴고(전체 R2 0.6659 대 0.6683) 2026-08-07 에 재확인됐습니다.
> 유효하게 남은 것은 **결측 집단 전용 예측구간 관리** 하나뿐입니다.

### 2.6 RAG 정형 질의 콜드 스타트 결함 (2026-08-30, 부분 시정·재측정 대기)

**Redis 캐시가 식으면 RAG 정형 질의가 최대 97초 걸립니다.** `AGGREGATE_CACHE_TTL` 은 3,600초이며 만료할 때마다 다음 사용자 한 명이 그 비용을 부담합니다.

| 상태 | sql P50 | sql max |
| --- | ---: | ---: |
| 캐시 적중 (warm) | 7.03ms | 8.88ms |
| 캐시 미스 (cold) | - | **97,087.81ms** |

`GROUP BY bidwinnr_nm` 이 `bid_results`(실제 3,423,008행, EXPLAIN rows 추정 3,267,347행) 인덱스를, `GROUP BY dminstt_nm` 이 `bid_announcements`(실제 5,490,072행, EXPLAIN rows 추정 2,179,319행)를 훑고 `Using temporary; Using filesort` 를 수행합니다. `_snapshot_scope` 가 날짜·기관 필터에서 스냅샷을 포기하므로 `"2026년"` 같은 흔한 표현이 전부 이 경로를 탑니다.

> **측정 함정**: `src/rag/structured_data.py:237` 주석은 이 비용을 "2초" 로 적고 있으며 실측의 **25~48배 과소평가**입니다. 2.4절 구간 정본도 같은 함정으로 sql P50 을 7.39ms 로 기록했습니다(직전 측정이 캐시를 데워 놓았음). **캐시 상태를 명시하지 않은 SQL 레이턴시 수치는 신뢰하지 마십시오.** 상세는 [`rag_structured_sql_coldstart_20260830.md`](../analysis/rag_structured_sql_coldstart_20260830.md).

**부분 시정 완료(`3c27ed3`)**: `bidwinnr_nm` 집계에 날짜 인덱스를 강제해 13,446ms 를 698ms 로 낮췄습니다(19.3배, 반환 15행 동일).

**Wave E1 시정 완료(`a53b01a`)**: `corrupted_probe` 3건의 전체 스캔을 제거하고
스냅샷 손상 마커를 재사용하며, 공고 기관·공고명 집계에 날짜 인덱스 힌트를
적용했습니다. 정형 집계 결과와 안내 문구 의미는 유지했습니다.

**Wave E2 조사 완료(`500e70a`)**: `.contains()` 13건을 전수 조사했습니다. 기관명
검색을 접두 일치로 단순 전환하면 "거제시" 표본의 99.6%가 손실되므로 기각합니다.
G5·G6 자유 검색은 Meilisearch fail-closed 운영 검증 후 위임할 수 있습니다.

**Wave E3 하네스 완료(`7ec1d23`)**: Redis cold·warm과 MySQL `performance_schema`
소비를 같은 표본에서 귀속하는 `scripts/measure_coldsql_attribution.py`를 추가했습니다.
캐시 비움 요청과 실제 성공이 모두 확인되지 않으면 `canonical=false`로 닫힙니다.

**Wave E4 정본 실측 완료(`2ba8f68`, 문서 정정 `683d705`)**: `7dcc771` 동결에서
32문항 x 3회 cold/warm 을 같은 표본으로 측정했습니다. `canonical=true`,
`failed_gates=[]`, 요청 실패 0 입니다([`coldsql_attribution_canonical_20260830.md`](../analysis/coldsql_attribution_canonical_20260830.md)).

| 지표 | 값 |
| --- | ---: |
| cold 총 SQL 소비 | **223.77초** |
| warm 총 SQL 소비 | **0.15초** |
| 최대 단일 쿼리 delta | 29.67초 |
| 상위 10개 누적 비중 | **92.0%** (205.78초) |

상위 10개가 전부 `LIKE concat('%', ?, '%')` 선행 와일드카드입니다. E1 이 겨눈
`bidwinnr_nm` 집계는 7위(18.19초)로 내려갔고, 잔여 지배 SQL 은 **`bid_announcements`
선행 와일드카드 5종**입니다. E2 가 접두 전환을 이미 기각했으므로 다음 후보는
Meilisearch 위임 또는 인덱스·스냅샷 경로 재설계입니다.

**Wave E5 회귀 시정 완료(`33bfdf8`)**: E1 이 실시간 경로 손상 탐침을 스냅샷 마커로
바꾸면서, 스냅샷이 없는 경로에서 제외 안내가 사라졌습니다. E1 을 "안내 문구 의미
유지" 로 적었던 종전 서술은 **사실이 아니었습니다.** 제외 확인을 파이썬 판독 ->
스냅샷 마커 -> `LIMIT 1` 탐침 3단계로 두고 앞 단계에서 끝나면 뒤를 실행하지
않습니다. 운영 환경은 마커에서 끝나 추가 비용이 없고 순위 쿼리는 불변입니다.

> **기각 기록**: SQL `exclude_corrupted()` 를 빼고 오버페치로 거르는 안은 실측
> 기각입니다. `bid_results` 낙찰업체 상위 15건이 **전부 손상값**이라 실시간 순위가
> 빈 목록이 됩니다(정상 5건을 채우려면 81위까지 필요, 오버페치는 15건). 윈도우
> 집계로 한 스캔에 푸는 안은 6,436ms -> 35,934ms 로 5.6배 느려져 기각했습니다.
> **단위 테스트는 이 결함을 못 잡습니다.** fixture 규모에서는 항상 통과합니다.

**Wave F 조사 완료(2026-08-30)**: 콜드 비용 223.77초의 92%는 **사용자 검색의 선행
와일드카드 `LIKE '%키워드%'`** 하나에서 나옵니다. 후보 넷을 닫고 하나를 권고했습니다.
접두 전환(E2), Meilisearch 위임(F2, 편차 최대 +1,267%·집계 불가), 손상 필터 제거
(F1, EXPLAIN 동일하여 무효), 기관 스냅샷 확장(부분 문자열이라 부적용)은 전부 기각입니다.

**당시 권고(2026-08-30)**: ngram FULLTEXT 를 `dminstt_nm`(warm 1,719.6 -> 90.6ms,
19.0배)과 `bidwinnr_nm`(808.7 -> 283.8ms, 2.9배)에만 적용한다.

> **2026-09-01 종결**: 이 권고는 **실행 후 기각**됐습니다. 운영 인덱스를 만들고 같은
> HEAD 에서 플래그만 바꾼 쌍대 측정에서 콜드 총 SQL 이 OFF 333.19초 대 ON 339.57초로
> 개선이 없었습니다. 19.0배는 소규모 probe 의 warm 배율이라 운영 콜드에 이전되지
> 않았습니다. **운영 FULLTEXT 인덱스 3개는 제거했고 잔여 0 입니다.**
> 상세는 [`ngram_prefilter_paired_verdict_20260901.md`](../analysis/ngram_prefilter_paired_verdict_20260901.md).
> 이 절은 이력으로 남기며 **다시 착수 대상이 아닙니다**(기각 목록 참조).

**콜드 SQL 총량은 2026-09-01 결정으로 게이트가 아니라 관찰 지표입니다.** 동일 조건
재측정이 333.19초와 432.99초로 30% 흔들려 재현되지 않습니다
([`coldsql_metric_demotion_20260901.md`](../analysis/coldsql_metric_demotion_20260901.md)).

---

## 3. 기각 및 반복 금지 목록 (Do Not Repeat)

상세 근거는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 7장입니다.

| 금지 항목 | 결론 |
| --- | --- |
| 기각된 성능 실험 재시도 | Uvicorn 증설, `GC_MODE=batch-disable`, `GC_MODE=threshold`는 기각 |
| README 성능 수치 기록 | 1·2장이 정본이며 README에는 기록하지 않음 |
| `--inject`·요약만으로 완료 판단 | `terminal read`, diff, 검증 결과를 직접 대조 |
| Capsule·보고 경로 공유 또는 완료 Task 재사용 | Task·Dispatch마다 독립 경로와 새 Task/ready 복귀 사용 |
| 파이프라인 종료 코드·비표준 계약 필드 신뢰 | 게이트 도구와 계약 필드만 사용 |

---

## 4. 현재 진행 과업 및 우선순위 (Active Priorities)

1-0. **RAG 콜드 SQL 잔여 시정 (ngram 경로 기각, 2026-09-01)**: 운영 FULLTEXT 인덱스를
생성하고 경계값 7 클래스를 실측한 뒤 같은 HEAD `d3cad6c` 에서 플래그만 바꾼 쌍대 측정을
했습니다. **콜드 총 SQL 이 OFF 333.19초 대 ON 339.57초로 개선이 없어 선행필터를
기각합니다**([`ngram_prefilter_paired_verdict_20260901.md`](../analysis/ngram_prefilter_paired_verdict_20260901.md)).
MATCH 포함 쿼리 delta 합만 112.29초이며, `GROUP BY` 의 `Using temporary; Using filesort` 가
남고 콜드에서 1.4GB ngram 인덱스 적재 비용이 스캔 절감분을 상쇄합니다. Wave F3 의 19.0배는
소규모 probe 의 warm 배율이라 운영 콜드에 이전되지 않았습니다. 경계값 7 클래스는
**실측 완료**이며 `edge_07`·`edge_11` 이 조용한 누락을 일으켜 fail-closed 가 필수입니다
([`ngram_edge_classes_measurement_20260901.md`](../analysis/ngram_edge_classes_measurement_20260901.md)).
운영 FULLTEXT 인덱스 3개는 2026-09-01 에 **제거 완료**이며 (제거는 5초 이내, 재구축 없음)
행 수 5,490,072 / 3,423,008 로 G1 무손실을 확인했습니다.
**콜드 SQL 총량은 2026-09-01 결정으로 게이트에서 제외하고 관찰 지표로 강등했습니다**
([`coldsql_metric_demotion_20260901.md`](../analysis/coldsql_metric_demotion_20260901.md)).
동일 조건 재측정이 333.19초와 432.99초로 **99.8초(30%) 흔들려 재현되지 않습니다.**
코드 기여는 0 이며(digest 38개 동일, 신규 0건) 원인은 `innodb_buffer_pool_size` 가
기본값 128MB 인 채로 데이터가 27GB 였다는 것입니다. 버퍼풀을 2GB 로 배선했고
측정 규약 5.4 절에 DB 상태 기록을 필수로 넣었습니다. **G3 컷오버는 재현되는
지표로 판정합니다.**

1-0-a. **(종결) 이전 계획**: Wave F의 ngram FULLTEXT 선행필터 권고는 운영 쌍대
측정에서 개선이 없어 **기각**됐습니다. 경계값 7 클래스 실측도 완료했으며,
운영 FULLTEXT 인덱스는 제거됐고 플래그는 계속 OFF입니다. 구현·운영 인덱스 생성·
재측정은 추가 착수 대상이 아니며, 근거와 상태는
[`current_state_facts.yaml`](current_state_facts.yaml) 원장에서 관리합니다.
1. **운영 검증**: 2026-08-26 CI run `32930156938`(`5f8174a`) **3플랫폼 green**. Windows Docker Desktop 실기는 장비 확보 후 수행하는 **후속 과업**입니다.
1-4. **Vector fail-closed·정확 제목**: 근거 적중 **16/16**, 기간·기관 post-filter를 유지합니다. 2026-08-27 후보 30건과 공고명 정규화 정확 일치 재순위로 q21 정답을 top-5에 포함했습니다([`task_9fe129597faf.md`](../analysis/task_9fe129597faf.md)).
1-2. **LLM 경로 최적화**: 2026-08-26 v4(`b4913fd`, 각 72회차)에서 **`gemma4:e2b` 승격** ([`llm_quality_v4_e4b_e2b_20260826.md`](../analysis/llm_quality_v4_e4b_e2b_20260826.md)). 2026-08-27 blind fixture v2(32문항) 측정에서 **e2b 승격 유지** 확정(동결 `13f947a`). numeric 양쪽 **87.5% 동률**이며 e2b 가 과잉응답 0 대 1, refusal 8/8 대 7/8, P50 3,990 대 6,459ms 로 앞섭니다. 과잉거절 12.5% 와 P50 은 두 모델 모두 미달이며 원인은 검색 미스 3문항입니다. 1차 측정은 백필 후 KB 미색인으로 **무효**([`llm_generalization_judgment_20260827.md`](../analysis/llm_generalization_judgment_20260827.md)).
1-1. **Arq 정식 기준선**: 2026-08-24 경로별 10회 캘리브레이션 확정. In-Process 1,195.59 jps / 480.42ms, Container 1,756.94 jps / 327.06ms (CV 1.7% 이하). 잠정값 900/600 제거, 기준선은 캘리브레이션 호스트에 결박([`arq_baseline_calibration_20260824.md`](../analysis/arq_baseline_calibration_20260824.md)).
1-3. **감사 후속 P1**: 2026-08-25 에 RAG 라우팅 오분류, 복합 numeric·refusal 미채점, 모델 라벨·Arq 호스트 미결박을 닫았습니다.
1-5. **Servc 운영 경로**: 2025년 300/300건 평가에서 MAE 1.2686, 0.5%p 적중 63.33%, 피복률 89.67%입니다([`servc_api_path_remeasurement_20260826.md`](../analysis/servc_api_path_remeasurement_20260826.md)). 2026-08-27 유효 OOS는 3,589건으로 3,098건 게이트를 충족했습니다.
2. **프론트엔드**: HTMX 를 2026-08-25 기각하고 ADR 을 SSR + Jinja2 + jQuery 로 개정했습니다. `base.html` CDN 7곳에 이어 Chart.js·marked 도 로컬 벤더로 옮겨 **템플릿 외부 참조 0건**이며, Tailwind 는 빌드타임 CSS(44KB)로 전환했습니다.
3. **G3 컷오버 판정**: 2026-09-01 에 **레이턴시 게이트 전 항목 통과**로 판정했습니다([`g3_cutover_verdict_20260901.md`](../analysis/g3_cutover_verdict_20260901.md)). 남은 차단 항목은 **G2 의 Windows Docker Desktop 실기 검증 하나**이며 장비 부재 사유입니다. 전체 컷오버 선언은 그 방침이 정해진 뒤에 합니다. 개별 게이트 PASS 를 컷오버 PASS 로 승격하지 않습니다.

### 4.1 종결 계열 요약

상세 기전·반복 금지는 [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 참조.

- **안전·품질 게이트**: fail-open 제거, 상태 전파 경계, frontend·Docker·CI 검증 능력과 `source_commit` 신선도 게이트를 갖췄습니다.
- **구조·데이터**: 9개 모듈을 AST 동일성으로 분할했고 ORM 13모델·137컬럼을 `Mapped[]`로 전환했습니다. DDL 지문은 불변입니다.
- **실측·계측**: 예측 웜 P95 c1 15.39ms·c4 34.32ms·c10 47.77ms, SSE c1 첫 토큰 1297.73ms·전체 6716.22ms. 블로킹 I/O·Arq 계측 배선 완료, 최적화 판정 미확정. CPU utilization 은 대기를 포함한 `cpu_utilization_probe_ms` 와 대기를 제외한 `cpu_utilization_observation_ms` 를 분리해 기록합니다.
- **조율 인프라**: 워커 준비 안전성(Git common directory 검증), ModelRegistry single-flight(로드 1회), finalize/Level 1 PASS 없는 병합 차단을 닫았습니다. 워커 감시는 정체를 승인 대기(prompt)와 실패 정체(failure)로 분류하고 실패 정체를 우선합니다. Dispatch 는 파일 편집 자동 승인 모드 전환을 함께 보내되, `shift+tab` 의미가 CLI 마다 다르므로 Antigravity 계열로 판정될 때만 전송하고 그 밖에는 fail-closed 입니다. 감시는 한 워크트리에 터미널이 여럿일 때 워커 터미널을 고르며, 제목이 없거나 셸 기본 제목인 터미널은 후보에서 제외합니다. 기동 실패 시 표시하는 명령은 손조립이 아니라 실제 실행한 명령에서 만듭니다. 워커 런처는 Antigravity(`orca_agy_launch.py`)와 Kimi(`orca_kimi_launch.py`) 둘 다 있으며, Kimi 는 단발 실행 후에도 셸로 이어받아 창과 출력을 남깁니다. 벤치마크 provenance 는 `base_url`↔컨테이너 결박·시작/종료 교체 무효화·런타임 revision·dirty 거부로 결박했습니다. Arq 하네스 2종 헬퍼는 단일화하고 Redis 는 fail-closed 결박입니다.
- **신뢰 설정 잠금**: PID stale 회수 제거, POSIX `fcntl.flock`·Windows `msvcrt.locking` advisory lock으로 교체. 미지원 플랫폼은 fail-closed 중단. 회귀 테스트 완료, 원격 Windows CI 확인은 별도입니다.
- **운영 준비**: 워커 기동 자동화, mypy·bandit·CI 게이트, 프론트엔드 lockfile·`npm ci`를 반영했습니다.

---

## 5. 핵심 불변 원칙 (Critical Invariants)

- **데이터 무손실 (G1)**: 기존 DB 테이블명·컬럼명·타입 변경 절대 금지.
- **Train/Serve 단일화**: 특징 생성은 [`src/ml/features.py`](../../src/ml/features.py) 단일 함수만 사용.
- **게이트 규약 준수**: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md) 미준수 수치는 양방향 무효.
- **1인 작업 Git**: PR 없음. 작업 브랜치 검증 통과 후 `main` 에 `git merge --no-ff`.
- **이모지 절대 금지**: 주석, 커밋 메시지, 문서 등 모든 산출물.

---

## 6. 미해결 사항 및 갱신 규약 (Unknowns & Protocol)

### 6.1 알려진 미해결 사항 (Unknowns)

- **Wave H 조율 평면 강화 (2026-08-31, 병합 완료)**: 문서 배정표가 `TIER_POLICY` 와 어긋나면 CI 가 실패합니다(검사 12개 -> 15개). ngram 선행필터는 기본값 OFF 플래그 뒤에 있고 기관명·업체명 집계 두 경로에만 붙습니다. 런처 승인 준비는 세 런처 공통 모듈로 통합했고 성공 판정을 `file_edit_auto_approve.ok` 로 합니다. 잔여는 [`handoff_20260831_wave_gh.md`](../ops/handoff_20260831_wave_gh.md) 3 장입니다.
- **ngram 경계값 7 클래스 (2026-09-01, 실측 완료·종결)**: 격리 MySQL 8 스키마에서 실측했습니다. `edge_07`(K-water2026)과 `edge_11`(공사's)이 MATCH 로 LIKE 결과를 **조용히 누락**해 fail-closed 가 필수이며, 나머지 5 건은 표본 환경에서 동등했으나 운영 데이터에 표본이 없어 보수적으로 `false` 를 유지합니다([`ngram_edge_classes_measurement_20260901.md`](../analysis/ngram_edge_classes_measurement_20260901.md)). **운영 스키마에서 7 건 전부 PASS 로 보였던 것은 표본 0 건의 공집합 비교였습니다.** ngram 선행필터 자체가 기각되고 인덱스도 제거돼 이 항목은 종결입니다.
- **Wave G 조율 평면 정합성 (2026-08-31, 병합 완료)**: 외부 감사 두 건을 HEAD `d0cb3d7` 에서 교차 검증해 실제 잔여만 닫았습니다. 한쪽 보고서는 `4aa444f`(838 커밋 뒤처짐) 기준이라 10건 중 8건이 이미 수정 완료였습니다. **감사 보고서는 기준 커밋을 확인한 뒤 수용하십시오.** 닫은 것은 모델 정책 3중 분기, 리뷰어 provider 독립성 fail-closed, `commit_count` 타입 우회, `CURRENT_STATE` q21 모순, 2.4 절 warm 범위, EXPLAIN 추정치 표기, ngram 회귀 하네스입니다.
- **리뷰어 실행 경로 (2026-08-31, 해소)**: `orca_run_reviewer.py` 가 모델 provider 로 CLI 를 정합니다. gemini·claude·cerebras 는 `agy`, qwen 계열은 `qwen -m <id> -p` 이며 미지원·판정불가는 `ReviewerToolError` 로 막습니다. `qwen3.7-plus` 로 실제 리뷰를 완주해 확인했습니다. **provider 와 CLI 는 1:1 이 아닙니다** (Antigravity 가 Gemini·Claude·GPT-OSS 를 함께 서빙).
- **리뷰어 diff 상한 (2026-08-31, 해소)**: I-A에서 리뷰어 diff 기본 상한을 실제 Wave G 규모보다 크게 올리고 절단 fail-closed 회귀 검증을 추가했습니다. Qwen 빌더 결과를 Gemini 계열 독립 리뷰어로 재검증해 통과한 뒤 병합했습니다.
- **분석 문서 수치 정합성 (2026-08-31, 병합 완료)**: I-B에서 원시 JSON 기반 Markdown 표 생성기와 `verify` 명령을 추가하고, `METRICS` 마커가 있는 `docs/analysis/` 문서를 agent-rule 검사에 연결했습니다. 전체 테스트 2회 `2917 passed`, 규칙 검사 `16/16`, 독립 리뷰를 통과했습니다.
- **Antigravity 편집 권한 선점 (2026-08-31, 해소)**: I-D에서 `agy` 시작 명령에 `--mode accept-edits`를 넣어 첫 편집 전 모드 전환 경쟁 조건을 제거했습니다. `--dangerously-skip-permissions`는 사용하지 않으며 셸 승인 감시기는 유지합니다. 전체 테스트 2,924건, 규칙 16/16, 독립 리뷰를 통과해 병합했습니다.
- **ngram MySQL 8 격리 CI (2026-08-31, 병합 완료)**: 운영 DB와 분리된 MySQL 8 서비스에 최소 스키마와 ngram FULLTEXT 인덱스를 만들고 전용 통합 검증을 실행하는 CI job을 추가했습니다. 운영 FULLTEXT 인덱스 생성과 기능 플래그 활성화는 사용자 승인 전까지 보류합니다.
- **Wave I 미병합 현황 (2026-09-01 기준)**: I-A/I-B/I-D/I-G 는 `main` 에 병합 완료입니다.
  I-C 는 `citations_wrong` 으로 반려됐습니다(브랜치 `kwanbum217/orca-i-c`, 커밋 `9210641` 보존).
  I-F 조율 계약 강제(scope guard, worker_done guard)는 `8b9e5e9` 로 `main` 에 병합됐습니다.
  MATCH AGAINST 구현이 아닙니다.
  I-H 경계값 7 클래스 픽스처는 2026-09-01 Wave K1 으로 `main` 에 병합됐습니다(`a0ec7e3`).
  J3 독립 리뷰 문서 2 건도 Wave K2 로 이식했고(`32b2426`), 그 과정에서 원 리뷰의
  "CI `mysql-ngram-integration` 잡 삭제" 관찰이 브랜치 base 뒤처짐에 의한 착시였음을
  확인해 정정했습니다.
  **운영 FULLTEXT 인덱스 생성과 `NGRAM_PREFILTER_ENABLED=true` 는 사용자 승인 전 보류입니다.**
  실행 절차는 [`../ops/ngram_fulltext_cutover_runbook.md`](../ops/ngram_fulltext_cutover_runbook.md) 를 따릅니다.
  ngram 컷오버 순서는 [`../ops/handoff_20260901_cutover.md`](../ops/handoff_20260901_cutover.md) 4장입니다.
  잔여(Windows 실기, 관측성 스택, RPO/RTO, SSR E2E Phase 2~4, ngram 컷오버)는
  [`../ops/handoff_20260903_wave_h_close.md`](../ops/handoff_20260903_wave_h_close.md) 4장·5장입니다.
  **CURRENT_STATE 정규화는 부분 해소입니다.** 웨이브별 해소 이력을
  [`../ops/wave_resolution_history_20260902.md`](../ops/wave_resolution_history_20260902.md) 로 분리해
  57,381바이트를 48,039바이트로 줄였습니다. 자체 권장 예산 8,000자에는 여전히 미달이며,
  남은 분량은 2장 지표 정본과 6.1 미해결 사항입니다. 둘 다 이 문서가 존재하는 이유에 해당해
  기계적 축소 대상이 아니고, 항목이 실제로 닫힐 때 함께 줄어듭니다.
  **SSR E2E 는 범위 조사가 끝났습니다.** 권장안은 `pytest-playwright` 4단계 분할이며
  [`../analysis/ssr_e2e_scope_survey_20260902.md`](../analysis/ssr_e2e_scope_survey_20260902.md) 입니다. 착수는 사용자 합의 대기입니다.
- **RAG llm 구간 판정과 기동 예열 (2026-09-01)**: llm 후보 넷을 실측으로 닫았습니다.
  `SYSTEM_PROMPT` 는 Ollama 가 접두사를 캐시해 46% 를 줄여도 prefill 이 9% 만 줄고,
  컨텍스트는 이미 상위 3건 250자로 절제돼 있으며(평균 846자), 응답도 평균 248자로
  짧습니다. 남는 것은 `gemma4:e2b` 의 **99 tok/s** decode 속도이며 손댈 수 없습니다.
  **실질 문제는 콜드 비용**이었고 기동 예열로 첫 질의 중앙 31,398ms 를 18,784ms 로
  낮췄습니다(콜드 초과분의 약 70% 제거, 결과 불변).
  아울러 컨테이너 루트 로거 때문에 종전 예열 로그가 한 줄도 남지 않던 결함을 고쳤습니다.
  상세는 [`rag_llm_segment_and_warmup_20260901.md`](../analysis/rag_llm_segment_and_warmup_20260901.md).
  **RAG 최적화는 여기서 닫습니다.** 남은 지렛대는 모델·하드웨어 교체입니다.
- **RAG vector 구간 최적화 판정 (2026-09-01)**: 종전 분석이 지목한 임베딩은 병목이
  아닙니다. 실측에서 Ollama 임베딩 45ms, ChromaDB HNSW 3.4ms 이며 **병목은 메타데이터
  `where` 절**입니다(`category` 하나로 3.4ms -> 1,170ms, 344배).
  넓게 받아 파이썬에서 거르는 안은 fixture 96건 중 **6건이 결과 불일치**해
  **기각**했습니다(HNSW 근사 특성상 `n_results` 가 다르면 결과가 달라져 완전 동등성
  달성 불가). 결과 불변인 임베딩 클라이언트 재사용만 병합했습니다(`7832292`).
  상세는 [`vector_metadata_prefilter_verdict_20260901.md`](../analysis/vector_metadata_prefilter_verdict_20260901.md).
  **남은 여지는 vector 가 아니라 llm 구간(warm P50 2,244ms, 62.5%)입니다.**
- **Wave K 조율 평면 (2026-09-01, 병합 완료)**: I-H 경계값 픽스처(`a0ec7e3`)와 J3 리뷰 문서(`32b2426`)를
  병합했고, `main` 에 남아 있던 테스트 실패 27건을 닫았습니다(`7dac20f`). 원인은 `b889ee6` 의 완료 세션
  잔류 검사가 테스트 안에서 실제 Orca 런타임을 호출해 fail-closed 로 거부한 것이며, 검사를 주입 가능한
  함수로 분리하고 운영 fail-closed 는 회귀 테스트로 고정했습니다. **직전 인수인계의 "테스트 2,928건 통과"
  는 사실이 아니었습니다.** 아울러 Dispatch 가 권한 자동 승인 감시기 부착 실패 시 기본값에서 거부하고
  워커 기동 성공 경로에서 상시 감시기를 단일 인스턴스로 자동 기동하도록 바꿨습니다(`1cdcb51`).
- **Windows Docker Desktop 실기 미검증 (후속 과업)**: 2026-09-01 컷오버 선언에서 차단 사유에서 제외했습니다. 장비 확보 시 `docker compose up` 전 서비스 healthy, 예측 API 응답, 마이그레이션을 검증하며, 실패 시 컷오버를 철회합니다.
- **LLM 품질 정본은 2026-08-28 현 HEAD 재측정**(동결 `d9a0536`, `gemma4:e2b` 32문항 x 3회)입니다. numeric 95.7%(67/70), evidence recall 0.957, citation 100%, refusal 24/24, 과잉응답 0 으로 2026-08-27 측정 대비 전 지표가 개선입니다. 다만 요청 2/96 이 타임아웃(q03)했고 긴 정확 공고명 질의가 58~180초를 소모하여 **레이턴시 꼬리는 회귀**입니다 ([`blind_fixture_remeasure_20260828.md`](../analysis/blind_fixture_remeasure_20260828.md)). e4b 동일 조건 재측정은 미실시입니다. 지연 정본 판정은 `benchmark_rag_segments.py` 가 담당합니다.
- **정확 제목 lexical 채널 효과 실측**: 느린 4문항(q03·q08·q25·q31) x 3회에서 요청 실패 2/12 -> **0/12**, 대표값 58,352ms -> **5,941ms**, 최대 180,045ms -> 41,874ms 로 꼬리 지연이 제거됐습니다. 정확도 손실은 없습니다([`lexical_channel_latency_effect_20260828.md`](../analysis/lexical_channel_latency_effect_20260828.md)). 같은 부분집합 e4b 대조는 품질 동률에 P50 6,245ms·최대 81,234ms 로 e2b 가 앞서 **e2b 승격 유지 근거가 보강**됐습니다. 부분집합 12회 표본이므로 전량 재측정으로 정본을 갱신해야 합니다.
- Ollama `gemma4:e4b` Predict c4·SSE c1·Query c1 2026-08-24 규약 준수 3회 측정, 게이트 전 항목 통과.
- Arq container synthetic raw 보존(1,681~1,764 jps, P95 325~342ms). **business-task E2E 2026-08-26 실측**: 격리 큐 실제 task 2종 30/30 완주, P50 5.5ms·P95 1,174.9ms, DB 11행 불변·운영 큐 무영향([`arq_business_e2e_20260826.json`](../../data/benchmarks/arq_business_e2e_20260826.json)).
- **공고 상세 페이지 쿼리 실측 완료 (2026-08-30)**: `similar_announcement_latest_filter` 로 전환해
  후보를 기관·카테고리로 먼저 좁힌 뒤 동일 그룹 최신 차수 여부를 `NOT EXISTS` 로 판정합니다.
  전체 테이블 `row_number()` 랭킹을 제거했고 window 의 결과 의미는 동치 테스트로 고정했습니다.
  **EXPLAIN ANALYZE 전후 비교와 상세 API 레이턴시 실측 완료.**
  신 구현 5.09ms, `GET /api/v1/bids/{pk}` P95 47.98ms, 추가 인덱스 불필요
  (커밋 `49bb224`, [`detail_query_explain_20260830.md`](../analysis/detail_query_explain_20260830.md)).
- **RAG 정본 갱신 및 T7 판정 종료 (2026-08-30)**: HEAD `6210ee1` 에서 v2 32문항 x 3회를 측정해 `canonical=true`, 요청 실패 0/96 으로 정본을 갱신했습니다([`blind_fixture_v2_canonical_20260830.md`](../analysis/blind_fixture_v2_canonical_20260830.md)). numeric 95.8%(138/144), evidence recall 0.958, refusal 24/24, 금지 표현 위반 0, P50 3,147ms, P95 19,897ms 입니다. **T7 conditional vector bypass 는 품질 회귀가 없습니다.** 근거는 지표가 아니라 검색 동일성입니다. 두 측정에서 성공한 공통 94개 요청의 `retrieved_evidence_ids` 가 순서까지 한 건도 다르지 않습니다. T7 판정을 종료합니다.
- **채점 규약 결함 해소 (2026-08-30)**: fixture 의 `context_sufficient` 는 검색 성공을 전제하므로, 검색이 기대 문서를 못 가져온 상태의 정직한 거부가 과잉응답으로, 거부 답변의 인용 부재가 citation 누락으로 집계됐습니다. 하네스가 이제 `retrieval_miss` 를 판정해 citation 과 과잉응답 집계에서 분리하고, 제외 전 원시값과 제외된 문항 ID 를 `summary` 블록에 함께 남깁니다. numeric 과 evidence recall 은 검색 성능을 그대로 드러내야 하므로 제외하지 않습니다. **보정 후 2026-08-30 정본은 citation 69/69(100%), 과잉응답 0 으로 T7 이전 기준선과 일치**합니다.
- **워커 모델 배정 자동화 (2026-08-30)**: `orca_taskctl` Dispatch 가 `orca_model_router` 배정표를 실제로 사용합니다. role x risk 로 모델이 정해지고 배정 근거가 출력과 `--json` 에 남으며, dry-run 과 실제 Dispatch 가 같은 경로를 씁니다. `--model` 명시 지정은 계속 우선하되 배정표를 벗어나면 경고가 남습니다. 2026-08-29 에 medium 위험도 Task 두 건에 flash-high 가 배정된 사고가 이 결선으로 막힙니다. 아울러 Antigravity 모드 판정에 `unknown` 을 도입해, 생성 중 화면이 스피너만 남아 상태줄을 못 읽는 경우 키를 보내지 않고 건너뜁니다(기존에는 normal 로 오판해 accept-edits 워커를 plan 으로 밀어냈습니다). 반려 후 재작업 Task 를 발급하는 명령도 추가됐습니다.
- **정본 판정 게이트 결박 (2026-08-30)**: `measure_llm_quality.py` 의 `canonical` 판정이 provenance·모델·포트만 보던 결함을 닫았습니다. fixture sha256 이 정본 레지스트리(v2 32문항)에 있고, `--limit` 0, 전량 측정, 3회 이상 반복, 요청 실패 0 을 모두 만족해야 `canonical=true` 입니다. `--fixture` 는 필수 인자이며 실패 게이트는 `canonical_failed_gates` 에 남습니다. 이 결함으로 `canonical=true` 로 잘못 저장됐던 v1 24문항 측정은 `data/benchmarks/noncanonical/blind_fixture_v1_20260828_reference.json` 로 격리했습니다(측정값 불변). v1 로 측정된 과거 파일 4건은 당시 기록으로 보존하며 현재 정본과 직접 비교하지 않습니다([`data/benchmarks/README.md`](../../data/benchmarks/README.md)).
- **조율 도구 결함 3건 정리 (2026-08-30 Wave A)**: 기동 준비를 런처·직접 Dispatch 공통 상태 기계로 통합하고 CLI 판정을 기동 시 기록한 메타데이터 우선으로 바꿨습니다. 모드 판정은 상태줄로 한정해 대화 본문 오염을 막고, accept-edits 는 현재 모드 확인 후 상한 안에서만 전환합니다. `orca_worker_watch.py` 에 `--watch`·`--min-commits`·`--stall-threshold` 를 넣어 자작 감시 루프를 없앴고(정체 후보와 차단은 구분, 정체만으로는 종료 코드 1 아님), `orca_auto_approve.py` 가 CLI 설문 같은 비명령 프롬프트를 화이트리스트로 해제합니다(되돌리기 어려운 확인은 제외).
- **Antigravity `dispatch --inject` 는 동작하지 않습니다 (2026-08-29 실증)**: 터미널 2대, 시도 3회에서 전부 `agent_prompt_blocked` 로 실패했습니다. 신뢰 대화창이 없는 준비 완료 프롬프트에서도 실패하므로 대화창 탓이 아닙니다. `--return-preamble` 로 지시문을 받아 `terminal send` 로 전달하는 경로를 쓰십시오.
- 벤치마크 provenance 는 시작·종료를 결박해 대상 교체 시 strict 에서 fail-closed 됩니다([`prov_start_end_invalidation_20260823.md`](../analysis/prov_start_end_invalidation_20260823.md)). `--allow-unknown-provenance` 는 정본이 아닙니다.

### 6.2 정본 갱신 규약 (Update Protocol)

- **동기 갱신**: 운영 지표, 게이트 판정, 불변 사실이 바뀌면 그 커밋에 본 문서 갱신을 포함합니다.
- **과업 상태 원장**: 과업 상태는 [`current_state_facts.yaml`](current_state_facts.yaml)의 `status`와
  문서 앵커를 같은 커밋에서 갱신합니다. CI가 앵커 주변의 상태 표지와 금지 상태를 대조합니다.
- **간결성 유지**: 실험 로그나 분석 과정을 적지 않고 결론과 수치만 요약합니다 (8,000자 이내).
- **진실 우선순위**: `실제 코드 / 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff`

---

## 7. 증거 경로 참조 (Evidence Pointers)

- v2 설계: [`docs/ops/orca_coordinator_token_optimization_v2.md`](../ops/orca_coordinator_token_optimization_v2.md), 제어 평면: [`orca_control_plane_tools.md`](../ops/orca_control_plane_tools.md)
- 지표 원장: [`orca_v2_metrics_ledger.md`](../ops/orca_v2_metrics_ledger.md)
- 레이턴시 게이트 규약: [`latency_gate_protocol.md`](../ops/latency_gate_protocol.md)
- 예측 재측정(2026-08-22): [`predict_remeasurement_20260822.md`](../ops/predict_remeasurement_20260822.md)
- 예측 통제 A/B(2026-08-22): [`predict_ab_20260822.md`](../ops/predict_ab_20260822.md)
- 블로킹 I/O 계측: `docs/analysis/` 의 `predict_coldstart_instrumentation.md`, `query_rag_latency_instrumentation.md`, `arq_throughput_harness.md`, `arq_throughput_20260823.md`, `arq_throughput_gate_20260823.md`
- 워커 기동: [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
- 용역 모델: [`servc_model_status.md`](../servc_model_status.md)
- 용역 운영 API 경로 재측정: [`servc_api_path_remeasurement_20260826.md`](../analysis/servc_api_path_remeasurement_20260826.md)
- 미병합 브랜치 판정: `docs/ops/` 의 `*_verdict_*.md`. 2026-08-26 arq-cutover 와 베이크오프 9건 판정으로 전량 완결이며 회수 후보는 2건뿐

---

## 2026-09-12 정규화 이관 항목 (2026-09-03 ~ 2026-09-11 6.1 상세 전문)

> 2026-09-12 CURRENT_STATE.md 정규화(8,000자 예산 준수)를 위해 6.1 미해결 사항에서 전문을 이관한 항목들입니다. 사실과 측정 로그를 보존합니다.

- **Windows Docker Desktop 실기 (2026-09-03, 미검증)**: 장비 확보 후 Compose healthy, 예측 API, 마이그레이션을 확인합니다.
- **SSR E2E (2026-09-11, 해소)**: Phase 1~4 가 이미 구현돼 있었고 전용 CI Job `e2e-browser-test` 가 skip 0 조건으로 통과합니다. 2026-09-02 조사 시점의 대기 표기가 구현 이후에도 갱신되지 않아 사실이 낡아 있던 것을 바로잡았습니다.
- **RPO/RTO 복구 목표 (2026-09-11, 실측 통과)**: RPO 24시간·RTO 4시간을 확정했고 런북 공란을 그 값으로 고쳤으며 분기 복구 절차서를 병합했습니다. 로컬 단계 나눔 드릴은 `data/backups/restore_drill_report_20260911.json` 기준으로 통과했고 총 852.83초로 RTO 한도 이내입니다.
- **워커 런처 계열 (2026-09-08, 해소)**: 런처 테스트의 실제 프로세스 부작용, 자동 승인 감시기 자기 종료, preamble 인계 규약 공용화, claude/opencode/grok 런처 신설, dispatch 런처 자동 선택을 Wave AM/AN 8건으로 닫았습니다. 사용 CLI 7종 중 6종이 `dispatch --launcher` 정규 경로에 있습니다(codex 는 구조가 달라 대상 아님).
- **자동 승인 화이트리스트 (2026-09-08, 판단 대기)**: `pgrep`, 환경변수 접두 명령, `git add`/`git commit`, `orca orchestration send`, CLI `--help` 가 화이트리스트 밖이라 워커마다 사람 승인이 필요합니다. 열지 여부는 사용자 결정 사항입니다.
- **자동 승인 화이트리스트 (2026-09-10, 확장 완료)**: 워커가 매번 사람 승인을 기다리던 명령을 열었습니다. `git add` 는 **명시 경로만** 허용하고 `-A`, `--all`, `-u`, 점 경로, 인자 없음을 거부합니다. 다른 작업의 미커밋 산출물을 삼키는 것을 막기 위함입니다. `git commit` 은 `-m`, `--message`, `-F`, `--file` 만 허용하고 **`--no-verify` 와 `-n` 을 절대 거부**합니다. 열리면 premerge 전량 테스트 게이트와 커밋 메시지 검증이 통째로 우회되기 때문이며, `--amend`, `--allow-empty`, `--author`, `--date`, `--reset-author` 도 같습니다. `pgrep` 과 임의 명령의 `--help`/`-h`, `orca orchestration send` 를 열었고 `orca` 의 다른 서브커맨드는 여전히 보류입니다. `git reset`, `push`, `checkout`, `restore`, `merge`, `rebase`, `worktree add/remove` 는 그대로 보류입니다.
- **관측성 2단계 Prometheus (2026-09-11, 대시보드·레이턴시 실측 완료)**: Collector prometheus exporter, Prometheus 스크랩, Grafana 데이터소스와 HTTP/DB 지연 대시보드를 넣었습니다. 메트릭 켜짐 예측 API c10 600x3 최악 P95 는 56.74ms(꺼짐 48.71ms) 이며 G3 100ms 한도를 통과했습니다.
- **SLO·알람 규칙 (2026-09-11, 완료)**: 예측 API P95 100ms, 5xx 0.1%, SSE 전체 P95 20초를 Prometheus 규칙과 Alertmanager `local-hold` 로 넣었습니다. SSE 첫 토큰 3초와 100ms 초과율 0.5% 는 라이브 메트릭이 없어 벤치마크 게이트로 남겼고, 메일·Slack 수신기는 비밀값 승인 후입니다.
- **RAG cold SQL (2026-09-07, 정본 확보·1차 원인 미규명)**: 버퍼풀을 실제로 비운 뒤(121,120 -> 1,192 페이지) 타임아웃 300초로 측정해 96요청 전량 성공으로 canonical 게이트를 통과했습니다(`rag_segments_coldpool_20260907.json`, sql 구간 콜드 P50 11.9ms·max 69.3ms). 콜드 버퍼풀 실행이 가장 빨라 1차의 10만 ms 대 값은 버퍼풀로 설명되지 않으며 원인은 미규명입니다. 재현 가능한 두 조건에서 근거가 없으므로 타임아웃 기본값 120초는 유지합니다.
- **RAG cold SQL 원인 조사 (2026-09-10, 가설 좁힘·미확정)**: 1차의 10만 ms 대 값을 코드 판독으로 조사해 가설 다섯을 순위와 근거로 정리했습니다(`docs/analysis/at2_coldsql_cause_investigation_20260910.md`). **그 값을 쿼리 실행 시간이라 부르면 안 됩니다.** 타이머가 SQL 실행만 감싸는지 캐시 조회와 세션 checkout 과 결과 조립까지 감싸는지 미확정이므로 정형 SQL 구간 계측값이 정확한 표현입니다. 유력 후보는 캐시 miss 시 선행 와일드카드 `LIKE` 와 `GROUP BY` 를 포함한 실시간 집계, 그리고 연결 획득 대기가 `sql_ms` 에 함께 계상되는 계측 범위 둘입니다. warmup 하네스는 직렬 1회 호출이라 직접 원인으로는 약하나 캐시와 연결 상태 교란 후보로 남습니다. 동시 요청 경합 가설은 하네스가 `concurrency=1` 직렬이라 이번 측정의 설명으로는 기각에 가깝습니다. 실행 가능한 다음 실험을 판정 기준과 함께 보고서 6장에 남겼습니다. **같은 날 코드 판독으로 셋을 확정했습니다.** 네 문항의 공통점은 날짜 범위나 카테고리가 아니라 기관명 필터를 가진 개체 지정 낙찰 질의라는 점이며, 기관명 필터가 `_snapshot_scope` 를 `None` 으로 만들어 live 경로를 선택합니다(`src/rag/structured_data.py:191-204`). `sql_ms` 는 `retrieve_structured_data` 호출 직전부터 반환 직후까지를 감싸므로 Redis 캐시 조회, lazy checkout 대기, 다중 SQL, 결과 조립, `corrupted_probe` 가 전부 그 안에 들어갑니다(`src/rag/engine.py:743-747`). 정형 DB 호출은 `asyncio.to_thread` 로 오프로드되므로 이벤트 루프 블로킹 가설은 부정됐고, 스레드풀과 DB 풀 경합은 별도 가설로 남습니다(`src/rag/engine.py:1177-1185`). 남은 것은 개별 SQL 시간 구성비의 후속 계측입니다.
- **lexical 전량 재측정 (2026-09-10, 완료·콜드 SQL 재현)**: 전량 fixture 32문항 repetitions 3 으로 96요청을 측정해 canonical 게이트를 통과했습니다(`data/benchmarks/rag_segments_lexical_full_20260910.json`, trace 96/96 중복 0, `git_sha` `df602cd`). 구간은 `llm_ms` P50 2,529ms, `vector_ms` P50 291ms, `total_ms` P50 3,176ms 입니다. **부수적으로 콜드 SQL 지연을 재현했습니다.** `sql_ms` 는 P50 9.51ms 인데 max 90,415ms 이고, cold 32건에서만 P95 79,632ms 로 폭발합니다. 10초를 넘긴 문항은 **q03, q08, q25, q31 넷뿐**이며 2026-08-30 에 지목된 그 문항과 정확히 같습니다. 각 문항의 warm 회차는 8에서 17ms 로 정상입니다. 이로써 기관명 필터가 `_snapshot_scope` 를 `None` 으로 만들어 live 집계 경로를 타는 것이 원인이라는 판정이 코드 판독과 재현 실험 양쪽에서 뒷받침됐습니다.
- **콜드 SQL 구간 귀속 (2026-09-10, 원인 확정)**: AU2 계측을 켜고 q03/q08/q25/q31 을 repetitions 3 으로 측정해 90초의 구성을 확정했습니다(`data/benchmarks/rag_segments_coldsql_r20_20260910.json`, 근거 `docs/analysis/av2_coldsql_segment_measurement_20260910.md`). **`cursor_ms / sql_ms` 가 99.9% 이고 `residual_ms` 는 85에서 126ms 입니다.** connection checkout 대기 가설과 파이썬 조립·직렬화 가설은 **기각**됐습니다. 최악 트레이스 113,300ms 의 최상위 구간은 `top_rows_2` 43,853ms(38.7%), `top_rows_3` 42,613ms(37.6%), `cached_aggregate_2` 22,070ms(19.5%) 이며 소계가 `cursor_ms` 와 일치합니다. **단일 최대 항목은 `corrupted_probe` 로 42,990ms(37.9%)** 이고 이것은 `top_rows_2`·`top_rows_3` 안에 중첩돼 있으므로 최상위 소계에 더하면 안 됩니다. 탐침은 `col.contains(REPLACEMENT_CHAR)` 즉 선행 와일드카드 `LIKE` 라 인덱스를 쓸 수 없고, `.limit(1)` 이 있어도 손상 행이 없으면 조기 종료가 없어 **데이터가 깨끗할수록 느립니다.** 용도는 `dropped` provenance 표시 하나입니다. 네 트레이스 모두 같은 구성비이며 값만 75,564에서 113,300ms 로 흔들립니다. AT2 가 탐침을 낮은 우선순위 후보로 둔 판단은 실측에서 뒤집혔습니다. **수정은 미착수이며 탐침 제거 가부는 `dropped` 표시 포기 가능 여부가 선결입니다.**
- **손상 탐침 제거 (2026-09-11, 구조적 제거 확정·효과 크기 미확정)**: 스냅샷 재구축이 손상 유무와 무관하게 rank=0 마커를 기록하고(`metric_count` 1 또는 0), 실시간 경로가 마커 존재 여부를 값과 분리해 읽어 `corrupted_probe` 를 건너뜁니다(`817cb22`). **확정된 것은 둘입니다.** 콜드 4건의 `corrupted_probe_ms` 합계가 144,541ms 에서 **0ms** 가 됐고 `cursor_count` 가 11~12 에서 **9** 로 줄었습니다. 탐침 질의가 그대로 사라진 구조적 사실이라 타이밍 잡음과 무관합니다. **총 시간 개선은 미확정입니다.** 콜드 `sql_ms` 합계는 392,745ms 에서 327,322ms 로 줄었으나 남은 쿼리의 회차간 분산이 10배라(`cached_aggregate_2` 가 1,665에서 40,984ms) 이 차이를 효과 크기로 인용하면 안 됩니다. 두 측정 사이에 스냅샷 재구축이 있었고 Redis 초기화도 한쪽에만 적용돼 조건이 다릅니다. **효과는 마커가 있어야 납니다.** 마커가 없으면 종전대로 탐침이 돌며, 운영에서는 야간 스냅샷이 그 역할을 합니다. 탐침 제거 후 남은 1순위는 `_cached_aggregate` 두 호출로 최악 트레이스의 62.3% 입니다. 근거는 `docs/analysis/aw2_probe_removal_effect_20260911.md` 입니다.
- **측정 설계와 실행계획 조사 (2026-09-11, 도구 완비·원인 미확정)**: 콜드 SQL 측정이 효과 크기를 판정할 수 있게 됐습니다. 하네스가 `structured_sql_segments` 를 결과 JSON 에 담고, `scripts/compare_rag_segments.py` 가 구조 차이는 확정, 구성비는 참고, 절대 시간은 산포 대비로 판정합니다. **시간 분기에는 확정과 개선이라는 판정 자체가 없습니다.** 가능한 문구는 판정 불가, 구별 불가, 산포 초과(참고) 셋뿐이라 잡음을 개선으로 읽을 경로가 구조적으로 막혀 있습니다. 표본 부족은 구별 불가와 구분해 판정 불가로 보고합니다. 비교기는 읽기 전용이며 자동 승인 화이트리스트에 등록됐습니다. **옛 하네스가 만든 결과 JSON 은 정형 트레이스가 없어 판정 불가가 나옵니다.** 2026-09-10 이전 측정은 소급 비교할 수 없고 새 하네스로 다시 재야 합니다. 한편 매칭 쿼리 실행계획 뒤집힘은 **원인 미확정**입니다. 영속 통계 변화(마지막 갱신 2026-09-01), 수집 데이터 증가(`MAX(collected_at)` 2026-09-10 02:04), 인덱스 현황 변화 세 가설을 각각 기각했고, 남은 후보는 메모리 통계와 index dive 와 동시 테스트 쓰기입니다. **계획 전환 경계가 실재합니다.** `EXPLAIN` 추정 기준으로 2025-08-15(9.5%)에서 2025-09-01(9.2%) 사이에 전환점이 있고 운영 대표값 2025-09-10 은 9.0% 로 경계 바로 옆입니다. 부수적으로 **영속 통계가 낡았습니다**. `bid_announcements` 통계 2,295,025 행 대 실제 5,504,119 행으로 약 139.8% 차이입니다. `ANALYZE TABLE` 은 관찰 대상을 바꾸는 쓰기라 실행하지 않았고 승인 사항으로 남겼습니다. 근거는 `docs/analysis/ax1_measurement_design_20260911.md` 와 `docs/analysis/ax2_plan_instability_20260911.md` 입니다.
- **compare-stats 종단 기준선과 통계 갱신 (2026-09-11, 기준선 확정·효과 참고)**: 캐시 미적중 종단 wall time 을 회차별로 실측했습니다. **버퍼풀 가열 구간과 정상상태를 구분해야 합니다.** 가열 5회는 6,466~17,298ms 로 단조 감소하고, 정상상태 6회는 5,038~5,928ms 평균 5,526ms 입니다. **정상상태 산포 890ms 가 이 경로 최적화의 판정 바닥입니다.** 그보다 작은 개선은 n=6 으로 구별할 수 없습니다. AV1 이 남긴 잔여 2.33초는 기준값 조건이 달라 생긴 값이며, 같은 조건에서 다시 재면 **약 1.4초**이고 HTTP·FastAPI·SQLAlchemy·조립·Redis 쓰기 구간입니다. 숨은 SQL 이 아닙니다. **`ANALYZE TABLE` 을 실행했습니다(되돌릴 수 없음).** `bid_results` 통계 3,118,641 -> 3,388,123, `bid_announcements` 2,295,025 -> 6,377,745 입니다(실제 3,431,580 과 5,504,119). 동일 절차 재측정은 3,889~4,030ms 평균 3,951ms 산포 141ms 이며, 범위가 겹치지 않고 평균차 1,575ms 가 산포 합 1,031ms 를 넘지만 판정 규칙상 **산포 초과(참고)이고 확정이 아닙니다.** 적용 전 통계를 복원할 수 없어 표본을 늘릴 수 없습니다. **확정할 수 있는 것은 계획 안정화입니다.** 매칭 쿼리가 `EXPLAIN` 3회 전부 `ALL` 로 고정됐고 산포가 890ms 에서 141ms 로 6.3배 조여졌습니다. 다만 **전체 스캔 쪽으로** 고정됐으며 매칭 쿼리 단독은 1,265~1,584ms 로 이전과 같은 계열이라, 종단 1.6초 개선은 매칭 쿼리에서 온 것이 아닙니다. 쿼리별 귀속은 미실시입니다. 근거는 `docs/analysis/ay1_compare_stats_endtoend_and_analyze_20260911.md` 입니다.
- **KB 색인 메모리 폭주 (2026-09-09, 해소)**: Wave AP 다섯 Task 를 병합한 뒤 두 조건에서 실측해 해소를 확인했습니다. 16GiB 조건 피크 4,323MB, 14GiB 원복 조건 피크 1,027MB 이며 컨테이너 소멸이 없었습니다. 이어서 `HEAVY_TASK_NAMES` 에 `run_schedule_catchup_task` 를 추가해 3시간 타임아웃을 적용했고(`nightly_schedule_task` 는 cron 에서 이미 받고 있어 대상 아님), catchup 로그가 안내한 수집 공백은 실재하지 않음을 `--dry-run` 으로 확인했으며, 색인 상한을 500,000 에서 **520,000** 으로 올려 최근 1년 505,271건 전량을 **삭제 0건**으로 색인했습니다(14GiB 조건 피크 4,051.8MB, 243.66초). 상한 정의가 두 모듈에 중복돼 있던 구조도 단일 정의로 통일했습니다.
- **스케줄 따라잡기 (2026-09-08, 해소)**: 이미 지난 매일 02:00 크론 슬롯을 놓쳤으면 기동 시 한 번 보충하도록 판정을 슬롯 기준으로 바꿨습니다(`80d7cb0`). 종전에는 경과 24시간 임계치만 봐서 19시간 경과 시점에 `threshold_not_exceeded` 로 거부했습니다. 쿨다운은 유지하며 재시작 반복 발화를 막습니다. 운영 발화를 실측 확인했습니다(`reason=missed_schedule`, `last_cron_slot=2026-09-08T02:00:00`).
- **적격심사 정량평가 (2026-09-10, 동작)**: 공고 상세 페이지에 공고 기준 분석 카드를 붙였습니다. 일반용역은 별표 14종 하한율을 DB 실측으로 확정했고 `B`·`k`·`T` 는 사용자 입력입니다. 기술용역은 `srvceDivNm=기술용역` 이고 `sucsfbidMthdNm`에 적격심사가 있으면 공고 하한율만 쓰며 44개 문자열을 공통 배점표로 묶지 않습니다. 하한율이 없으면 `TECH_SERVICE_MISSING_LWLT` 로 차단합니다. 실사용 표본은 `docs/analysis/ar2_tech_servc_realuse_announcements_20260910.md` 에 14건입니다. 화면 범위 배지는 응답마다 일반용역·기술용역·협상 셋 중 하나로 다시 설정하며 기술용역일 때 공고 하한율을 쓴다는 사실을 표시합니다. 차단 사유 문구 사전에 `TECH_SERVICE_MISSING_LWLT` 를 넣었고, 서버가 `코드: 메시지` 형태로 보내는 `blocked_reason` 에서 코드 접두를 분리하도록 고쳤습니다. 종전에는 사전 키가 순수 코드라 어떤 코드에도 매칭되지 않아 다섯 항목이 전부 죽어 있었습니다. `BLOCK_CODE` 상수 8종이 모두 접두 분리에 걸리는 것을 확인했습니다.
- **금지 패키지 산출물 게이트 (2026-09-10, 동작)**: 이 저장소는 npm 이 정본이고 pnpm 과 yarn 을 금지하는데 그 금지를 검사하는 장치가 없어 두 번 새어 들어왔습니다. Level 1 게이트에 게이트 9 를 추가해 `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `yarn.lock`, `bun.lockb` 가 작업 트리에 있으면 병합을 차단합니다. 커밋 여부와 무관하게 파일 시스템을 직접 보며, 루트와 `frontend/` 의 `package-lock.json` 은 정본이라 허용하고 `node_modules/` 아래는 검사하지 않습니다. 11GB 주 저장소에서 1.45초입니다. `orca_worker_watch.py` 는 같은 집합을 비차단 경고로 알리되 전체 순회 대신 이미 실행한 `git status` 의 untracked 목록을 재사용하므로 추가 비용이 없습니다. 그 대신 gitignore 대상은 감시기 검출에서 빠지며 병합을 막는 정본 판정은 게이트 9 입니다. 집합 정의는 `scripts/orca_forbidden_artifacts.py` 단일 원천입니다. 감시기는 `git status` 가 `core.quotePath` 로 큰따옴표와 C 스타일 이스케이프를 씌운 비ASCII 경로도 해석하며, 디코딩할 수 없는 줄은 경고 후 건너뛰어 상시 감시가 멈추지 않습니다.
- **워크트리 setup 의 pnpm 오염 (2026-09-11, 해소)**: 산출물을 만들던 것은 워커가 아니라 Orca 프로젝트 setup 스크립트였습니다. 사용자가 Orca 앱에서 설정 스크립트를 `pnpm install` 에서 `npm ci` 로 바꾸고 실행 시기를 기본 건너뛰기로 지정했습니다. 현재 값은 `scripts.setup=npm ci`, `setupRunPolicy=skip-by-default` 입니다. `--setup skip` 없이 워크트리를 만들어 `pnpm-lock.yaml`·`pnpm-workspace.yaml`·`yarn.lock`·`bun.lockb` 가 모두 생기지 않고 `node_modules` 도 설치되지 않음을 실측했습니다. **이제 `--setup skip` 을 붙이지 않아도 됩니다.** 게이트 9 는 방어선으로 그대로 둡니다. 이 설정은 저장소 밖 로컬 설정이라 다른 기계에서는 다시 확인해야 하며, `orca.yaml` 로 옮기면 버전 관리 대상이 됩니다.
- **compare-stats 병목 규명 (2026-09-10, 실측으로 뒤집힘)**: 선행 조사(`at4`)는 `EXPLAIN` 추정으로 매칭 건수 쿼리를 최우선 병목으로 지목하며 `bid_results` 약 311만 행 전체 스캔(`ALL`)을 근거로 들었습니다. **2026-09-10 실측이 이 전제를 재현하지 못했습니다.** `EXPLAIN ANALYZE` 3회 교차 실행에서 원형 `IN` 은 903/943/896ms, `EXISTS` 는 960/892/854ms 였고 **양쪽 모두 `ix_bid_results_dt_cat` range 스캔**이었습니다. 원형도 `ALL` 이 아니었고, 이 쿼리는 6.5초가 아니라 약 0.9초입니다. 평균 914.0ms 대 902.0ms 로 개선은 확인되지 않았습니다. COUNT 는 양쪽 327,686 으로 동일합니다. `EXISTS` 전환은 의미 보존과 회귀 안전을 근거로 병합했으나 **성능 개선 근거로 인용해서는 안 됩니다.** 추정과 실측이 갈린 원인은 미확정이며 bind 값 차이와 버퍼풀 설명은 리뷰에서 기각됐습니다. 6.5초의 실제 구성은 다시 규명해야 합니다. 근거는 `docs/analysis/au1_compare_stats_exists_verification_20260910.md` 입니다.
- **금액 집계 성능 (2026-09-10, 측정 완료)**: `GET /api/v1/bids/stats` 웜 레이턴시는 3.34ms(P95 3.80ms)입니다. `GET /api/v1/bids/compare-stats` 는 실측했습니다. 콜드(버퍼풀 빈 상태, 캐시 없음) 147.7초, 웜 캐시 미적중 회차별 25.2/11.3/9.8/8.9/9.1/6.3/6.8초로 **정상상태 약 6.5초**, Redis 캐시 적중 0.004~0.06초입니다. 전환 전 웜 31.97초 대비 약 4.9배 개선이며 **해소가 아니라 완화**로 읽어야 합니다. 6.5초는 여전히 느리고 24시간 TTL 캐시가 체감을 덮고 있을 뿐입니다. 측정 조건은 컨테이너 내부 `innodb_buffer_pool_size` 2048MB 이며 콜드 값은 회차 1건이라 게이트로 쓰지 않습니다.
- **협상에의한계약 지원 (2026-09-10, 동작)**: 협상 공고를 `NEGOTIATION_CONTRACT` 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율(`techAbltEvlRt`, `bidPrceEvlRt`)과 변종 식별자를 화면에 제공합니다. 변종은 기본·SW사업·엔지니어링·건설엔지니어링 넷이며 `다수공급자계약-적격성평가 및 가격협상` 은 대상이 아닙니다. **가격점수는 계산하지 않습니다.** 계수 `k` 와 통과점수 `T` 가 공고 데이터에 없고, `bid_results` 에 낙찰자 한 명만 있어 경쟁 투찰가 의존 산식은 사후 재현도 불가능하기 때문입니다. **2026-09-11 에 전 구간을 다시 셌습니다.** 협상 공고 **121,052건 전부** `sucsfbidMthdAppStd` 가 비어 있으며 기간은 2025-01-05 부터 2026-09-09 까지입니다. 같은 기간 협상이 아닌 공고에는 값이 있어(2026-01-01 이후 327,874건 중 68,256건, 20.8%) 수집 누락이 아니라 **협상 공고에만 해당 항목이 제공되지 않는 구조**로 보입니다. 채움률만 보고 착수하면 헛일이므로 반드시 협상 공고로 좁혀 확인하십시오. 대신 변종별 과거 낙찰률 실측 분포를 참고값으로 제시하며 Redis 24시간 캐시를 거칩니다(콜드 1.6~2.6초, 캐시 0.0003초). 순위와 낙찰 여부는 계산 불가로 명시했습니다.
