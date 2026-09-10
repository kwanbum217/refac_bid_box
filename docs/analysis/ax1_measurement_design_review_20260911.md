# AX1 측정 하네스·비교 판정기 독립 검토

> 작성일: 2026-09-11
>
> 상태: 독립 검토 완료, 수용(pass)
>
> 대상: 브랜치 `kwanbum217/orca-ax1` 커밋 `0a5ca958b3c39fbbf9fff36025a35785aec905f8`
>
> 대상 파일: `scripts/benchmark_rag_segments.py`, `scripts/compare_rag_segments.py`, `scripts/orca_auto_approve.py`, `tests/test_benchmark_segment_capture.py`, `docs/analysis/ax1_measurement_design_20260911.md`
>
> 검토 Task: `task_1966202f2fc0`

---

## 1. 판정

**수용한다.** 산포 안의 시간 차이를 개선으로 적을 경로가 없고, 비교 실행기는
읽기 전용이다. 차단 결함은 없다.

이 도구는 이후 최적화의 채택 여부를 판정하는 게이트다. 관대한 쪽으로
틀리면 잡음을 효과로 읽게 되므로, 그 방향의 오류만 결함으로 본다.
아래 2장이 그 판정의 근거다.

---

## 2. 산포 판정: 보수적인 쪽으로 틀린다

구현은 `scripts/compare_rag_segments.py:347-397` 이다. 공유 시간 지표마다
다음 순서로 간다.

1. 조건별 표본이 `min_samples`(기본 2) 미만이면 `판정 불가`.
2. 두 조건의 최소~최대 범위가 겹치면 `구별 불가`.
3. 범위가 안 겹쳐도 평균차가 두 산포(max-min)의 합 이하이면 `구별 불가`.
4. 둘 다 실패하면 `산포 초과(참고)`. 확정도 개선도 아니다.

시간 항목의 가능한 문구는 `판정 불가`, `구별 불가`, `산포 초과(참고)` 세 개
뿐이다. `확정` 과 `개선` 은 시간 분기에 존재하지 않는다.
`format_verdict` 도 그 문자열을 만들어 내지 않는다.

### 2.1 두 조건은 설계상 보수적이다

범위가 겹치면 평균이 멀어도 구별 불가다. 범위가 안 겹쳐도 평균차가
산포 합 안에 있으면 역시 구별 불가다. 관대한 판정은 평균만 보고 우열을
적는 것인데, 그 경로는 막혀 있다.

AW2 실패 사례와 같은 입력
(`cached_aggregate_2` 가 1,665ms 와 40,984ms 를 오가는 경우)은
`tests/test_benchmark_segment_capture.py:167-186` 이 `구별 불가` 로 고정하고,
출력 문자열에 `개선` 이 없음을 단언한다.

### 2.2 소표본에서 범위 비겹침이 나와도 시간 확정은 나오지 않는다

관측 범위는 표본이 작을수록 참 범위를 작게 본다. n=2 또는 n=4 에서
같은 분포의 두 표본이 우연히 안 겹칠 여지는 있다.

같은 연속 분포에서 크기 4인 두 표본이 완전히 분리될 확률은 대략
`2 / C(8,4) = 2/70 ≈ 3%` 수준이다. 다만 그 전형적인 분리는 네 작은 값 대
네 큰 값이라 간격이 좁다. 그때 평균차는 산포 합보다 작아 3번 조건이
구별 불가로 되돌린다.

3번까지 통과하려면 두 덩어리 사이에 산포 합의 절반보다 큰 틈이 있어야
한다. 동일 분포에서는 드물다. 설령 나와도 결과는 `산포 초과(참고)` 이고
`확정` 이 아니다. 문서 `docs/analysis/ax1_measurement_design_20260911.md:61-62`
도 "표본이 적으므로 확정하지 않고 참고로만 둔다" 로 못 박는다.

따라서 **우연히 범위가 안 겹쳐 시간 확정이 나올 확률은 0** 이다.
구현이 관대한 쪽으로 틀리지 않는다. 결함이 아니다.

남는 잔여는 n=2 에서 두 쌍이 멀리 떨어진 채 각자 뭉치면 `산포 초과(참고)`
가 날 수 있다는 점이다. 이는 우열 주장이 아니라 참고 신호다. 문서 4장
읽기 절차가 구조 확정만 사실로 인용하라고 적는다.

구조 항목의 `확정`(구간 소멸·생성, 카운터 범위 비겹침)은 타이밍 잡음과
무관한 존재 여부라 소표본에서도 확정으로 보는 설계다. 문서 2.1절과
코드 `scripts/compare_rag_segments.py:193-218`, `253-265` 가 일치한다.

---

## 3. 비교기는 읽기 전용이다

`scripts/compare_rag_segments.py` 전수 추적 결과다.

