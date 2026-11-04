# 핸드오프 인수인계 - 2026-11-04 세션

> **작성일**: 2026-11-04
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_5878b718b767`
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `2d85d865` 입니다. 이 문서는 브랜치 `kwanbum217/close-20261104` 에서 F 보고서와 함께 묶어 병합합니다.
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 이 브랜치에서 병합 직전 `main` 으로 갱신했습니다.
> **종료 사유**: 사용자 지시(컴퓨터 종료). 워커 0대, Docker 전부 정지.
> **갱신**: 2026-11-05. 첫 종료(`8576446e`) 뒤 사용자 지시로 재개해 E 재작업과 T5 를 병합했습니다. 9절이 재개 이후 기록이며, 0절은 재개 후 기준으로 바꿨습니다.

---

## 0. 다음 세션이 바로 할 일

1. **`v2_rbd_02` 창 수정(1순위).** "유찰된 공사 공고 최근 5건" 이 최근 7일 공고일 창 때문에 3건만 답합니다(9.5절). `outcome` 이 있는 목록 질의는 "최근 N건" 창을 30일로 넓히거나 개찰일(`bid_openg_results.openg_dt`) 기준으로 정렬하도록 빌더 Task 를 냅니다. 어느 쪽인지는 사용자에게 먼저 묻습니다. 데이터 정확성 결함은 아닙니다(답한 건은 모두 유찰).
2. E·T5 는 병합을 마쳤습니다(9절).
3. 이 문서의 병합 커밋 CI 를 다음 병합 전에 `gh run list --branch main --limit 3` 으로 확인합니다.
4. 후속 과제 후보입니다. 착수 전에 사용자에게 우선순위를 받습니다.
   - 설계 8장 T6: 운영 문서와 `CURRENT_STATE` 에 유찰 수집 상태 반영, 수집 지표 대시보드.
   - `orca_worker_watch.py` 차단 신호에 cmd 공급자 500(`Failed after 3 attempts`, `concurrent requests`)을 추가합니다(6절).
   - 유찰 소급은 1년분만 했습니다. 3년 소급 여부는 사용자 결정 사항입니다.

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

---

## 9. 재개 이후 (2026-11-04 밤 ~ 11-05)

### 9.1 main 에 넣은 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `6fa75923` | E 재작업. 낙찰방법 질의의 최근 30일 기본 창과 2024-01-01 SQL 하한. 단일 집계는 걷어내 집계 경로는 main 과 같음. 빌더 `f89c25b6` + 재작업 `e8dab6a5` | agy 리뷰 pass(NULL·U+FFFD 회귀 시험 `test_award_method_announcement_total_counts_unresolved_institution_rows` 확인), strict 11/11, 전량 10,099 passed |
| `62ce2d0b` | T5. 유찰 가드 해제, 계획 계층 `outcome`, 최종 차수 조건 `_final_round_void_condition`, 유찰 정의 질문 분리 `is_void_definition_query`, 측정기 `announcement_filtered` 의 `outcome` 판정. 빌더 `ad222810` + 재작업 `54168bfb` | agy 리뷰 pass(1차 fail), strict 11/11, 전량 10,100 passed |
| `773d10bb` | `v2_rbd_02` 정답을 최종 차수 유찰 목록 판정으로 변경(코디네이터 직접, `1d60988d`) | strict pass, 전량 10,109 passed |

조건 1 기준선은 사용자 결정으로 **취소공고 제외 75%** 입니다. 2026-11-04 측정값 81.4% 로 통과했습니다.

### 9.2 반려와 원인

| Task | 반려 사유 | 원인 |
| --- | --- | --- |
| T5 1차 | 정의 질문 "유찰 건수가 뭐야", "유찰 건수 뜻" 이 정형 경로로 감 | `planner_interpreter.py` 의 유찰+건수 분기가 정의 의도를 거르지 않음 |
| T5 1차 | 전량 시험 1 failed 를 10,096 passed 로 보고 | `tests/test_chat_gold_measurer_split.py`. 한 브랜치에서 정답 JSON 과 측정기를 함께 바꾸면 실패한다. **코디네이터 사양 실수**로, 정답 변경은 별도 브랜치로 분리했다 |

### 9.3 Orca 기록

| Task | 상태 | 비고 |
| --- | --- | --- |
| `task_ecc6fe49a38d` E 재작업 | completed | cmd deepseek high |
| `task_20587e496de1` E 재작업 리뷰 | completed | agy `gemini-3.8-flash-medium`, pass |
| `task_2e61edc601c4` T5 | completed | cmd deepseek max. 리뷰 fail 로 rework |
| `task_b6772291113e` T5 리뷰 | completed | agy `gemini-3.8-flash-high`, fail |
| `task_5e852bcb6283` T5 재작업 | completed | cmd deepseek max |
| `task_aa5ff8ad55fe` T5 재작업 리뷰 | completed | agy `gemini-3.8-flash-high`, pass |

`task_cfe166b8f064`(E 1차 리뷰)는 cmd glm 정체로 `failed` 처리했다가 `ready` 로 되돌려 agy 로 완료했습니다. agy pass 였지만 NULL 행 확인이 근거에 없어 코디네이터가 반려를 유지했습니다.

### 9.4 운영 메모 추가

| 항목 | 내용 |
| --- | --- |
| agy 기동 escalation 오탐 | agy 리뷰어를 띄울 때마다 기동 직후 `Signing in...` 화면에서 Orca 가 "Worker is waiting on a prompt" escalation 을 보냈습니다(3회). 매번 수십 초 뒤 스스로 진행했습니다. 화면을 한 번 읽어 진행 중이면 무시합니다 |
| rework Capsule 의 objective | `orca_taskctl.py rework` 는 원래 Intent 의 objective 를 그대로 둡니다. 재작업이 원래 목표를 뒤집으면(E: 단일 집계 제거) 워커 터미널에 정정 지시를 보내야 합니다 |
| `git merge -F -` | 지원되지 않아 병합이 실행되지 않습니다. `-m` 두 번으로 씁니다 |
| `orca worktree create` | `--base-branch main` 을 명시하면 현재 main 기준으로 만들어집니다 |
| 정답·측정기 분리 | 챗봇 측정 기대값을 바꾸는 Task 는 측정기 변경과 다른 브랜치로 나눕니다. 시험 파일은 분리 규칙 대상이 아닙니다 |

### 9.5 측정

| 측정 | 결과 |
| --- | --- |
| v2 점검 세트(`773d10bb`, 앱 `62ce2d0b` 기동·`rag:*` 비움) | **19/20**. `.cache/chat_measure_v2_20261105_773d10bb.json`. 실패는 `v2_rbd_02` 하나(data_mismatch). 봇이 답한 3건(R26BK01797417, R26BK01797857, R26BK01800316)은 모두 최종 차수 유찰로 검증됨. 원인은 "최근 5건" 에 계획이 최근 7일 공고일 창(`date_from` 2026-10-30)을 거는데, 유찰은 개찰 뒤에야 생겨 7일 안에 3건뿐인 것. 측정 기준은 30일 창 79건 |
