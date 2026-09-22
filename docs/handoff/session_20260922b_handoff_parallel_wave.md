# 세션 인수인계: 2026-09-22 인수인계 잔여 과업 병렬 처리, D2·D8·Meili 실측, 용역 A값 판정

> **작성일**: 2026-09-22
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `7d1c66d0`
> **Orca Run**: `run_859e195073ba` (빌더 3, 조사 2, 리뷰 3 Task 전부 완료, 워커 터미널·워크트리 전부 회수)
> **이어받은 문서**: [`session_20260922_audit_residual_wave.md`](session_20260922_audit_residual_wave.md)

---

## 1. 한 줄 요약

이전 인수인계 5장의 잔여 과업을 워커로 병렬 처리해 병합 6건(되돌림 1건 포함)을 반영했고, D2 따라잡기 판정과 Meili 전체 재구축 시간을 실측했습니다. D8(홈 최근 공고 첫 질의 1일 윈도)은 Frgcpt 회귀로 사용자 결정에 따라 되돌렸습니다. **용역 적격심사 가격점수에는 A값이 들어가지 않는다는 사실을 1차 출처로 확정했고, 저장소의 A값 반영 하한은 공사 산식을 용역에 잘못 적용한 것입니다.**

---

## 2. 이번 세션 병합 (first-parent)

| 병합 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `28385ec6` | X3 공고 파티션 키 NOT NULL 전제를 ORM 과 G1 기준선 양쪽에서 고정하는 테스트 | 리뷰 pass, Level 1 11/11, 전량 5,329, CI 성공 |
| `169ee4d1` | D3 복구 drill `database_import` 를 테이블별 적재 시간(`database_import_breakdown`)으로 기록 | 리뷰 pass, Level 1 11/11, 전량 5,331. **CI 실패**(4장) |
| `393aee5c` | D8 홈 최근 공고 선별 첫 질의에 1일 윈도 조건 | 리뷰 pass, Level 1 11/11, 전량 5,329. `7d1c66d0` 에서 되돌림 |
| `a9d4377b` | pytest 경고 예산 상한 5 에서 0 (사용자 결정) | 전량 5,336, actionlint |
| `047e751f` | D3 CI 실패 수정(mypy 2건, Windows 타이머 단언)과 source_commit 갱신 | 전량 5,344, CI 성공 |
| `7d1c66d0` | D8 되돌림 | 전량 5,351, mypy src 통과 |

워커 모델: 빌더 Command Code `deepseek/deepseek-v4.1-flash`(X3 effort default, D3·D8 effort high), 리뷰어와 조사 OpenCode `opencode/muse-spark-1.3-contributor-free`. 전부 `orca_taskctl.py dispatch --terminal` 터미널 부착 경로이며 **비감독 경로**입니다. 경고 예산, 감사 로그 정리, D3 CI 수정, D8 되돌림은 코디네이터가 직접 했습니다.

---

## 3. 측정 결과

측정 조건: `main` `047e751f`, Docker 는 `db`·`redis` 만(Meili 측정은 임시 컨테이너 추가), 버퍼풀 2GB, 정규화 부하 16.2~18.3%. 원시 결과는 `data/benchmarks/measure_20260922/` 입니다.

### 3.1 D2 따라잡기 판정 (이전 인수인계 5장 2번)

| 조건 | A 최악 회차 최대 | B 최악 회차 최대 |
| --- | ---: | ---: |
| `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true` | 0.93ms | 0.20ms |
| `false` | 0.19ms | 0.19ms |

분기는 `threshold_not_exceeded`(마지막 수집 후 7.17시간, 기준 24시간)였고 쿨다운 키 `bidbox:schedule:catchup_cooldown` 은 측정 전후 모두 없었습니다. **판정 함수만 돌며 실제 수집은 시작되지 않음을 확인했습니다.** 차이는 1ms 탐침 해상도 이하라 효과는 미미로 판정합니다. 이 과업은 종결입니다.

### 3.2 D8 재측정과 되돌림

| 시나리오 | 새 구현 SQL / 최악 중앙값 | legacy SQL / 최악 중앙값 |
| --- | ---: | ---: |
| all | 1 / 2.23ms | 1 / 2.23ms |
| Cnstwk | 1 / 2.62ms | 1 / 2.55ms |
| Servc | 1 / 2.19ms | 1 / 2.18ms |
| Thng | 1 / 2.34ms | 1 / 2.26ms |
| Frgcpt | **2 / 7.68ms** | 1 / 1.17ms |

