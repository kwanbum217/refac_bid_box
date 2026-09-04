# 인수인계: 2026-09-04 도커 스택 점검과 금액 정합성

> **작성일**: 2026-09-04
> **코디네이터**: Claude Opus 5
> **인수 시점 main**: `67780db`
> **종료 시점 main**: `eca9f37` (origin/main 푸시 완료)
> **작업 트리**: 주 저장소 1개. 미병합 브랜치 1개(`perf/dashboard-amount-aggregation`, 커밋 없음)
> **Orca**: 사용하지 않음. 단독 세션이며 겹치는 파일·자원 없음

---

## 1. 이번 세션에서 한 일

사용자 요청은 "도커 서버를 올려 프론트·백엔드 점검"이었습니다. 점검 중 데이터
공백과 금액 오류가 드러나 그 둘을 처리했습니다.

| 순서 | 병합 커밋 | 내용 | 검증 |
| --- | --- | --- | --- |
| 1 | `9c78b2f` | 워커 기동 시 스케줄 따라잡기 활성화 | 3488 passed, 규칙 20/20 |
| 2 | `eca9f37` | 공고 금액 집계 오버플로우와 파싱 규칙 불일치 해소 | 3491 passed, 규칙 20/20 |

---

## 2. 스택 점검 결과 (전부 정상)

컨테이너 5개 전부 healthy. `/api/v1/health/ready` 는 `ready` 이며 MySQL, Redis,
Meilisearch, 모델 레지스트리, ChromaDB, Ollama 가 모두 ok, 워밍업 3종 완료입니다.

SSR 페이지는 전부 200 입니다.

| 페이지 | 응답 |
| --- | --- |
| `/` | 200 / 540ms |
| `/bids/` | 200 / 17ms |
| `/bids/results/` | 200 / 151ms |
| `/bids/dashboard/` | 200 / 7ms |
| `/bids/compare/` | 200 / 6ms |
| `/chatbot/` | 200 / 287ms |
| `/bids/{pk}/` `/bids/result/{pk}/` | 200 / 53ms, 286ms |

점검용 계정 `stackcheck0904` (id=14) 를 만들었습니다. 불필요하면 지워도 됩니다.

**주의**: `/bids/compare/` 와 `/bids/dashboard/` 의 빠른 응답은 껍데기만 내려주기
때문입니다. 실제 데이터는 JS 가 API 로 따로 가져오므로 페이지 200 이 곧 화면
정상을 뜻하지 않습니다.

---

## 3. 데이터 공백 8일치 백필

마지막 수집이 `2026-08-27 07:14` 에서 멈춰 있었습니다. 일일 수집 크론은 02:00
KST 인데 그 시각에 스택이 내려가 있어 크론이 돌 기회가 없었고, 기동 시
따라잡기도 꺼져 있어 재기동으로도 메워지지 않았습니다.

`scripts/backfill_from_g2b.py --sync-downstream` 으로 메웠습니다.

| 항목 | 결과 |
| --- | --- |
| 신규 적재 | 공고 7,768건 / 낙찰 4,859건 |
| 파생 집계 | 기관 38,953, 순위 스냅샷 150행 |
| ChromaDB KB | 12,011건 반영 (전체 534,571) |
| Meilisearch | 공고 7,190 / 낙찰 4,806 |
| 정합성 검사 | **실패** (아래 6.2) |

---

## 4. 스케줄 따라잡기 활성화 (`9c78b2f`)

`run_schedule_catchup_task` 는 이미 구현돼 있었으나
`AUTOMATION_SCHEDULE_CATCHUP_ENABLED` 기본값이 False 이고 어느 compose 에도
설정이 없어 **한 번도 동작한 적이 없습니다.** 개발·운영 compose 양쪽 워커에
활성화를 추가했습니다.

판정 경로 양쪽을 컨테이너에서 실측했습니다. 임계 이내는
`needed=False (threshold_not_exceeded)`, 임계 초과는
`needed=True (threshold_exceeded)` 입니다.

**함정**: 워커의 루트 로깅 레벨이 WARNING(30) 이라 따라잡기 판정의
`logger.info` 가 찍히지 않습니다. 로그가 없다고 미동작으로 판단하지 마십시오.
확인은 `settings.AUTOMATION_SCHEDULE_CATCHUP_ENABLED` 직접 조회로 하십시오.

---

## 5. 금액 정합성 (`eca9f37`)

`compare-stats` 의 공고 총액이 `-6,063,896,128,872,295,352` 였고 기관 순위 1위가
324건짜리 기관의 137경원이었습니다. 상세는
[`announcement_amount_outliers_20260904.md`](announcement_amount_outliers_20260904.md).

원인은 셋입니다.

1. 행마다 BIGINT 캐스팅 후 SUM 해서 컬럼에 담기 전에 wrap. `Numeric(30,0)` 으로 변경.
2. 조달청 원본에 100조 초과 33건(자릿수 중복 4, 더미값 27, BIGINT 포화 2). 원본은 보존하고 집계에서만 배제.
3. 파싱 규칙 불일치. 집계 SQL 에 콤마 제거가 없었고, `_coerce_amount` 는 `int(float(...))` 로 20자리 원본을 어긋나게 만들었습니다.

