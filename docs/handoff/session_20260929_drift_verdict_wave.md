# 세션 인수인계: 2026-09-29 드리프트 판정 규칙 1차와 비숫자 차수 방어

> **작성일**: 2026-09-29
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `2a110b97`
> **Orca Run**: `run_b406a154bbad`
> **이어받은 문서**: [`session_20260928_catchup_wave.md`](session_20260928_catchup_wave.md)

---

## 1. 한 줄 요약

직전 인수인계 10장의 3번(드리프트 감시 오탐 제거 1차)과 W13 리뷰어 후속(비숫자 차수 방어)을 워커 2대로 병렬 구현해 병합했습니다. 빌더는 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어는 OpenCode `opencode/muse-spark-1.3-contributor-free` 입니다. 운영 데이터로 새 판정을 계산해 보니 1차 규칙만으로는 오탐이 해소되지 않고 한 주 보류될 뿐이라는 사실이 드러났습니다(4장).

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| D2 비숫자 차수 방어 | `ed1040c1` | `_is_later_cancelled` 는 공고 행 차수가 정수로 해석되지 않으면 False. `_ord_as_int` 규약은 유지. 경계 테스트 3건 | 리뷰 pass, strict, premerge 5,681 passed, CI 성공 |
| D1 드리프트 판정 규칙 1차 | `2a110b97` | 신규 `src/ml/drift_verdict.py`. 달력 4종과 `is_post_regime_shift` 는 PSI 를 계산하되 판정에서 제외(`excluded_from_verdict`, `excluded_drift_features`). 비제외 드리프트 2개 이상일 때만 창 드리프트(1개면 STABLE, `below_quorum`). 겹치지 않는 직전 창(`retrain_logs` 의 [now-14일-12시간, now-7일+12시간] 최근 행 `window_drift`)도 창 드리프트여야 DRIFT_DETECTED, 아니면 `DRIFT_PENDING` 으로 보류하고 알림 없음 | 리뷰 pass, strict, premerge 5,695 passed. worker 재시작으로 운영 반영 |

D1 작업 중 코디네이터 결정 두 건입니다.

| 질문 | 결정 |
| --- | --- |
| `tests/test_large_module_split.py` 가 `monitoring.py` 를 582줄로 막는다(구현 678줄) | 상한 테스트는 두고 판정 로직을 `src/ml/drift_verdict.py` 로 분리. `monitoring.py` 581줄 |
| 레거시 테스트의 SessionLocal 스텁 때문에 직전 창 조회가 실패한다 | 조회는 창 판정이 DRIFT_DETECTED 일 때만, 예외는 경고 후 None(보류, 알림 없음) |

---

## 3. 운영 조치

| 대상 | 결과 |
| --- | --- |
| Docker | 세션 시작 시 꺼져 있어 기동. 5개 서비스 정상 |
| worker 따라잡기 | 데이터 `missed_schedule` 실행, 주간 재학습 `weekly_retrain_up_to_date` 건너뜀, 드리프트 따라잡기 성공(09:55, 구 규칙) |
| worker 재시작 | D1 병합 후 재시작. 컨테이너에서 새 상수 import 확인 |
| 추적되지 않은 파일 | `data/benchmarks/probe_repeat_20260928_211532_r1~r5.json`(비정본 RAG 구간 측정 5회, 참조처 없음)을 사용자 승인으로 휴지통으로 이동 |

---

## 4. 드러난 사실: 1차 규칙은 오탐을 한 주 미룰 뿐이다

D1 병합 후 운영 worker 에서 기록·알림 없이 새 판정을 계산했습니다(평가 창 7일).

| 분류 | 표본 | 창 판정 | 비제외 드리프트 | 제외 드리프트 | 최종 |
| --- | --- | --- | --- | --- | --- |
| 공사 | 505 | DRIFT_DETECTED | 9 | 5 | DRIFT_PENDING |
| 용역 | 382 | DRIFT_DETECTED | 16 (두 집단 합) | 10 | DRIFT_PENDING |
| 물품 | 672 | DRIFT_DETECTED | 12 (두 집단 합) | 10 | DRIFT_PENDING |

| 사실 | 판단 |
| --- | --- |
| 달력·레짐 제외 후에도 비제외 드리프트가 9~16개로 정족수 2를 크게 넘는다 | W12 보고서 7절의 예측과 같다. 남는 것은 누적·확장 통계(`inst_*`, `repeat_*`)와 단주간 구성 차이다 |
| 이번 주는 직전 창 기록에 `window_drift` 가 없어 전부 보류된다 | 설계 의도. 다음 주(2026-10-06 이후) 창도 창 드리프트면 알림이 다시 나간다 |
| 실질적 오탐 제거에는 권고 3(누적 특징 시간 정렬)과 4(28일 이상 창) 가 필요하다 | 2차 과제. 기준선 재생성과 얽혀 합의가 필요하다 |

---

## 5. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋과 `2a110b97` CI 확인 | 종료 직전 확인 결과는 코디네이터 보고 |
| 2 | 드리프트 오탐 제거 2차 합의(사용자) | 4장. 2026-10-06 전후 알림 재발 전에 결정하는 것이 좋다. 선택지: 누적 특징(`inst_*`, `repeat_*`)을 판정 제외 목록에 추가(빠름, 감시 범위 축소), 28일 창 또는 다중 창(기준선 재생성 불필요 여부 확인 필요), 누적 특징 시간 정렬(기준선 재생성) |
| 3 | 취소 분모 제외 플래그 켤지 결정(사용자) | 비숫자 차수 방어는 이번에 병합됨. 켜려면 `.env` 에 `RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED=true` 후 worker 재시작 |
| 4 | 나라장터 화면 대조(사용자) | 직전 문서 10장 5번 그대로 |
| 5 | 용역 대형 경고 억제 적용 여부(사용자) | 직전 문서 10장 6번 그대로 |
| 6 | 2026-10-05 월요일 05:00 알림 확인과 늦은 도착 추세 비교 | 직전 문서 10장 7번 그대로. 같은 주 드리프트 로그의 `window_drift` 기록도 확인 |
| 7 | 1-2 외장 디스크 백업 | 디스크 미연결로 보류 계속 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 워커 워크트리 `orca-d1`, `orca-d2` 와 로컬·원격 작업 브랜치 정리 완료. 이 문서 브랜치만 병합 후 정리 |
| Orca | Run `run_b406a154bbad` 빌더 2대·리뷰어 2대 회수, 창 닫음. `orca_settled_session_audit.py` 잔류 없음 |
| Docker | 전 서비스 가동. worker 상시 가동 원칙대로 내리지 않음 |
