# 세션 인수인계: 2026-09-27(밤) CI 게이트 D-16·D-14 구현과 물품 기록 갱신

> **작성일**: 2026-09-27
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `06e88b5a` (이 문서 병합 전)
> **Orca Run**: `run_01ed34ec96c1`
> **이어받은 문서**: [`session_20260927c_decision_items_wave.md`](session_20260927c_decision_items_wave.md)

---

## 1. 한 줄 요약

사용자 지시로 물품 모델 사이드카 지표를 갱신하고, CI 게이트 설계 중 D-16(scripts 개별 커버리지)과 D-14(단위 성능 게이트)를 구현해 병합했습니다. 그 과정에서 재시도 테스트의 격리 결함을 찾아 고쳤습니다. D-15 는 설계만 있고 미착수입니다.

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| 물품 기록 갱신 | `dc7271cd` | `data/model_metrics/quantum_leap_v25_pro.json` 을 현재 서빙 버전 `v_20260806_043408_749` 실측(2026-01-01 이후 3,000건, R2 0.419)으로 갱신. 이전 값은 승격 이전 모델(version 25.1, R2 -0.213) | 코디네이터 직접. `load_serving_metrics` 는 서빙 metadata 지표(R2 0.358)를 먼저 쓰고 사이드카는 metadata 지표가 없고 버전이 일치할 때만 쓰므로 승격 판단은 바뀌지 않는다 |
| D-16 `task_ff1ab5303090` | `8bcb92c7` | 조율 도구 6종과 무테스트 2종에 개별 커버리지 하한(78/84/74/83/83/80/98/96). CI 에 전역 판정과 분리된 별도 스텝 | 리뷰 pass, strict, CI 성공(전역 src 89.36% 유지) |
| 재시도 테스트 격리 `task_c70017fcfe4e` | `028d6cee` | `tests/test_api_collector_retry.py` 의 `sleep_calls` 가 전역 `asyncio.sleep` 을 바꿔 다른 테스트가 남긴 코루틴의 `sleep(0.1)` 46,055건이 기록에 섞이던 결함. `api_collector` 모듈의 `asyncio` 이름만 대리 객체로 바꾸고 격리 회귀 테스트 추가 | 리뷰 pass, strict, CI 성공 |
| D-14 `task_bfabe5520b68` | `06e88b5a` | `data/benchmarks/perf_unit_baseline.json`(OpenAPI 경로 49·오퍼레이션 56, 특징 키 97 집합 해시, Servc 특징 35, unservable 빈 목록, 홈 질의 상한 15), `tests/test_perf_unit_gate.py`, 레이턴시 규약 9장, CI ubuntu 전용 스텝(`SKIP_MODEL_LOAD: 'true'`) | 리뷰 pass. 재검증 `task_b78566cd2e89` 보고로 strict |

---

## 3. 드러난 사실과 판단

| 사실 | 판단·조치 |
| --- | --- |
| 오늘 G3·D-14 병합 전 전량 테스트의 "원인 불명 1~2건 실패" 는 재시도 테스트 격리 결함이었다 | 실패 목록을 `-rf` 로 남겨 특정했다. 부하 탓으로 추정했던 것은 틀렸다. `premerge_full_suite_gate.py` 가 실패 테스트 이름을 증거에 남기도록 개선 후보 |
| 격리 결함의 발단은 F1 Capsule 이 "asyncio.sleep 을 monkeypatch" 만 지시하고 기록 범위를 한정하지 않은 것 | Capsule 에 전역 치환 금지를 명시해야 한다 |
| D-14 빌더가 보고서 command 칸에 "(2회 연속)" 설명을 붙여 게이트 6 이 그 문자열을 실행하다 실패 | 재검증 Task 로 처리. 재검증 Capsule 에 "command 칸은 지정 문자열 그대로" 를 명시해 해소 |
| 코디네이터가 D-14 Capsule 에 `SKIP_MODEL_LOAD=1` 로 적었으나 코드는 `'true'` 만 인정 | 빌더가 발견해 `'true'` 로 적용. 사양에 환경변수 값을 적을 때 코드 확인 필요 |
| 재검증 워커가 또 heartbeat `--from` 에 다른 핸들을 써서 거부 | 터미널 정정으로 해소. 재검증 과제에서 두 번째 재발 |
| 사이드카 지표가 승격을 왜곡할 수 있다는 코디네이터 설명은 틀렸다 | 코드 확인 후 정정. 사이드카는 metadata 지표가 없을 때만 쓰인다 |

---

## 4. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합과 `06e88b5a` CI 확인 | 종료 직전 확인 결과는 5장 |
| 2 | Docker Desktop 기동 후 `docker compose up -d` | 종료 때 전부 내렸다 |
| 3 | 월요일 03:00·04:00·05:00 결과 확인 | 컴퓨터가 꺼져 있으면 건너뛴다. worker 기동 시 따라잡기 수집 1회 |
| 4 | D-15 착수 여부. 착수하면 단계 0(빈 DB 마이그레이션과 운영 기준선 일치 확인)부터 | `docs/analysis/ci_gate_designs_20260927.md` 3장 |
| 5 | 1-2 외장 디스크 백업(경로·주기) | 디스크 미연결로 보류 |
| 6 | `premerge_full_suite_gate.py` 실패 테스트 이름 기록 개선 | 3장 첫 행 |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 워커 워크트리 0건, 작업 브랜치 0건(로컬·원격) |
| Orca | Run `run_01ed34ec96c1` 워커 터미널 전부 회수, 잔류 세션 감사 통과, 상시 감시기 종료 |
| Docker | 사용자가 컴퓨터를 끄려고 요청해 Redis `SHUTDOWN NOSAVE`, 나머지 `docker compose stop`, Docker Desktop 종료(볼륨 보존) |
