# 세션 인수인계: 2026-09-28 인수인계 이행과 기동 따라잡기 확장

> **작성일**: 2026-09-28
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `c7b4ee84` (이 문서 병합 전)
> **Orca Run**: `run_0f28089a96b2`
> **이어받은 문서**: [`session_20260927d_ci_gates_and_thng_record.md`](session_20260927d_ci_gates_and_thng_record.md)

---

## 1. 한 줄 요약

직전 인수인계의 과제 중 D-15 스키마 서명 CI 와 premerge 실패 이름 기록을 구현해 병합했습니다. 컴퓨터가 꺼져 월요일 스케줄이 전부 누락된 것을 계기로, 기동 따라잡기를 주간 재학습·드리프트 감시·커버리지 감시까지 넓혔습니다. 그 과정에서 따라잡기 슬롯이 UTC 로 계산되던 결함을 찾아 고쳤습니다. 빌더는 cmd deepseek-v4.1-flash, 리뷰어는 kilo Space Bunny Alpha(OpenRouter, max) 입니다.

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| kilo 리뷰어 연동 | `155732b5`, `fa915dcd` | `scripts/orca_opencode_launch.py` 에 `--binary kilo`, `--variant`. kilo 대화형 TUI 는 `KILO_CONFIG_CONTENT` 로 model·variant 를 고정한 `orca-worker` 에이전트를 주입. 모델 풀 `kilo-space-bunny`(provider openrouter, 자동 배정 제외) | 코디네이터 직접. strict, CI 성공. 실측에서 세션 기록이 `variant: max` |
| K1 premerge 실패 이름 기록 | `ad635c2e` | 증거 JSON 에 `failed_tests`(최대 50, 절단 표시), 실패 메시지에 nodeid 10건. 추출은 pytest 요약 머리줄 뒤로 한정 | 리뷰 pass 였으나 체크리스트 답과 근거가 모순되어 코디네이터가 결함으로 뒤집고 직접 수정. 재검증 후 strict |
| K2 D-15 스키마 서명 CI | `5666f91c` | `verify_migration.py --signature-scope {full,managed}`, CI `g1-schema-signature` 잡(utf8mb4_unicode_ci 로 빈 DB 생성 후 alembic upgrade head, ORM 19 + alembic_version 대조) | 단계 0 을 코디네이터가 로컬 실측(20테이블 해시 일치). managed 반례(컬럼 삭제) 검출 확인. 리뷰 pass, 재검증 후 strict, CI 에서 새 잡 첫 실행 성공 |
| K3 주간 재학습 따라잡기 | `a01df8fc` | 로컬 타임존 슬롯 헬퍼(`previous_cron_slot`, `next_cron_slot`), 데이터 따라잡기 슬롯 UTC 결함 수정, 주간 재학습 따라잡기, `weekly_retrain_task` 안의 토큰 기반 공통 선점, 다음 슬롯 3시간 이내 양보 | 1차 리뷰 fail(cron 과 따라잡기 상호 배제 부재) 후 재작업, 재리뷰 pass, strict |
| source_commit 갱신 | `27595bcb` | K1~K3 병합으로 5커밋 초과해 main CI `lint-and-validate` 실패. 코디네이터 브랜치로 갱신 | CI 성공 |
| K4 드리프트·커버리지 따라잡기 | `c7b4ee84` | 드리프트(매일 04:00, `retrain_logs` 기준)와 커버리지(월 05:00, Redis 스케줄 기록 기준) 따라잡기, 두 원 태스크 공통 선점, 1시간 이내 양보, `_record_schedule(success_statuses=...)` | 1차 리뷰 fail(커버리지 정상 실행이 실패로 기록, 실패 실행을 처리됨으로 판정) 후 재작업, 재리뷰 pass, strict. source_commit 은 병합 커밋 안에서 갱신 |

---

## 3. 운영 조치와 실측