| 위험 | 존재 |
| --- | --- |
| 파일 쓰기 (`write_text`, `json.dump`, `open(..., "w")`) | 없음 |
| DB 접속 | 없음 |
| 컨테이너 제어 (`docker`) | 없음 |
| 네트워크 (`urllib`, `socket`, `requests`) | 없음 |
| `subprocess` | 없음 |
| 외부 패키지 | 없음. `argparse`, `json`, `typing` 만 |

`open` 은 `load_result` 한 곳뿐이다(`scripts/compare_rag_segments.py:54`).
`open(path, encoding="utf-8")` 는 모드 기본값이 읽기(`r`)다.
`main` 은 두 JSON 을 읽어 `print(format_verdict(...))` 만 하고 종료한다.
출력 파일 인자가 없다.

CLI 테스트 `tests/test_benchmark_segment_capture.py:201-238` 은 실행 전후
입력 파일 내용이 같고, 임시 디렉터리에 파일이 늘지 않음을 단언한다.

자동 승인 화이트리스트에 넣어도 사람 승인 없이 쓰기가 열리지 않는다.

---

## 4. 파싱 변경은 옛 줄을 깨지 않는다

`parse_segment_lines` 는 먼저 `_split_structured_sql_field` 로 JSON 조각을
떼고, 나머지에만 기존 정규식 `(\w+)=([^\s]+)` 을 쓴다.

- 마커가 없으면 원문을 그대로 돌려준다. 옛 로그 줄은 예전과 같다.
- `null`, 잘린 JSON(`end is None`), `JSONDecodeError`, 객체가 아닌 값은
  모두 예외를 내지 않고 필드를 생략한다.
- 중괄호 깊이와 문자열 이스케이프를 세므로 중첩 객체와 값 안 공백을
  잘리지 않게 읽는다. 계측 JSON 은 로그 줄 끝에 붙으므로, 잘린 경우
  마커 앞 필드는 `payload[:idx]` 로 남는다.

기존 결과 JSON 키는 삭제·개명이 없다. `main` 대비 HEAD 의 `payload`
최상위 키는 제거 0건, 추가 7건
(`structured_sql_traces` 와 집계 키)이다.

---

## 5. `corrupted_probe_ms` 는 이중 계상되지 않는다

하네스 `summarize_structured_sql_segments`
(`scripts/benchmark_rag_segments.py:403-467`) 는 구간을 이름별로만 모아
집계하고 합산하지 않는다. 구성비는 각 구간 평균 / `cursor_ms` 평균이며,
주석과 문서 5장이 합이 100%를 넘을 수 있다고 명시한다.

비교기도 구간을 독립 지표로 모은다. `corrupted_probe_ms` 를
`top_rows_N` 에 더하거나, 구간 합과 `cursor_ms` 의 일치를 요구하는 검사가
없다. 중첩을 무시하고 합치면 실패하는 무결성 검사가 없으므로, 그 검사가
중첩을 놓치는 문제도 없다.

---

## 6. 화이트리스트는 항목 하나만 더했다

`scripts/orca_auto_approve.py:1127-1137` 의 판정 로직은 그대로다.
`uv run python|python3 <target>` 의 `target` 문자열이 집합 원소와
일치할 때만 승인한다.

추가된 원소는 `scripts/compare_rag_segments.py` 하나다.
`./scripts/compare_rag_segments.py` 나
`scripts/../scripts/compare_rag_segments.py` 는 집합에 없어 보류된다.
상대 경로 조작은 다른 스크립트를 승인하지 않고, 허용 경로도 별칭으로는
열리지 않는다(닫힌 실패).

`uv run --with ... python ...` 는 `args[1]` 이 `python` 이 아니라서
기존처럼 보류된다.

---

## 7. 문서

`docs/analysis/ax1_measurement_design_20260911.md` 는 구조 확정, 구성비
참고, 절대 시간 산포 대비의 세 등급과 조건 동등화 세 항목(스냅샷 재구축
금지 구간, Redis 초기화 대칭, 반복 회차)을 절차로 적는다. AW2 실패의
직접 원인과 맞다.

EXPLAIN 추정을 실측으로 인용한 과거 실패를 이 문서가 이름 붙여 적지는
않는다. 도구의 존재 이유 문장은 AW2 잡음과 1회 차감 금지가 대신한다.
조건 동등화 규약은 있으므로 차단 사유는 아니다.

---

## 8. 범위와 테스트

`git diff --name-only main...HEAD` 는 허용된 다섯 파일뿐이다.
`src/rag`, `src/app`, `pyproject.toml` 은 없다.
새 테스트 파일만 추가됐고, 빈 `pass` 테스트나 기존 테스트 파일 수정은
없다.

`worker_done.json` 은 `.orca/capsules/task_300707949c54/worker_done.json`
에 있고 `version`, `task_id`, `branch`, `commit_count`, `commit`,
`changed_files`, `blocking_issues` 를 갖춘다. 테스트는 재실행하지 않았다.