**결과**: 운영 DB 실측 총액이 `2,125,507,790,559,697` (549만 건, 평균 3.87억) 로
정상 복구됐습니다.

---

## 6. 미해결 항목

### 6.1 `bid_dataset_summaries` 에 음수가 남아 있음

코드는 고쳤지만 **테이블에는 아직 `-6,063,896,128,872,295,352` 이 저장돼
있습니다.** 화면은 이 값을 봅니다. 갱신하려면 재집계가 필요한데 그 쿼리가
477초 걸리므로 6.3 을 먼저 처리하는 편이 낫습니다.

### 6.2 정합성 검사 103건 (데이터 손실 아님)

`run_data_reconciliation.py` 의 검사는 **낙찰결과** 식별자 기준으로 ChromaDB 를
보는데, KB 색인은 **공고** 기준(`announcements_by_collected_delta`)으로만
넣습니다. 이번 낙찰 4,806건 중 대응 공고가 `bid_announcements` 에 없는 건이
정확히 103건이며 검사가 지목한 수와 일치합니다. 구조상 KB 에 들어갈 수 없어
검사가 필연적으로 실패합니다. 검사 기준을 고칠지 색인을 넓힐지 판단이
필요합니다.

### 6.3 `agency_top10` 성능 (진행 중이던 작업)

원래 착수 대상이었습니다. 브랜치 `perf/dashboard-amount-aggregation` 을 만들어
두었으나 **코드 변경은 아직 없습니다.**

| 쿼리 | 웜 상태 |
| --- | --- |
| `matched_count` | 2.20s |
| `announce_by_month` | 0.39s |
| `result_by_month` | 0.22s |
| `agency_top10` | 31.97s |
| 전체 summary SUM | 477s |

원인은 금액을 `raw_data` longtext 에서 JSON 파싱해 집계하기 때문입니다.

**핵심 발견**: 수집 코드(`api_collector.py:279`)가
`base_amount = extract_business_budget(raw_data)` 로 저장합니다. 즉 컬럼에 이미
파싱 결과가 들어 있고, 집계는 같은 파싱을 549만 번 다시 하고 있습니다.

전수 대조 실측 (5,497,840건):

| 구분 | 건수 |
| --- | --- |
| `base_amount` == 파싱값 | 3,972,687 |
| raw_data 에 금액 키 없음 (양쪽 NULL) | 1,524,810 |
| 파싱되는데 컬럼 NULL | 234 |
| 값이 다름 | 109 |
| raw_data 가 NULL | 0 |

`base_amount IS NOT NULL` 이 3,972,796 으로 위 분류와 정확히 맞아떨어집니다.
**컬럼 기반으로 바꿔도 달라지는 행은 343건(0.006%)뿐입니다.**

예비 실측으로 `base_amount` 만 쓰는 `agency_top10` 은 **6초**였습니다(다른 무거운
쿼리와 경합 중 측정이므로 단독이면 더 빠를 것입니다).

**남은 확인 1건**: 불일치 343건의 정체를 확인하려 했으나 조회가 20분을 넘겨
세션 종료로 중단했습니다(`KILL QUERY`). parquet 복구분일 가능성이 있습니다.
343건이 무시 가능한 수준인지 확인한 뒤 컬럼 기반으로 전환하십시오.

### 6.4 BIGINT 포화 2건의 `base_amount`

`R25BK01131785`, `R25BK01210563` 의 `9223372036854775807` 은 조달청 원본이 아니라
적재 과정이 만든 값입니다. `NULL` 이 맞아 보이나 DB 값 변경이라 승인을 받지
못해 보류했습니다. 현재는 집계에서 배제되어 화면 영향은 없습니다.

### 6.5 수집 단계 범위 검증 부재

BIGINT 범위를 넘는 값이 경고 없이 클램프되어 적재됩니다.

---

## 7. 다음 착수 순서 제안

1. 6.3 의 남은 확인(343건) 후 `_announcement_amount_expr` 를 `base_amount` 기반으로 전환.
2. 전환 후 `bid_dataset_summaries` 재집계로 6.1 해소. 화면 숫자가 정상으로 돌아옵니다.
3. 6.2 의 검사 기준 판단.
4. Windows Docker Desktop 실기 검증. G2 게이트가 계속 보류입니다.

---

## 8. 자원 상태

- 도커 스택: 전부 내림. Redis 는 `SHUTDOWN NOSAVE` 로 종료.
- 백그라운드 작업: 전부 종료. 장시간 MySQL 조회 1건은 `KILL QUERY` 로 중단.
- 워크트리: 주 저장소 하나.
- 브랜치: `perf/dashboard-amount-aggregation` 이 남아 있으나 커밋이 없어 버려도 무방합니다.
- `origin/main` 은 `eca9f37` 까지 푸시 완료.
