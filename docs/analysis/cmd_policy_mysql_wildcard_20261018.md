# cmd 워커 정책 mysql/mysqldump 중간 와일드카드 실측

> 작성일: 2026-10-18

## 실측 환경

- 정책 원본: `scripts/orca_policies/commandcode_worker_settings.json`
- 배치 경로: `.commandcode/settings.json` (워크트리)
- 세션: `cmd -p '...' --model stealth/cat-jam:free --trust --yolo` (1회)

## 실측 결과

| # | 명령 | 기대 | 결과 | 매칭 규칙 |
|---|------|------|------|-----------|
| 1 | `mysql --version` | 차단 | 차단 | `Shell(mysql:*)` |
| 2 | `mysqldump --version` | 차단 | 차단 | `Shell(mysqldump:*)` |
| 3 | `for i in 1; do mysql --version; done` | 차단 | 차단 | `Shell(*do mysql *)` |
| 4 | `sh -c "mysql --version"` | 차단 | 차단 | `Shell(sh -c *mysql*)` |
| 5 | `echo $(mysql --version)` | 차단 | 차단 | `Shell(*$(mysql *)` |
| 6 | `for i in 1; do mysqldump --version; done` | 차단 | 차단 | `Shell(*mysqldump*)` |
| 7 | `sh -c "mysqldump --version"` | 차단 | 차단 | `Shell(sh -c *mysql*)` |
| 8 | `grep -c mysql docs/ops/multi_agent_setup.md` | 통과 | 통과 | - |
| 9 | `ls tests/test_mysql_concurrency.py` | 통과 | 통과 | - |
| 10 | `uv run python scripts/db_readonly_query.py --help` | 통과 | 통과 | - |

## 판정

- verdict: candidate
- 차단 7개 모두 차단, 통과 3개 모두 통과.
- mysql 은 실행 형태 경계(`;`, `&&`, `||`, `|`, `do`, `then`, `$(`, `sh -c`, `bash -c`, 따옴표)에 맞춘 중간 와일드카드를 사용했다.
- mysqldump 는 `Shell(*mysqldump*)` 로 넓게 막아도 정상 명령에 거의 등장하지 않아 오탐이 없다.
- blocking_issues: 없음.