카테고리 네 곳의 약 1ms 잔여는 사라졌으나, Frgcpt 는 1일 윈도가 희소해 윈도 질의 뒤 카테고리 필터 전역 200행 질의로 넘어가며 직전 구현 1.99ms 에서 7.68ms 로 회귀했습니다. DB 기동 23초 뒤의 콜드 측정이라 전날 수치와 절대값 비교는 어렵지만, 같은 회차 안의 교차 측정이라 회귀는 확정입니다. **D8 잔여 약 1ms 는 설계 비용으로 종결합니다.** 다시 줄이려면 윈도 질의가 비었을 때의 후속 질의 비용을 희소 카테고리에서 먼저 재야 합니다.

### 3.3 Meili 전체 재구축 (이전 인수인계 5장 4번)

| 항목 | 값 |
| --- | --- |
| 클라이언트 적재 | 581.9초 (공고 4,879,588건, 낙찰 3,439,172건) |
| 서버 색인 완료 대기 | 257.4초 |
| 전체 | **839.3초** |
| 문서 수 / 실패 작업 | 8,318,760 / 0 |
| 색인 크기 / 클라이언트 최대 RSS | 21.8GB / 약 185MB |

별도 포트(7701)의 임시 `getmeili/meilisearch:v1.14` 컨테이너와 빈 전용 볼륨에 `scripts/sync_search_index.py` 전체 동기화로 적재했고 운영 색인은 건드리지 않았습니다. 기본 `MEILI_TIMEOUT_SECONDS=5` 는 배치 실패 위험이 있어 **30초로 측정했습니다.** 실제 복구에서도 같은 설정이 필요한지 확인해야 합니다. RTO 는 drill 약 1,439초에 재색인 839초를 더해 **약 2,278초(38분)** 입니다. `docs/ops/rpo_rto_policy.md` 3장 단계표에는 아직 반영하지 않았습니다.

---

## 4. D3 CI 실패의 원인

Level 1 게이트 3 은 `scripts/*.py` 변경에 `backend_mypy` 를 요구하지 않아 D3 게이트를 `--verify` 없이 11/11 로 통과시켰습니다. 그러나 CI 의 `uv run mypy src/` 는 src 가 import 하는 `scripts/backup_recovery_core.py` 까지 따라 들어가 타입 오류 2건을 잡았습니다. Windows 러너는 모킹된 import 구간 경과 시간이 타이머 해상도로 0.0 이 되어 새 테스트의 `> 0` 단언이 실패했습니다. 중간 병합 `393aee5c`, `a9d4377b` 의 CI 실패도 같은 원인임을 로그로 확인했습니다. **scripts 만 바꾼 Task 도 게이트에 `--verify "uv run mypy src"` 를 붙이십시오.**

`uv run mypy scripts/backup_recovery_core.py scripts/backup_recovery.py` 는 `scripts/backup_recovery_drill.py:136` 의 기존 오류 1건을 보고합니다. CI 대상 밖이며 이번 세션에서 고치지 않았습니다.

---

## 5. 용역 적격심사 A값 판정

외부 설계서(`BIDBOX_적격심사_정량평가_입찰가격_보완_설계서.md`, grok-4.7-high 작성) 검토 중 조사 Task A1 을 돌렸습니다. 보고서는 `.orca/capsules/task_72ed37b56c35/findings.md`(주 저장소, gitignore) 입니다.

| 사실 | 근거 |
| --- | --- |
| 일반용역·기술용역·지자체 용역 적격심사 입찰가격 평점은 `입찰가격 / 예정가격` 이며 A값을 빼지 않는다 | 조달청 일반용역 적격심사 세부기준(국가법령정보센터, 조달청공고 제2026-15호), 조달청 공고 제2026-260호 보도(분자 88 에서 90), 일반용역 별표 원문 미러. 코디네이터가 두 곳을 직접 대조 |
| `(입찰가격 - A) / (예정가격 - A)` 와 A값 정의는 공사 별표 전용이다 | 공사 적격심사 별표 원문 |
| 운영 DB 에는 A값이 수집되지 않는다 | 2026-06-01 이후 최근 20만 건에서 `a_value`·`aValue`·`nonBidCost`·`non_bid_cost` 키 0건(공사 포함), 공사 raw_data 키 143개에 A값 구성 항목 없음 |

