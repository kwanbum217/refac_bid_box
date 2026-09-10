# MySQL 통계 신선도 점검기 독립 검토 (2026-09-11)

> 작성일: 2026-09-11
> 대상: 브랜치 `kwanbum217/orca-az2`, 커밋 `ee1d250`
> 역할: 독립 리뷰어 (task_01a29588e1ff)
> 판정: pass
> 전제: 테스트를 재실행하지 않았고, DB 질의·ANALYZE TABLE·Docker 조작을 하지 않았다. 코드와 문서, `git diff main...HEAD` 만 대조했다.

---

## 1. 결론

점검 실행기는 읽기 전용이다. 종료 코드 1 은 사람에게 `ANALYZE TABLE` 을 권하는 신호일 뿐, 그 명령을 실행하거나 예약하지 않는다. 통계 행 부재와 `last_update` NULL 은 정상으로 오판하지 않는다. 원인 규명은 설정 오구성을 관측으로 기각하고 런타임 발화 실패는 미확정으로 남겼다. 갱신 주기 선택지는 셋이며 기준선 무효화 시점이 적혀 있다.

차단 결함은 없다. 잔여 리스크는 4절에 적는다.

---

## 2. 읽기 전용성

추적 범위는 `scripts/check_mysql_stats_freshness.py` 와 그것이 지연 임포트하는 `scripts/db_readonly_query.py` 이다.

| 경로 | 판정 | 근거 |
| --- | --- | --- |
| DB 쓰기 | 없음 | 질의 상수는 `SELECT NOW() AS now` 와 `SELECT table_name, last_update, n_rows FROM mysql.innodb_table_stats WHERE database_name = DATABASE()` 두 문장뿐이다 (`scripts/check_mysql_stats_freshness.py:45-49`) |
| SQL 결합 | 없음 | `--tables` 값은 질의에 넣지 않고, 조회 결과를 파이썬에서 이름으로 거른다 (`scripts/check_mysql_stats_freshness.py:157-164`) |
| ANALYZE | 없음 | 실행기·테스트에 `ANALYZE` 문자열이 없다. 정책 문서의 언급은 코디네이터가 이미 실행한 사실과 자동 실행을 만들지 않았다는 선언뿐이다 |
| 파일 쓰기 | 없음 | `open`, `Path.write`, `write_text` 가 없다. 출력은 `print` / `json.dumps` 표준출력만이다 |
| 컨테이너 제어 | 없음 | `docker`, `subprocess` 호출이 없다 |
| 네트워크 | DB 연결만 | `run_query` 가 `settings.DATABASE_URL` 로 SQLAlchemy 엔진을 연다. HTTP 클라이언트나 임의 소켓은 없다 |
| 파서 검사 | 재사용 | `fetch_stats` 가 두 문장 모두 `assert_read_only` 를 통과시킨 뒤에만 `run_query` 에 넘긴다 (`scripts/check_mysql_stats_freshness.py:146-153`) |
| 드라이버 차단 | 재사용 | `run_query` 는 `SET SESSION TRANSACTION READ ONLY` 후 실행한다 (`scripts/db_readonly_query.py:157-161`). `limit=0` 은 `fetchall` 이라 시스템 테이블 행을 잘라 오판하지 않는다 |

`assert_read_only` 는 `SELECT`/`SHOW`/`EXPLAIN`/`DESC`/`WITH` 시작 토큰만 통과시키고, 세미콜론 다중 문장과 쓰기 키워드를 거부한다. `ANALYZE TABLE` 은 시작 토큰 검사에서 걸린다. `last_update` 컬럼명은 단어 경계 때문에 `UPDATE` 금지 토큰에 오탐되지 않는다.

화이트리스트 변경은 `scripts/check_mysql_stats_freshness.py` 한 항목 추가가 전부이다 (`scripts/orca_auto_approve.py:1169-1179`). 같은 커밋이 실행기와 등록을 함께 넣었으므로 git 만으로는 "확인 시각이 등록보다 앞선다" 를 초 단위로 증명할 수 없다. 다만 등록된 스크립트 자체에 쓰기 경로가 없고, 다른 실행기나 docker/python 승인 분기는 열리지 않았다. 사람 승인 없이 돌아도 ANALYZE 나 스키마 변경이 나가지 않는다.

---

