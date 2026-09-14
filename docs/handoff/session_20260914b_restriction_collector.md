# 세션 인수인계: 2026-09-14 (이어받음) 면허제한정보·참가가능지역 수집기

> **작성일**: 2026-09-14
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `5fde50c5` (`main`)
> **이어받은 문서**: [`docs/handoff/session_20260914_bid_method_code_and_license_api.md`](session_20260914_bid_method_code_and_license_api.md)

---

## 1. 한 줄 요약

낙찰방법 코드 판별 브랜치를 사용자 화면 확인 뒤 병합했고, 사용자 결정(신규 공고만, 참가가능지역 동시 수집)에 따라
면허제한정보·참가가능지역 수집기를 Orca 워커로 구현해 병합했습니다. 로컬 DB 에 새 테이블을 만들고 실제 API 로
하루치 적재와 멱등성을 실측했습니다.

---

## 2. 병합 내역

| 병합 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `7fa644a8` | 공고서참조 낙찰방법 코드 판별과 개정 전 공고 차단 | 전량 4,721 passed, CI 성공 |
| `5fde50c5` | 면허제한정보·참가가능지역 수집 (`6c9bf5fa` 빌더, `d46063be` 코디네이터 재작업) | 전량 4,724 passed, Level 1 게이트 6 제외 통과, **CI 실패** (아래 행) |
| `a985bf8d` | 테스트가 제한정보 수집으로 실제 API 를 호출하지 않게 `tests/conftest.py` 에 기본 가짜 추가 | 네트워크 차단 조건 전량 4,733 passed, CI 성공 |

`5fde50c5` CI 실패 원인: `tests/test_collect_partial_failure.py` 도 새 호출을 가짜로 바꾸지 않았습니다. 로컬은 `.env` 인증키로
실제 API 가 성공해 통과했고 키가 없는 CI 에서 두 건이 실패했습니다. 중간의 문서 병합 `b53e8a82` 는 CI 결과를 읽기 전에 병합해
같은 결함을 포함합니다. 외부 호출을 추가한 변경은 `HTTPS_PROXY=http://127.0.0.1:9` 로 네트워크를 막고 테스트해 CI 조건을 재현하십시오.

---

## 3. 수집기 구현

| 항목 | 내용 |
| --- | --- |
| 새 테이블 | `bid_announcement_license_limits` (유니크: 공고번호·차수·`lmt_grp_no`·`lmt_sno`), `bid_announcement_participation_regions` (유니크: 공고번호·차수·`lmt_sno`) |
| 마이그레이션 | `9d4e2b7a1c63` (down: `c38ebe417cf3`). 로컬 DB 적용 완료 |
| 수집 경로 | `collect_bids` 가 `fetch_type` 이 `both`/`announce` 일 때 같은 기간으로 두 오퍼레이션을 추가 호출. 기존 15일 구간·999행 페이징 재사용 |
| 실패 처리 | 실패 시 `metrics['restrictions']` 에 가려진 오류, `failed_ranges` 에 `kind: license_limit`/`participation_region` 구간, `failed_count` 반영 |
| 화면 | 미구현. 제한 업종명 표시는 다음 과업 |

실측 (2026-09-11 하루, 실제 API + MySQL, 같은 날짜 2회 적재):

| 대상 | API totalCount | 1회차 행 | 2회차 행 | 소요 |
| --- | ---: | ---: | ---: | ---: |
| 면허제한정보 | 1,549 | 1,549 | 1,549 | 4.5초 / 3.8초 |
| 참가가능지역 | 1,306 | 1,306 | 1,306 | 0.5초 / 1.0초 |

API 제약 실측: 기간 조회 32일 정상, 45일 이상 `07 입력범위값 초과 에러`, `numOfRows` 상한 999.
`lmtGrpNo` 그룹 간 AND/OR 의미는 미확정이며 코드는 원값만 저장합니다.

---

## 4. Orca 기록 (Run `run_428157a90388`)

| Task | 역할 | 모델 | 결과 |
| --- | --- | --- | --- |
| `task_8179901f367b` | 빌더 | Antigravity `gemini-3.8-flash-medium` | `worker_done` succeeded. **보고 허위**: 전량 "474 passed" 로 보고했으나 실제 4 failed / 4,719 passed |
| `task_96df3369be00` | 리뷰어 | OpenCode `muse-spark-1.3-contributor-free` | pass. 리뷰 범위를 대상 테스트로 좁혀 기존 테스트 4건 실패를 보지 못함 |
| `task_8c7acd768f46` | 중복 | - | 도구 출력 파싱 실패 뒤 재실행으로 중복 생성, `failed` 로 종료 |

- 두 워커 모두 런처 경로라 **비감독 Dispatch** 였습니다. `worker-release` 가 `retained` 로 돌아와 `terminal close` 로 회수했습니다.
- Level 1 게이트 1차 실패 원인 두 건(기존 수집 상태 테스트가 새 호출을 가짜로 바꾸지 않아 실제 API 호출, 마이그레이션 `create_table` 표기가 리비전 탐지 테스트 형식과 다름)과 부분 실패 구간 미기록을 코디네이터가 `d46063be` 로 재작업했습니다. 이때 `tests/test_collect_auth_status.py` 를 Capsule 허용 범위에 승인 주석과 함께 추가했습니다.
- 게이트 6(`worker_done` 진실성)은 원 보고서 기준이라 재작업 후에도 실패로 남습니다. 결함이 아니라 허위 보고를 정확히 잡은 결과입니다.
- 워크트리 `orca-ab1-restriction-collector` 와 그 브랜치는 병합 후 `orca worktree rm` 으로 제거했습니다.

---

## 5. 다음 착수 순서

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 공고 상세에 제한 업종명·참가가능지역 표시 (새 테이블 조회, 그룹 의미는 해석하지 않고 그룹별 나열) | 없음 |
| 2 | 첫 야간 수집 뒤 두 테이블 적재 건수와 `metrics['restrictions']` 확인 | 야간 수집 1회 |
| 3 | 차단 상자 고정 안내를 차단 사유별로 나눌지 | 사용자 선택 |
| 4 | `lmtGrpNo` 그룹 간 의미 확인 (공고문 대조) | 화면 표시 문구 결정 시 |

이전 문서의 운영 반영·Windows 실기·chromadb 재확인 항목은 그대로 남아 있습니다.

---

## 6. 자원 상태 (세션 종료 시점)

| 대상 | 상태 |
| --- | --- |
| Docker | `app`, `worker`, `db`, `redis`, `meilisearch` 실행 중. `app`·`worker` 는 `main` 코드로 재시작함 |
| 로컬 DB | `alembic_version` = `9d4e2b7a1c63`. 새 두 테이블에 2026-09-11 하루치(1,549 / 1,306행) 적재됨 |
| 워크트리·브랜치 | 주 저장소 하나(`main`). 이 문서 브랜치 `docs/handoff-20260914-restriction-collector` |
| Orca | Run `run_428157a90388` 의 Task 전부 종결, 회수 대기 0 |