따라서 `calculate_price_score` 의 A값 무차감은 맞고, 용역 공고에 `(예정가격 - A) × 하한율 + A` 를 적용하는 `calculate_min_bid_amount` 운용과 `min_bid_amount_with_a` 응답 필드, 선행 설계 `docs/design/servc_qualification_evaluation_design_20260909.md:165` 의 "A값 반영 하한을 빠뜨리면 탈락" 문장은 용역에 맞지 않습니다. 운영 데이터에 A값이 없어 사용자에게 드러난 적은 없고, 테스트 고정값(`tests/test_evaluations_api.py` 의 459,980,000원)에만 남아 있습니다.

외부 설계서의 판정: 점수와 보완 금액에 A값을 넣지 않는 핵심 결정과 반올림 격자 검증은 맞습니다. 코디네이터가 처음에 "낙찰하한 미만 권고" 로 지적한 것은 틀렸으며 정정했습니다. A값 하한 금액을 "낙찰하한 표시" 로 병기하는 부분은 빼야 합니다. 예정가격 없음 경로를 차단에서 성공 응답으로 바꾸는 것은 별도 결정으로 분리를 권했습니다.

---

## 6. 다음 세션 할 일

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | `7d1c66d0` 과 이 문서 병합의 CI 확인 | 세션 종료 시점에 실행 중일 수 있다 |
| 2 | 용역 A값 경로 정리 결정 | 용역 규칙에서 A값 반영 하한과 `min_bid_amount_with_a` 를 끌지, 공사 확장용으로 남길지. 테스트 459,980,000원 기대값과 선행 설계 165행 정정이 함께 따른다 |
| 3 | 외부 가격 보완 설계서 재작성 여부 | 5장 판정을 반영해 A값 병기 절을 빼고, 예정가격 없음 경로 변경은 분리 |
| 4 | RTO 단계표 갱신 | 재색인 839초(`MEILI_TIMEOUT_SECONDS=30` 전제)를 `docs/ops/rpo_rto_policy.md` 3장에 반영. 운영 런북은 독립 리뷰 필수 |
| 5 | 다음 drill 에서 DB import 1.7배 원인 판정 | D3 계측으로 `database_import_breakdown` 이 보고서에 남는다 |
| 6 | OP-3 주간 재학습 | worker 는 A안대로 정지 상태 유지 |

---

## 7. 이번 세션에서 드러난 사실

| 사실 | 조치 |
| --- | --- |
| `orca_taskctl.py create --task-id` 는 무시되고 ID 가 새로 발급된다 | scope 에 Task ID 경로가 들어가면 create 뒤 Intent 를 고치고 `expand` 로 재확장 |
| 동시 쓰기 상한 검사가 `.orca/` 에만 쓰는 조사 워커도 쓰기로 센다 | 우회하지 않고 선행 워커 완료 뒤 투입 |
| `check --wait --types` 가 heartbeat 를 섞어 돌려준다 | heartbeat 는 자동 ack 하고 실질 메시지에서만 멈추는 대기 스크립트로 처리 |
| `orca worktree rm` 은 브랜치까지 지운다 | 지우기 전 `git log main..<branch>` 가 0 인지 확인 |
| 커밋 타입에 `revert` 는 없다 | 되돌림은 `refactor:` 로 |
| 사용자가 워크트리 두 개를 "회수 안 된 하위 세션" 으로 지적했다 | 병합 전 증거 기록이 워크트리 안에서 돌아야 해서 남긴 것이었다. 병합 즉시 제거 |
| 코디네이터가 저장소 코드와 선행 문서를 근거로 A값 결함을 단정했다가 1차 출처 조사로 뒤집혔다 | 도메인 산식 판정은 저장소가 아니라 원문 기준으로 한다 |

---

## 8. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 작업 브랜치·워커 워크트리 0건 |
| Orca | Run `run_859e195073ba` Task 전부 완료, 워커 터미널 전부 회수, 배달 큐 비움 |
| Docker | `db`·`redis` 기동 중. Meili 측정용 임시 컨테이너와 볼륨은 삭제 |
| 감사 로그 | `data/promotion_audit.log` 를 실제 승격 1줄만 남기고 정리. 원본 9,245줄은 `data/backups/promotion_audit_20260922_before_cleanup.log`(gitignore) |
