# 핸드오프 인수인계 - 2026-11-10 세션

> **작성일**: 2026-11-10
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_e892c513c825`(신규), `run_f846c95069c9`(B4 리뷰만)
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `3fa50e0b` 입니다. 이 문서는 브랜치 `kwanbum217/handoff-20261110` 에서 씁니다.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정).
> **종료 사유**: 사용자 지시로 인수인계 작성 뒤 Docker 와 배경 프로세스를 모두 내리고 종료합니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | Meilisearch 전체 재색인 완료(사용자 지시로 이월) | `make up` 뒤 `docker compose exec app env MEILI_TIMEOUT_SECONDS=30 python3 scripts/sync_search_index.py`. 약 840만 건을 1,000건 묶음으로 보내며 스크립트 송신이 병목이라 약 45분 걸립니다(분당 약 180묶음). 완료 판정은 `/tasks?statuses=enqueued,processing` 의 `total` 0 과 `/bids/` 200. 전량 시험과 겹치면 시간 측정 시험이 흔들리므로 동시에 돌리지 않습니다 |
| 2 | 마지막 병합들의 main CI 확인 | `gh run list --branch main --limit 8`. 공급망·시험 job 이 통과해야 합니다 |
| 3 | 예비가격 수집 따라잡기 | `bid_prearng_prices.rl_openg_dt` 최대가 2026-10-14 입니다. Docker 를 띄우면 `prearng_daily` 크론(최근 14일 창)이 돕니다. 10-14 ~ 10-27 개찰분은 14일 창 밖이라 소급 수집이 따로 필요합니다(아래 3장) |
| 4 | 스케줄 실행 기록 영속화 | 실패 기록이 Redis 7일 TTL 로 사라져 10-17 이후 중단 원인을 확정하지 못했습니다 |
| 5 | I-ai·I-data 미확인 항목 재현 | 11-09 인수인계 4장 그대로입니다 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 브랜치 | 내용 |
| --- | --- | --- |
| `e4f124e6` | B3 compare-match | 비교 화면 매칭률 분자·분모를 최근 365일 공고 기준으로 통일, 99.8% 고정 문구 제거 |
| `74aeeb1c` | B2 cnstwk-guard | 전용 모델 없는 분야(공사·외자) 투찰가 추천 차단, v25 대체 후보 제거 |
| `b4f98444` | B4 qual-badge | 목록·홈 적격심사 배지와 Meilisearch 색인 문서에 첨부 판별 갈래 반영, 갈래 분류 뒤 색인 갱신 |
| `260a7600` | B5 manual-retrain | 수동 재학습이 주간 재학습과 같은 카테고리 fan-out(`run_retrain_category_fanout`)과 중복 방지를 공유 |
| `f8c43411` | F-02 sajeong-refresh | 예비가격 적재 뒤 수요기관명 연결과 기관별 사정률 재집계 자동 실행, 연결 로직을 `src/app/services/prearng_dminstt_link.py` 로 단일화, 원인 문서 `docs/analysis/sajeong_stats_refresh_20261110.md` |
| `3fa50e0b` | win-onboard-reindex | windows-onboarding 스킬 4장 A 에 복원 뒤 Meilisearch 재색인·확인 절차와 `MYSQL_CLIENT_CONTAINER` 안내 |

모든 브랜치는 빌더 → GLM 독립 리뷰 pass → Level 1 strict 증거 → 전량 시험 증거 순서를 거쳤습니다. 병합한 워크트리는 병합 직후 제거했고 브랜치는 `refs/backup/<이름>` 에 고정한 뒤 삭제했습니다. 남은 워크트리와 워커는 없습니다.

---

## 2. 운영 반영

| 항목 | 결과 |
| --- | --- |
| 수요기관명 연결(사용자 지시) | `link_prearng_dminstt.py --execute` 로 빈 `dminstt_nm` 30건을 채웠습니다. 미매칭 88건이 남습니다. 빈 값만 채우는 갱신이라 덮어쓰기는 없습니다 |
| 사정률 통계 재집계(사용자 지시) | `rebuild_institution_sajeong_rate_stats` 1회 실행, 1,060행 → 1,042행(기관 1,025, 시·도 16, 분야 1), `rebuilt_at` 2026-11-10 06:23:44, 6.6초. 1,095일 창이 밀리고 새 수집이 없어 일부 기관이 최소 표본 아래로 내려간 것으로 봅니다 |
| 백업 | `data/backups/sajeong_refresh_20261110/` 에 통계 테이블 덤프와 빈 수요기관명 키 118건 목록. Git 미추적이며 커밋하지 않습니다 |
| Meilisearch 재색인 | B4 병합 직후 app·worker 재시작과 전체 재색인을 완료했습니다(공고 4,931,956건, 낙찰 3,473,111건). 모든 병합 뒤 두 번째 전체 재색인은 약 25%(약 2,090묶음/8,400묶음) 진행 중 사용자 지시로 중단했습니다. 이후 병합(B5, F-02, windows-onboarding)은 색인 문서를 바꾸지 않아 색인 내용은 B4 반영 상태와 같다고 봅니다. 중단은 upsert 도중이라 색인을 깨뜨리지 않습니다. 0장 1번 과업으로 넘깁니다 |

---

## 3. 미착수·후속 과업

| 과업 | 근거 | 비고 |
| --- | --- | --- |
| 예비가격 소급 수집 | `prearng_daily` 는 최근 14일 개찰분만 봅니다. 10-14 이후 공백 중 14일 창 밖 구간은 자동으로 채워지지 않습니다 | 소급은 `stream_servc_prearng_range` 경로. 나라장터 호출량을 사용자와 정한 뒤 진행합니다 |
| 수집 중단 원인 확정 | 원인 문서 4장: 10-18 06:00 KST 이후 크론 슬롯 미실행, 실패 기록은 Redis TTL 로 소실 | 세션 종료마다 Docker 를 내리는 운영 방식과 겹칩니다. 영속 스케줄 원장 도입을 검토합니다 |
| 재집계 후속 단계 예외 | F-02 리뷰 notes: 예상 못한 예외 시 후속 단계가 실행되지 않고 다음 성공 실행에서 보정됩니다 | 결함 판정 아님 |
| CLASSIFIED → FAILED 전환 시 색인 지연 | B4 리뷰 notes: 다음 전체 재색인 전까지 배지가 낡을 수 있습니다 | 결함 판정 아님 |
| 물품·용역 극단 경고 화면 미전달(I-ai F-01 잔여) | 11-09 인수인계 4장 | 공사는 B2 로 해소 |
| 점검표 미달 3건, 성능 측정 | 11-09 인수인계 3장 그대로 | 미착수 |

---

## 4. 운영 메모

| 항목 | 내용 |
| --- | --- |
| 전량 시험 간섭 | B5 증거 기록 중 Meilisearch 전체 재색인이 함께 돌아 `test_cpu_utilization_metric.py` 시간 측정 시험이 1건 실패했습니다. 단독 3회 통과, 재색인 뒤 재기록에서 전량 통과. 재색인·전량 시험을 겹치지 마십시오 |
| B3 11-09 실패 | 단독 전량 재실행 10,676 통과로 간섭 판정했습니다 |
| OCR 시험 불안정 | `tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once` 가 10초 추출 타임아웃으로 오늘 두 번 실패했습니다(F-02 빌더 전량 시험, windows-onboarding 증거 첫 기록). 단독 재실행은 매번 통과합니다. 타임아웃 여유나 시험 격리를 후속 과제로 봅니다 |
| 문서 과업 Capsule 검증 명령 | `python3 scripts/sync_skill_mirrors.py --check` 는 Level 1 게이트 허용 목록 밖이라 게이트 3 이 실패합니다. 문서 과업은 `--tests tests/test_sync_skill_mirrors.py` 로 덮습니다 |
| 빌더 보고 blocked 처리 | F-02 빌더가 범위 밖 시험 실패로 verdict blocked 를 적어 게이트 6 이 실패했습니다. 코디네이터 재현 뒤 `coordinator-capsule` 로 검증했고, 체크리스트는 빌더 Capsule 원문 블록을 그대로 붙였습니다(`yaml.safe_dump` 는 목록 들여쓰기를 바꿔 게이트 2 가 범위를 못 읽습니다) |
| GLM 리뷰어 기동 | 런처 `--preamble .orca/preamble_<task>_rev.txt` + `orchestration dispatch --return-preamble`. 지시문이 Intent 이름 경로 Capsule 을 가리키므로 두 경로 모두에 복사합니다. 감시기의 "reportPath 누락" 실패 정체는 지시문 문구 오탐입니다 |
| 종료 상태 | Docker Desktop 정지, Orca 워커 0, 배경 감시기·재색인 프로세스 정지 |
