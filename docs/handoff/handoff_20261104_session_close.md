# 핸드오프 인수인계 - 2026-11-04 세션

> **작성일**: 2026-11-04
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_5878b718b767`
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `2d85d865` 입니다. 이 문서는 브랜치 `kwanbum217/close-20261104` 에서 F 보고서와 함께 묶어 병합합니다.
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 이 브랜치에서 병합 직전 `main` 으로 갱신했습니다.
> **종료 사유**: 사용자 지시(컴퓨터 종료). 워커 0대, Docker 전부 정지.

---

## 0. 다음 세션이 바로 할 일

1. **E 재작업.** 브랜치 `kwanbum217/orca-e-eligibility-window`(`f89c25b6`, 백업 `refs/backup/orca-e-eligibility-window`)는 병합 금지입니다. 3절의 집계 범위 결함을 고치는 rework Task 를 발급합니다. 30일 기본 창과 2024-01-01 하한 변경은 사양대로이므로 유지합니다.
2. **T5 빌더.** E 재작업이 병합된 뒤 그 위에서 시작합니다. E 와 같은 파일(`src/rag/query_planning.py`, `src/rag/structured_data.py`)을 고치기 때문입니다. 근거는 `docs/analysis/fail_bid_t5_prestudy_20261104.md` 4.2절이고 사용자 결정은 4절에 있습니다.
3. **조건 1 기준선 결정.** T5 병합 전에 사용자에게 받아야 합니다. 제안은 취소공고를 뺀 비율, 기준선 75% 입니다.
4. 이 문서의 병합 커밋 CI 를 다음 병합 전에 `gh run list --branch main --limit 3` 으로 확인합니다.

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| 이 문서의 병합 커밋 | F `edebf0ad`: 유찰 T5 착수 전 코드 대조 보고서 `docs/analysis/fail_bid_t5_prestudy_20261104.md`. 이 인수인계와 `CURRENT_STATE` source_commit 갱신 | F 리뷰 pass(체크리스트 5개 no), Level 1 pass, 리뷰어 미확인 주장 1건은 코디네이터가 직접 확인 |

---

## 2. Orca 기록

| Task | 상태 | 비고 |
| --- | --- | --- |
| `task_6574ff196efa` E 적격심사 기본 창 | completed | 빌더 cmd `deepseek/deepseek-v4.1-flash` high. Level 1 pass. **Level 3 반려(3절)** |
| `task_cfe166b8f064` E 리뷰 | 5절 참조 | 1차 cmd `z-ai/glm-5.3-flash` 는 공급자 500 으로 정체해 `failed` 처리, 사용자 지시로 `ready` 로 되돌려 Antigravity `gemini-3.8-flash-medium` 로 재 Dispatch(워크트리 `orca-e-review`, E 커밋 기반) |
| `task_6639f4e7018b` F 유찰 T5 사전 조사 | completed | 빌더 cmd deepseek default. 첫 `worker_done` 에 보고 파일이 없어 터미널 지시로 보완 |
| `task_9ae5ef569564` F 리뷰 | completed | cmd glm high, pass, `validate_review_report.py` 계약 만족 |

모든 워커는 런처 비감독 경로(`orca_cmd_launch.py`·`orca_agy_launch.py` 터미널 + taskctl `dispatch --launcher`)입니다. Capsule·보고 JSON 은 주 저장소 `.orca/capsules/` 에 회수했습니다.

---

## 3. E 반려 사유: 단일 집계가 건수를 줄인다

`announcement_ranking_with_total`(`f89c25b6`, `src/rag/structured_data.py`)은 COUNT 와 기관 순위를 `SUM(COUNT(*)) OVER ()` 한 문장으로 합쳤습니다. 그러나 기존 `announcement_total` 과 다른 조건 집합을 씁니다.

| 항목 | 기존 `announcement_total` | E 의 단일 집계 |
| --- | --- | --- |
| 조건 | `announcement_conditions` | `institution_conditions` + `exclude_corrupted(dminstt_nm)` |
| 기관명 NULL·U+FFFD 손상 행 | 포함 | 제외 |
| 기관 해석 상한 초과 시 `fallback_condition` | 포함 | 미포함 |

결과적으로 award_method 질의의 공고 건수가 기관명 손상 행만큼 줄어듭니다. 빌더 시험 (e) 는 깨끗한 픽스처라 이를 잡지 못했습니다.

재작업 사양 제안입니다.
- 전체 건수는 반드시 `announcement_conditions`(fallback 포함)와 같은 범위여야 합니다.
- 한 가지 방법은 손상 제외를 WHERE 에서 빼는 것입니다. 그 대신 `GROUP BY dminstt_nm` 결과에서 윈도 합계를 구하고, 손상·NULL 그룹은 정렬을 뒤로 보낸 뒤 파이썬 계층에서 순위만 거릅니다. 이때 기존 `dropped` 안내(마커·탐침)가 바뀌지 않음을 시험으로 고정합니다.
- 다른 방법은 단일화를 포기하고 30일 기본 창만으로 비용을 해결하는 것입니다. 최근 30일 스캔은 실측 1.1초라 이것만으로 충분할 수 있습니다.
- 시험에는 기관명 NULL 행과 U+FFFD 행이 섞인 픽스처에서 total 이 기존 COUNT 와 같다는 단언을 반드시 넣습니다.

---

## 4. 유찰 소급과 T5 준비

### 4.1 소급 적재(사용자 승인, 코디네이터 실행)

| 항목 | 값 |
| --- | --- |
| 명령 | `uv run python scripts/backfill_openg_results.py --max-calls 400 --execute` |
| 기간 | 2025-11-04 ~ 2026-11-04, 7일 창 53개 x 3분류 = 159창 |
| 결과 | 성공 159 / 실패 0, 호출 159회 |
| 적재 | `bid_openg_results` 416,228행. 개찰완료 330,717, 유찰 73,668, 재입찰 11,794, 재시담 49. Cnstwk 130,701, Servc 173,633, Thng 111,894 |
| 다른 테이블 | `bid_results` 3,464,615, `bid_announcements` 최대 id 10,339,615 로 적재 전후 같음 |
| 원장 | `.cache/openg_backfill_ledger.json` |

새 테이블에 대한 upsert 라 적재 전 전체 스냅샷은 만들지 않았습니다.

### 4.2 재입찰번호 유니크 재검증(`docs/analysis/openg_rbidno_uniqueness_20261102.md` 6절)

| 확인 | 결과 |
| --- | --- |
| 키 중복 | 0그룹(유니크 키가 DB 에 걸려 있어 구조상 0) |
| 키 빈 값 | 네 컬럼 모두 0 |
| `rbid_no` 분포 | `000` 404,738, `001` 9,936, `002` 1,234, `003` 235, `004` 59, `005` 18, `006` 7, `007` 1 |
| 같은 공고·차수·분류에 행 2개 이상 | 9,936그룹, 21,426행 |

판정: `rbid_no` 는 상수가 아니고 실제로 갈리므로 `uq_bid_openg_results`(공고번호, 차수, 재입찰번호, 분류)를 유지로 확정합니다.

### 4.3 가드 해제 조건(설계 6.1절, F 보고서 2절 질의)

| 조건 | 측정 |
| --- | --- |
| 1. 최근 30일 개찰 공고 중 개찰결과 보유 | 등록 23,886/29,020, 재공고 2,661/3,291, 변경 1,271/1,884, 취소 0/1,965. 취소 제외 81.4%(27,818/34,195), 포함 76.9%. 기준선 미정 |
| 2. 유찰 목록 상위 20건 | DB 기준 20/20 유찰 |
| 혼재 공고(같은 공고·차수·분류에 유찰과 비유찰) | 최근 30일 163, 1년 2,572 |

### 4.4 사용자 결정

| 결정 | 내용 |
| --- | --- |
| 적격심사 날짜 창 | 기간 없는 award_method 질의는 최근 30일 기본 창(지표 무관). 별도 컬럼·함수 인덱스는 추가하지 않음 |
| 유찰 공고 정의 | **최종 차수 기준.** 같은 공고·차수·분류에서 `rbid_no` 가 가장 큰 행이 유찰인 공고만 유찰 공고로 본다. 재입찰에서 개찰완료된 공고는 제외 |

### 4.5 T5 빌더 사양에 넣을 것

- F 보고서 4.2절의 변경 지점 전부: `is_announcement_list_query` 예외, `build_retrieval_plan` 의 `filters["outcome"]`, `BidOpengResult` import, `_announcement_conditions` 의 조건, 표본 select 의 `progrs_div_cd_nm`.
- EXISTS 대신 최종 차수 조건입니다. 같은 키의 최대 `rbid_no` 행이 유찰이어야 합니다.
- F 보고서 3.1절의 시험 갱신과 3.2절의 신규 시험. 혼재 공고 픽스처(유찰 `000` + 개찰완료 `001`)가 목록에서 빠진다는 단언을 추가합니다.
- `data/benchmarks/chat_user_questions_v2.json` 의 `v2_rbd_02`(유찰된 공사 공고 최근 5건)는 지금 미지원 안내로 통과합니다. T5 뒤에는 기대값을 실제 목록으로 바꿔야 합니다.
- `DATA_GAP_MESSAGES["유찰 상태"]` 는 호출 경로가 없으므로 삭제하거나 폴백을 구현해야 합니다. T5 안에서 결정합니다.

---

## 5. 측정

| 측정 | 결과 |
| --- | --- |
| v2 점검 세트 | **20/20**(2026-10-26 17/20). `main` `2d85d865`, 앱 재시작, `rag:*` 캐시 비운 뒤. `.cache/chat_measure_v2_20261104_2d85d865.json` |
| E 리뷰(agy) | 리뷰어 verdict pass, `validate_review_report.py` 계약 만족. 그러나 `aggregate_result_changed` 근거란에 지시한 확인 (3) "기관명 NULL 행이 total 에 포함되는가" 가 없고 일반 시험 36건 통과만 적었습니다. 코디네이터 Level 3 판정으로 **반려 유지**(3절). 재작업 리뷰 Intent 에는 NULL·U+FFFD 행 픽스처로 total 을 직접 비교하는 명령을 못박습니다 |

---

## 6. 운영 메모

| 항목 | 내용 |
| --- | --- |
| 리뷰어 `--model` 거부 | cmd 리뷰어를 taskctl `dispatch --model z-ai/glm-5.3-flash` 로 지정하면 빌더와 같은 공급자라 `ModelRoutingError` 로 거부됩니다. 런처 터미널은 glm 으로 띄우고 dispatch 에는 `--model` 을 빼야 기동됩니다 |
| cmd glm 정체 | `500 ... shared hosted model reached its limit of 384 concurrent requests` 에서 멈추고 `continue` 로도 풀리지 않았습니다. `orca_worker_watch.py` 는 이 상태를 차단으로 잡지 못합니다. 사용자가 먼저 보고했습니다. 감시기 차단 신호에 `Failed after 3 attempts`·`concurrent requests` 를 추가하는 작업이 필요합니다 |
| agy 리뷰어 | `orca_agy_launch.py --model gemini-3.8-flash-medium --role reviewer` 터미널 + `dispatch --launcher scripts/orca_agy_launch.py --agent antigravity --model gemini-3.8-flash-medium`. Capsule 은 실제 ID 와 Intent 이름 디렉터리 두 곳에 복사 |
| 보고 파일 누락 | cmd deepseek 빌더가 `worker_done` 만 보내고 `report_path` 파일을 쓰지 않는 일이 2회째입니다(11-03 C, 11-04 F). 회수 전에 파일 존재를 확인합니다 |
| zsh glob | `cp dir/*.json` 에서 일치 파일이 없으면 그 명령 전체가 실패해 같은 줄의 yaml 복사도 빠집니다 |
| Docker | 세션 종료 시 `docker compose stop` 으로 정지, 볼륨은 그대로 |
