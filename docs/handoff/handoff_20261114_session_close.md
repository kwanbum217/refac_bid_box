# 핸드오프 인수인계 - 2026-11-14 세션

> **작성일**: 2026-11-14
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_82daa4ce6228`
> **기준 커밋**: 작성 시점 `main` 은 `b794c52c` 입니다.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정). 워커 0대, 전부 회수.
> **이전 문서**: [`handoff_20261113_session_close.md`](handoff_20261113_session_close.md) 0절 1~7행의 결과는 이 문서 0절로 이어집니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | 예비가격 소급 이어서 실행 | `G2B_MAX_CONCURRENT=2 uv run python scripts/backfill_prearng_by_notices.py --since 2026-10-12 --until 2026-10-27 --limit 2000 --execute`. 누적 적재 2,166건, 하루 상한 2,000건 유지 |
| 2 | 주간 재학습 후보 판정(다음 월요일) | `docs/design/servc_freshness_retrain_20261114.md` 절차(최신성 쌍대, 운영 쌍대, 승인 후 승격) |
| 3 | `RedisConnection.invalidate()` 무잠금 쓰기 | 리뷰어 범위 밖 관찰. `client()` 는 잠금으로 고쳤으나 `invalidate()` 는 잠금 없이 `_client` 를 지웁니다. 확인된 영향은 없어 관찰만 합니다 |
| 4 | Docker 스택 유지 | 사용자 결정으로 세션 종료 때도 worker 를 포함한 스택을 내리지 않습니다 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 |
| --- | --- |
| `ad0578a4` | 11-14 인수인계와 source_commit 갱신 |
| `a0215184` | 예측 초과율을 연결 재사용(`predict_keepalive`)으로 판정, 재측정 결과 기록 |
| `0cef5a31` | 새 스킬 `web-platform-launch`: Docker 기동, 준비 대기, 브라우저 열기, 종료(Windows PowerShell 우선, `make` 불필요) |
| `f65903d6` | 메인 화면 무응답 수정: 요청 경로에서 365일·입찰 중 건수 동기 집계 제거("집계 중" 표시), worker 10분·기동 직후 예열 크론(TTL 7200초, Redis 선점), 최신 차수 판정을 NOT EXISTS 로 좁힘 |
| `222130aa` | 메인 정확도는 같은 버전 사이드카 실측(RMSE 2.56)을 우선, `RedisConnection.client()` 동시 호출 경쟁 제거 |
| `b794c52c` | `web-platform-launch` 10장 팀원용 에이전트 프롬프트, source_commit 을 `222130aa` 로 갱신 |

---

## 2. 운영 확인 결과

| 항목 | 결과 |
| --- | --- |
| 팀원 요청 5건(메인 삭제·신설, 브레드크럼 삭제, 낙찰 결과 용역 고정, 입찰 인텔리전스 메뉴 삭제) | 모두 반영 확인. 메인은 1440×900 에서 스크롤 없이 한 화면(문서 높이 900px) |
| 메인 응답 | 수정 전 120초 초과 무응답, 수정 후 5~121ms |
| 건수 예열 1회 | 수정 전 질의당 6분 초과(동시 3개 중첩), 수정 후 32.9초. 365일 192,007건, 입찰 중 5,199건 |
| 메인 정확도 표시 | ±2.70(승격 시 학습 검증 source_metrics) 에서 ±2.56(운영 실측 사이드카) 으로 |
| CI | `a0215184`, `0cef5a31`, `f65903d6`, `222130aa` 성공. `b794c52c` 는 종료 시점 실행 중 |

---

## 3. 운영 메모

| 메모 | 내용 |
| --- | --- |
| Level 1 게이트 인자 | `--tests`, `--verify` 는 값이 필요합니다. 템플릿(`src/app/templates`) 변경은 `--verify "npm run build:css"` 와 `--verify "git diff --exit-code -- src/app/static/css/tailwind.css"` 가 있어야 게이트 3 이 통과합니다 |
| source_commit | 병합이 쌓이면 병합 뒤 규칙 검증이 실패합니다. 푸시 전이면 로컬 병합을 되돌리고 작업 브랜치에서 갱신 커밋을 더해 다시 병합합니다(amend 금지) |
| 범위 밖 시험 수정 | 빌더가 기존 시험 수정을 요청하면 승인 회신과 함께 Capsule 세 사본(주 저장소, 워크트리 task id, Intent 이름)의 `allowed_write_files` 를 갱신해야 scope guard 가 커밋을 허용합니다 |