| 대상 | 결과 |
| --- | --- |
| 주간 재학습 수동 실행 | 사용자 지시로 `cron:weekly_retrain_task` 를 큐에 적재. 1,590초, 표본 926,704, 도전 모델 `v_20260928_005951_162` 는 `REJECT_CHALLENGER`. 서빙은 `v_20260915_133523_756` 유지. `retrain_logs` 에 `weekly_schedule` 첫 기록(id 17) |
| worker 재시작 후 따라잡기 | 데이터 `missed_schedule`(슬롯 02:00 KST 정확) 501초 성공, 이어서 주간 `weekly_retrain_up_to_date` 건너뜀, 드리프트 `missed_drift_monitor` 성공, 커버리지 `no_previous_result_coverage` 성공. 스케줄 상태 전부 `success: true` |
| 커버리지 경고 | Thng 2026-08-24 주 대형 매칭률 53.5%, 전년 65.0%(공고 454건). 원인 조사 미착수 |

---

## 4. 드러난 사실과 판단

| 사실 | 판단·조치 |
| --- | --- |
| 월요일 03·04·05시 작업이 컴퓨터 꺼짐으로 모두 누락되고 보충 장치가 없었다 | K3·K4 로 따라잡기 대상을 넓혔다 |
| 따라잡기 슬롯이 UTC 02:00 으로 계산되어 KST 02:00 누락을 놓쳤다 | `collected_at` 은 UTC, arq cron 은 로컬(TZ=Asia/Seoul)임을 코드로 확인하고 K3 에서 수정 |
| 빌더 브랜치에 코디네이터가 main 병합(K1·K2)이나 문서 커밋(K4)을 얹으면 게이트 6 이 건수·changed_files 불일치로 실패 | K1·K2 는 재검증 Task, K4 는 코디네이터 커밋을 빼고 병합 커밋 안에서 source_commit 갱신. 빌더에게 검증 전 main 병합을 지시하면 문제없다(K4 에서 확인) |
| 재검증 Task 에서 런처의 빌더 커밋 고지와 Capsule 커밋 금지가 충돌해 워커가 매번 질문 | 개선 후보(6장) |
| 한 세션에 병합이 5건을 넘으면 source_commit 초과로 main CI 가 깨진다 | 병합 5건마다, 또는 마지막 병합 커밋 안에서 갱신 |
| K1 리뷰어가 체크리스트에 no 로 답하고 근거에 결함 시나리오를 적었다 | 이후 리뷰 Capsule 에 "근거에 결함이 있으면 answer 는 yes" 를 명시 |
| 재작업 Capsule 쓰기 범위를 재작업 파일만으로 잡아 원 커밋 파일이 범위 초과로 떴다 | 재작업 Capsule 범위는 브랜치 전체 변경 파일로 잡는다 |

---

## 5. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합과 `c7b4ee84` CI 확인 | 종료 직전 확인 결과는 7장 |
| 2 | Thng 2026-08-24 주 매칭률 경고 원인 확인 | `uv run python scripts/result_match_rate_report.py` |
| 3 | K3 리뷰 이월 3건 | 주간 양보 상수 10800 리터럴, 카테고리 부분 실패 시 워터마크 전진, tz 인자 생략 호출 |
| 4 | 재검증 Task 에서 빌더 커밋 고지 제외 | `scripts/orca_worker_launch_common.py` 역할 고지 |
| 5 | 1-2 외장 디스크 백업 | 디스크 미연결로 보류 계속 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 워커 워크트리·작업 브랜치는 병합 후 정리. 이 문서 브랜치(`orca-kilo`)만 병합 후 정리 예정 |
| Orca | Run `run_0f28089a96b2` 워커 터미널 전부 회수 |
| Docker | 기동 유지(worker 상시 가동 원칙). app·worker 는 `c7b4ee84` 코드로 재시작됨 |

---

## 7. 종료 직전 확인

종료 직전 CI 와 정리 결과는 코디네이터가 이 문서 병합 직후 보고합니다.