## 3. 임계 오판 방향

종료 코드 계약은 코드와 테스트가 같다. `EXIT_OK=0`, `EXIT_STALE=1`, `EXIT_ERROR=2` (`scripts/check_mysql_stats_freshness.py:30-32, 271-289`). 빈 테이블 목록과 음수 임계, 기준 행 수 파싱 실패, 조회 예외는 2 이다. 하나라도 `stale` 이면 1 이다.

| 상황 | 코드 동작 | 방향 |
| --- | --- | --- |
| 통계 행 없음 | `status=MISSING`, `stale=True`, 종료 코드 1 | 거짓 정상 쪽이 아니다 |
| `last_update` 가 NULL 이거나 파싱 실패 | `parse_last_update` 가 `None` 을 주고, `evaluate_table` 이 `stats_rows is None or last_update is None` 이면 MISSING (`scripts/check_mysql_stats_freshness.py:87-120`) | 거짓 정상 쪽이 아니다 |
| 편차·경과일 임계 초과 | `>` 비교라 임계값 정가(25.0%, 3.0일)는 정상 | 경계에서 거짓 정상 쪽으로 한 칸 |
| `--expected-rows` 생략 | 편차를 계산하지 않고 경과일로만 판정 | 최근 `last_update` 와 큰 `n_rows` 오차가 겹치면 거짓 정상. 문서 3.1절이 이 한계를 명시한다 |
| 표본 잡음 15.9% | 기본 편차 임계 25% 미만이라 정상 | 의도된 거짓 정상. 갱신 직후 ANALYZE 를 다시 권하지 않기 위한 값이다 |

종료 코드 1 의 대가는 되돌릴 수 없는 ANALYZE 이다. 실행기는 그 대가를 스스로 치르지 않고 사람에게 넘긴다. 행 부재와 NULL 시각은 ANALYZE 권고 쪽으로 닫혀 있고, 표본 잡음과 기준 행 수 생략은 방치 쪽으로 열려 있다. 열흘 방치(경과일 10, 실제 대비 편차 58.3%)는 두 축 모두 기본 임계를 넘기므로 당시 상태라면 1 을 냈을 것이다.

전용 테스트는 행 부재를 `None, None` 한 쌍으로만 고정한다 (`tests/test_mysql_stats_freshness.py:97-102`). `n_rows` 는 있고 `last_update` 만 NULL 인 분기는 같은 `or` 조건이라 코드상 동일하나, 그 입력만 넣는 테스트는 없다. 오판은 아니지만 고정이 한 겹 부족하다.

---

## 4. 원인 규명과 잔여 리스크

정책 2.2절은 가설마다 판정과 관측을 표로 적었다.

| 가설 | 문서 판정 | 이 검토의 평가 |
| --- | --- | --- |
| 자동 재계산이 꺼져 있었다 | 기각 | ground_truth 가 전역 ON 과 테이블별 재정의 없음을 확정한다 |
| 일시 통계를 쓰고 있었다 | 기각 | `innodb_table_stats` 행과 `last_update` 관측이 전제와 맞다. persistent ON 의 변수 조회 원문은 이 Task 가 재조회하지 않았다 |
| 변경분이 10% 임계에 못 미쳤다 | 기각 | 갱신 전 139.8% 는 ground_truth 확정값이다 |
| 히스토그램이 바뀌었다 | 기각 | `docs/analysis/ax2_plan_instability_20260911.md` 인용이다. 이 검토의 허용 읽기 범위 밖이라 원문을 재확인하지 않았다 |
| 백그라운드 재계산 미발화 | 미확정 | dict_stats 지연, 컨테이너 재시작 시 변경 카운터 소실, 대량 적재와 임계 시점 어긋남을 후보라고만 적고 단정하지 않았다 |

"설정 오구성이 아니다" 는 관측으로 지지된다. "왜 백그라운드가 안 돌았는가" 는 증상에서 남은 자리를 런타임 층으로 좁힌 것이지, 그 세 후보를 관측으로 고른 것은 아니다. 문서는 그 한계를 미확정으로 표시했다. 근거 없이 원인을 단정한 문장은 없다.

구조적 결론(자동 재계산에 의존하면서 점검 장치가 없었다)은 설정이 정상이었는데도 열흘이 갔다는 사실에서 나온 운영 판단이며, MySQL 내부 발화 조건의 확정이 아니다. 이 구분은 유지됐다.

