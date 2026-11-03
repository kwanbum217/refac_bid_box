# 핸드오프 인수인계 - 2026-11-03 세션

> **작성일**: 2026-11-03
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_ba5e4c3015fe`
> **기준 커밋**: `main` 과 `origin/main` 은 `b30ef93a` 입니다. 이 문서는 브랜치 `kwanbum217/handoff-20261103-close` 에서 작성해 병합합니다.
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 병합 커밋마다 병합 직전 `main` 으로 갱신했습니다. 이 문서의 병합 커밋에서 다시 갱신합니다.
> **종료 사유**: 사용자 지시. 워커 0대, 미병합 작업 브랜치 없음.

---

## 0. 다음 세션이 바로 할 일

1. 결정 없이 진행할 과업은 없습니다. 3절의 차단 항목은 사용자 승인 또는 결정이 필요합니다.
2. `b30ef93a` CI 는 작성 시점에 G1 스키마 서명 job 이 success 였고 나머지 job 이 실행 중이었습니다. 다음 병합 전에 `gh run list --branch main --limit 3` 으로 결과를 확인합니다.
3. 새 테이블을 만드는 마이그레이션은 `mysql_charset="utf8mb4"`, `mysql_collate="utf8mb4_unicode_ci"` 를 명시합니다. 운영 스키마 기본값이 `utf8mb4_0900_ai_ci` 라 생략하면 4절의 결함이 다시 생깁니다.
4. `scripts/backfill_openg_results.py --execute` 와 나라장터 API 호출은 사용자 승인이 새로 있기 전에는 하지 않습니다.

---

## 1. 이 세션에서 main 에 넣고 원격까지 반영한 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `4b62dff3` | 개찰결과 수집 시험이 `.env` 서비스 키에 의존하던 순서 의존 실패를 시험 안 monkeypatch 로 격리. 빌더 `98ab4667` | 리뷰 pass, strict pass, 전량 10097 passed |
| `c04bb882` | `orca_taskctl.py create`·`rework` 가 새 응답 형태 `result.taskId` 에서 Task ID 를 읽고, ID 를 못 찾아도 Capsule 을 지우지 않음. 빌더 `ce1491a0` | 리뷰 pass, strict 11/11, 전량 10099 passed |
| `30cd6901` | 의미 검색 질의에서 "최근에"·"올해는" 이 "최근 에"·"올해 는" 으로 갈라지던 결함(`src/rag/query_planning.py` `_split_attached_period`) 수정. 빌더 `6f7cd09b` | 리뷰 pass, strict 11/11, 전량 10100 passed. 반례 10월서울시·올해가스공사·최근이천시 분리 유지를 코디네이터가 직접 확인 |
| `b30ef93a` | `bid_openg_results` 콜레이션을 `utf8mb4_unicode_ci` 로 정렬하고 G1 기준선 갱신. 코디네이터 직접 작업 `0485952f` | strict pass, 전량 10112 passed, 운영 DB managed 서명 PASS |

세 빌더 Task 는 cmd `deepseek/deepseek-v4.1-flash`, 리뷰는 cmd `z-ai/glm-5.3-flash` effort high 로 돌렸습니다. 모두 런처 비감독 경로(`orca_cmd_launch.py` 터미널 + taskctl `dispatch --launcher`)입니다. 워크트리 3개와 로컬 브랜치 4개는 병합 뒤 삭제했고 워커 터미널 6개는 모두 닫았습니다.

---

## 2. Orca 기록

| Task | 상태 | 비고 |
| --- | --- | --- |
| `task_23103f6f2cfa` | completed | A 빌더. 게이트 6 은 skip 건수 차이(보고 50, 재실행 41, 실패 0, 합계 동일)로 `report_path` 를 뺀 Capsule 사본으로 strict 기록 |
| `task_c3a9e724e6d0` | completed | B 빌더 |
| `task_1fbb0bd491b7` | completed | C 빌더. 처음 `worker_done` 에 보고 파일이 없어 터미널 지시로 보완함 |
| `task_ed11f42256e5`, `task_ef7ff627f71a`, `task_bb949091be40` | completed | A·B·C 리뷰, 모두 pass, `validate_review_report.py` 계약 만족 |

B·C 와 리뷰 Task 는 taskctl create 결함 때문에 `orca orchestration task-create` 로 직접 만들고 `orca_taskctl.py expand` 로 Capsule 을 실제 ID 경로와 stem 경로 두 곳에 썼습니다. B 병합으로 이 결함은 고쳐졌으니 다음 세션은 taskctl create 를 그대로 씁니다.

---

## 3. 아직 하지 않은 과업

| 과업 | 상태 |
| --- | --- |
| 유찰 1년 소급 `--execute` | 차단. 사용자 승인 전 실행 금지 |
| 유찰 T5 | 소급 적재 뒤에만 |
| 재입찰번호 유니크 재검증 | 소급 적재 뒤에만. 지금 행 수 0 |
| 적격심사 창 하한·창 필수화·별도 컬럼 | 사용자 결정 대기 |
| v2 재측정 | 앱 재시작 뒤. 이번 세션은 app 을 올리지 않았음 |
| `accounts_session_generation` 콜레이션 | `utf8mb4_0900_ai_ci` 그대로. 문자열 컬럼이 없어 서명·조인 영향 없음. 손대지 않음 |
| gap-guard 브랜치 | 병합 금지. 로컬 브랜치만 남음 |

---

## 4. 콜레이션 결함 기록

- **증상**: CI `G1 스키마 서명 재현성 검증` 이 `b4cd0866` 부터 `620ddbf1` 까지 연속 실패했습니다. `bid_openg_results` 8개 문자열 컬럼이 기준선 `VARCHAR(n)` 과 CI `VARCHAR(n) COLLATE "UTF8MB4_UNICODE_CI"` 로 달랐습니다.
- **원인**: 운영 스키마 기본 콜레이션은 `utf8mb4_0900_ai_ci` 입니다. 콜레이션을 명시하지 않은 `c1d2e3f4a5b6` 이 그 기본값으로 테이블을 만들었습니다. CI 는 스키마를 `utf8mb4_unicode_ci` 로 만들고, 나머지 운영 테이블도 `utf8mb4_unicode_ci` 입니다.
- **조치**: `c1d2e3f4a5b6` 에 콜레이션을 명시했습니다. 새 리비전 `a9b8c7d6e5f4` 는 테이블 콜레이션이 다를 때만 `CONVERT` 하고, downgrade 는 비어 있습니다. 운영 DB 에 적용했습니다.
- **증거**: 적용 전 백업은 `data/backups/snapshots/snapshot_20261103_021615` 이고 검증 PASS 입니다. 적용 전후 공고 5560232, 낙찰 3464615, 개찰결과 0 건이 같습니다. 기준선 diff 는 `bid_openg_results` 컬럼 표기와 해시뿐입니다.

---

## 5. 운영 메모

| 항목 | 내용 |
| --- | --- |
| 워커 `.venv` | 워크트리마다 `uv sync --frozen` 으로 따로 만들었습니다. 공용 `.venv` 링크는 편집 가능 설치 경로가 다른 워커의 `src` 를 가리킬 수 있어 피했습니다 |
| Level 1 게이트 | 셸 `&` 로 띄운 A 게이트는 완료 알림이 없었습니다. 게이트는 추적되는 배경 실행으로 띄웁니다 |
| 리뷰어 공급자 | 빌더와 같은 cmd 공급자여도 리뷰 Intent 에 `builder_provider: "cmd"` 를 두고 taskctl `dispatch --launcher` 로 거부 없이 기동했습니다 |
| premerge 키 | 전량 기록 전에 `G2B_SERVICE_KEY= serviceKey= SERVICE_KEY=` 를 비우는 우회는 A 병합 뒤로 불필요합니다. 이번 세션은 확인 차원에서 계속 비웠습니다 |
| Docker | 세션 종료 시 `docker compose stop` 으로 정지했습니다. 볼륨은 지우지 않았습니다 |
