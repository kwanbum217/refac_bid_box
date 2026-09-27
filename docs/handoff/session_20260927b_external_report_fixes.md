# 세션 인수인계: 2026-09-27(후반) 외부 분석 보고서 대조와 수정 웨이브

> **작성일**: 2026-09-27
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `83ba3b06` (이 문서 병합 전)
> **Orca Run**: `run_01ed34ec96c1`
> **이어받은 문서**: [`session_20260927_result_gap_monitors_and_query_quota.md`](session_20260927_result_gap_monitors_and_query_quota.md)

---

## 1. 한 줄 요약

외부 분석 보고서 30건을 대조했습니다(판정표: [`external_report_audit_20260927.md`](../analysis/external_report_audit_20260927.md)). P2·P3 18건은 조사 워커 3대가 확인했고, 작고 결정이 필요 없는 5건을 빌더로 고쳐 병합했습니다. 워커 배정은 빌더·조사 cmd GLM-5.3 Flash, 리뷰어 OpenCode Muse Spark 1.3 입니다.

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| F3 `task_86ead72dfcb1` D-17 | `8fce6da2` | `tests/test_predictor_v25_helper.py`, 대상 모듈 커버리지 16.67% → 100% | 리뷰 pass, strict |
| F2 `task_bb7291bd61f3` D-12 D4 | `4af82bf9` | 수집 무데이터 검사 `COUNT` → `SELECT id LIMIT 1`, 판정 `is None` | 리뷰 pass, strict |
| F1 `task_4262aa2a6715` D-18 | `da3b804b` | `tests/test_api_collector_retry.py` 14건, 재시도 본문 전 행 실행 | 리뷰 pass. 재검증 `task_7b2e195e8940` 보고로 strict |
| F4 `task_bf1bc77ce5ab` D-26·D-28 | `3bc278c7` | 분석 색인 누락 5건 추가·건수 정정, 사유 없는 `nosec B105` 7건에 사유 | 리뷰 pass. 재검증 `task_a1378fa0fbe0` 보고로 strict |
| F5 `task_42dfcc876b9b` D-29 | `83ba3b06` | `.jscpd.json` 경로 중복 제거, `Makefile` 설정 파일 사용, CI `lint-and-validate` 에 `jscpd@5.3.2` 단계 | 리뷰 pass. 재검증 `task_b5ea99da3af6` 보고로 strict. 중복률 1.59% |
| 운영 반영 | (운영 조작) | worker 재시작(F2 반영) | 20개 함수로 정상 기동 |

---

## 3. 드러난 사실과 판단

| 사실 | 판단·조치 |
| --- | --- |
| 전량 테스트가 동시에 여러 벌 돌면 `tests/e2e` 의 Chromium 5초 판정이 실패해 e2e 30건이 조용히 skip 된다 | 이 세션에서 게이트 6 을 세 번(R4, F4, F5) 막았다. 보고서는 고치지 않고 재검증 Task 로 처리했다. 근본 수정(판정 제한 시간, 또는 skip 대신 실패) 필요 |
| F1 Capsule 의 단일 파일 `--cov` 검증 명령이 전역 `fail_under=80` 때문에 테스트가 전부 통과해도 종료 코드 1 | Capsule 작성 결함. 단일 파일 커버리지 명령에는 `--cov-fail-under=0` 을 붙인다 |
| 연속 병합 5건으로 `source_commit` 이 6커밋 뒤처져 `validate_agent_rules` 1건 실패 | 코디네이터 병합 스크립트가 이 실패에서 멈추지 않고 `83ba3b06` 을 푸시했다. 이 문서 병합에서 `source_commit` 을 갱신해 해소한다. 연속 병합 중에는 5건마다 갱신할 것 |
| F4 재검증 워커가 heartbeat `--from` 에 코디네이터 핸들을 넣어 `sender_not_assignee` 로 거부 | 터미널로 정정 지시 후 정상. preamble 의 자기 핸들을 쓰지 않은 워커 실수 |
| 빌더가 완료한 뒤 코디네이터가 수신함을 비우기 전에 다음 Dispatch 를 하면 잔류 세션 감사가 거부 | 병렬 운용에서 두 번 발생. Dispatch 직전에 `check` 로 수신함을 먼저 비운다 |
| 조사 워커 D-28 판정의 "nosec 제거" 제안 | bandit `--ignore-nosec` 로 8건 모두 탐지됨을 확인해 기각. 워커 수정 제안은 도구로 재확인한다 |

---

## 4. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합의 CI 확인. `83ba3b06` CI 는 `source_commit` 때문에 `lint-and-validate` 가 실패할 수 있다 | 이 병합으로 해소 |
| 2 | e2e Chromium 판정 부하 민감성 수정 | 3장 첫 행 |
| 3 | 결정 대기: D-11 물품 모델, D-13 `DEFAULT_INST_RATE`, D-21 gitleaks, D-6 오프사이트 백업 | 판정표 참조 |
| 4 | 설계 필요: D-14 성능 회귀 CI, D-15 스키마 서명 CI, D-16 `scripts/` 커버리지, D-12 D5 스냅샷 commit 배치 | M 규모 |
| 5 | 이전 인수인계의 월요일 03:00·04:00·05:00 결과 확인 | 그대로 |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 워커 워크트리 6개(`orca-audit`, `orca-f1`~`f5`) 제거. 원격 작업 브랜치는 남아 있다 |
| Orca | Run `run_01ed34ec96c1` 워커 터미널 전부 회수, 잔류 세션 감사 통과 |
| Docker | 전 컨테이너 가동. worker 16:08 재시작 |