잔여 리스크는 차단 결함이 아니다.

1. 편차 공식 혼용. 정책 1절의 139.8% 는 `(실제 - 통계) / 통계` 이고, 실행기는 `abs(통계 - 기준) / 기준` 이다. 같은 갱신 전 숫자에 대해 테스트는 58.3% 를 고정한다 (`tests/test_mysql_stats_freshness.py:30-31`). 25% 임계의 잡음 근거(15.9%)는 실행기 공식과 같고, 139.8% 인용만 다른 분모다. 당시 상태 검출은 두 공식 모두 25% 를 넘긴다. 다만 통계 대비 약 25% 과소(실제 대비 약 20%)는 실행기 기본 임계 아래라 경과일이 3일 이내면 정상이다. 선택지 B 가 안는다고 적은 "임계 안의 드리프트" 와 같은 방향이다.
2. 히스토그램 기각의 원문 재확인은 이 검토 범위 밖이다.
3. `last_update` 단독 NULL 테스트가 없다.

---

## 5. 범위와 정책 선택지

`git diff --name-only main...HEAD` 는 다음 넷뿐이다.

- `docs/ops/mysql_statistics_refresh_policy_20260911.md` (신설)
- `scripts/check_mysql_stats_freshness.py` (신설)
- `scripts/orca_auto_approve.py` (화이트리스트 한 항목)
- `tests/test_mysql_stats_freshness.py` (신설)

ANALYZE 를 주기 실행하는 코드, arq 태스크, 크론 항목은 없다. 정책 문서 상태줄과 4절이 "자동 실행 없음" / "자동 실행 코드는 만들지 않았다" 로 멈춘다. 새 패키지도 없다. 기존 테스트 파일은 수정되지 않았다. 단위 테스트는 조회를 주입해 계산·종료 코드·MISSING·JSON 을 고정하며 빈 테스트가 아니다.

선택지는 셋이다.

| 선택지 | 대가 | 기준선 무효화 시점 |
| --- | --- | --- |
| A. 수집 크론 직후 매일 갱신 | 야간 이후 측정이 매일 비교 불가능 | 갱신 실행 즉시 |
| B. 점검기 종료 코드 1 후 사람 승인 갱신 | 25% 미만 드리프트를 안고 감. 조회 자체는 기준선을 건드리지 않음 | 실제 갱신 실행 때 |
| C. 측정 기간 중 갱신 금지, 종료 후 수동 | 방치 재발 가능. 점검을 측정 시작 조건에 묶는 것이 전제 | 사람이 갱신을 실행한 때 |

5절 경고는 2026-09-11 갱신으로 그 이전 `EXPLAIN` 관찰이 옛 통계 기준이 됐음을 명시하고, 갱신 전후를 같은 표에 비교하지 말라고 적는다.

---

## 6. 빌더 완료 보고

`.orca/capsules/task_aa7febc6357b/worker_done.json` 이 있다. `schema=ORCA_WORKER_DONE_V2`, `version=2.1.0`, `task_id=task_aa7febc6357b`, `branch=kwanbum217/orca-az2`, `commit_count=1`, `commit_shas=["ee1d250"]`, `changed_files` 넷, `blocking_issues=[]` 를 갖췄다. 검증 항목은 대상 테스트 339, 전량 4388, 규칙 21/21, 점검기 종료 코드 0 이다. 이 검토는 그 명령을 재실행하지 않았다.

---

## 7. 체크리스트 요약

| id | 답 | 결함 |
| --- | --- | --- |
| root_cause_evidenced | yes | 아니오 |
| checker_read_only | yes | 아니오 |
| analyze_executed | no | 아니오 |
| exit_code_contract | yes | 아니오 |
| missing_stats_row | no | 아니오 |
| whitelist_safety | yes | 아니오 |
| policy_options_with_costs | yes | 아니오 |
| baseline_invalidation_warning | yes | 아니오 |
| heavy_query_executed | no | 아니오 |
| new_package_added | no | 아니오 |
| test_quality | no | 아니오 |
| scope_exceeded | no | 아니오 |
| worker_done_report_present | yes | 아니오 |

기계 보고: `.orca/capsules/task_01a29588e1ff/review_done.json`.
