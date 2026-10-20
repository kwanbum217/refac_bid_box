# 인수인계: 20260910 Wave AT 세션 종료

> **작성일**: 2026-09-10
> **Run**: `run_5c20ff7393cf` (Wave AT)
> **기준 커밋**: `7a92e06` -> `c2b62bc` (10 커밋)
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260910_wave_ar_as_session_close.md`](handoff_20260910_wave_ar_as_session_close.md)

---

## 0. 다음 세션 첫 작업

**`.env` 비밀값 다섯 개를 회전하십시오.** 이번 세션에서 코디네이터가 원복을 검증하다
`diff` 출력으로 실제 값을 노출했습니다. 상세는 6장입니다.

기능 작업으로는 **compare-stats 최적화 구현**이 가장 준비된 과제입니다. 병목이
쿼리 단위로 규명됐고 방안별 위험까지 정리돼 있어 곧바로 착수할 수 있습니다.
다만 순위가 `EXPLAIN` 추정이므로 승격 전 실행시간·논리 읽기·결과 동등성 검증이
선행 조건입니다.

**워크트리를 만들 때 반드시 `--setup skip` 을 붙이십시오.** 이번 세션에서 그
절차를 지켜 `pnpm-lock.yaml` 오염이 한 번도 없었습니다.

---

## 1. 이 세션이 한 일

| 커밋 | 내용 |
| --- | --- |
| `d6dc35f` | RAG 콜드 SQL 원인 조사 (AT2) |
| `458f8a8` | 콜드 SQL 조사 확정 사항 (AT5) |
| `e7415c0` | 자동 승인 화이트리스트 확장 (AT1) |
| `df602cd` | 감시기 인용 경로 파싱 (AT3) |
| `c2b62bc` | compare-stats 병목 조사 + lexical 전량 재측정 (AT4) |

병합 후 main 전량 테스트 **4,357 passed**, 규칙 21/21, 문서 링크 680파일 유효.
Task 7건 전부 `completed`, 자원 잔류 0.

---

## 2. 콜드 SQL 원인 규명 (조사 완료, 구현 미착수)

**이 세션의 가장 큰 성과입니다.** 코드 판독과 재현 실험이 같은 결론을 가리켰습니다.

### 2.1 확정된 사실

| 항목 | 확정 내용 | 근거 |
| --- | --- | --- |
| `sql_ms` 의 의미 | SQL 실행 시간이 **아닙니다.** `retrieve_structured_data` 호출 직전부터 반환 직후까지의 구간 값이며 Redis 캐시 조회, lazy checkout 대기, 다중 SQL, 결과 조립, `corrupted_probe` 가 전부 포함됩니다 | `src/rag/engine.py:743-747` |
| 느린 네 문항의 공통점 | 날짜 범위나 카테고리가 아니라 **기관명 필터를 가진 개체 지정 낙찰 질의**입니다. 기관명 필터가 `_snapshot_scope` 를 `None` 으로 만들어 live 집계 경로를 선택합니다 | `src/rag/structured_data.py:191-204` |
| 이벤트 루프 블로킹 | **부정됐습니다.** 정형 DB 호출은 `asyncio.to_thread` 로 오프로드됩니다. 스레드풀·DB 풀 경합은 별도 가설로 남습니다 | `src/rag/engine.py:1177-1185` |
| 하네스 동시성 | `concurrency=1` 직렬입니다. 동시 요청 경합은 이번 측정의 설명이 아닙니다 | `scripts/benchmark_rag_segments.py:786-809` |

### 2.2 재현 실험이 확증했습니다

전량 fixture 32문항 repetitions 3, 96요청으로 측정해 canonical 게이트를
통과했습니다(`data/benchmarks/rag_segments_lexical_full_20260910.json`).

`sql_ms` 는 P50 **9.51ms** 인데 max **90,415ms** 입니다. cold 32건에서만
P95 79,632ms 로 폭발합니다. 10초를 넘긴 문항은 넷뿐입니다.

| 문항 | all max | all P50 |
| --- | ---: | ---: |
| q03 | 90,415ms | 12.75ms |
| q08 | 80,080ms | 8.79ms |
| q25 | 79,265ms | 17.46ms |
| q31 | 71,964ms | 17.31ms |

**2026-08-30 에 지목된 문항과 정확히 같습니다.** 각 문항의 warm 회차는 8~17ms 로
정상입니다. 즉 첫 호출의 live 집계가 비용 전부입니다.

### 2.3 남은 것

개별 SQL 시간 구성비입니다. live 집계 안에 `_cached_aggregate` 두 회, 최근 결과와
표본과 시계열 조회, `_top_rows` 의 순위 SQL과 `corrupted_probe` 가 있는데 각각이
90초의 얼마인지 모릅니다. 실험 설계는
`docs/analysis/at2_coldsql_cause_investigation_20260910.md` 6장에 있습니다.
**q03/q08/q25/q31 네 문항만 재현 대상으로 쓰면 되므로 실험 비용이 낮습니다.**

---

## 3. compare-stats 병목 (조사 완료, 구현 미착수)

캐시 미적중 정상상태 6.5초의 병목을 쿼리 단위로 특정했습니다.

| 순위(추정) | 쿼리 | 예상 행 | 비용 신호 |
| ---: | --- | ---: | --- |
| 1 | 매칭 건수 (`dashboard.py:503`) | 3,118,641 | `ALL`, 인덱스 미사용, `Start temporary` |
| 2 | 기관별 상위 10 (`:525`) | 1,039,520 | `Using temporary; Using filesort` |
| 3 | 공고 월별 (`:511`) | 1,039,520 | 동일 |
| 4 | 낙찰 월별 (`:518`) | 742,016 | 동일 |

매칭 쿼리는 결과 기간 조건이 있는데도 `bid_results` 전체를 읽습니다. 의미를
보존한 `EXISTS` 대안은 예상 행을 약 72만으로 낮췄습니다.

**구현 전 주의 세 가지입니다.**

- 순위는 `EXPLAIN` 기반 **추정**입니다. 승격 전 실행시간·논리 읽기·결과 동등성을
  별도로 검증해야 합니다.
- **단순 `JOIN` 은 중복 때문에 매칭 건수를 바꿉니다.** `EXISTS` 또는
  `COUNT(DISTINCT ...)` 를 쓰십시오.
- 파생 집계 방안을 고른다면 갱신 시점 기록, 원본과의 `MAX(collected_at)`·행 수·합계
  대조, 불일치 시 **fail-closed** 가 함께 있어야 합니다. 이 저장소에는 파생 집계가
  뒤처져도 오류 없이 조용히 틀린 값을 낸 이력이 있습니다.
- **캐시 TTL 연장은 방안이 아닙니다.** 미적중 경로 비용을 줄이지 않고 가릴 뿐입니다.

상세는 `docs/analysis/at4_compare_stats_optimization_20260910.md` 입니다.

---

## 4. 자동 승인 화이트리스트 확장 (완료)

워커가 매번 사람 승인을 기다리던 명령을 열었습니다. 독립 리뷰 통과, blocking 0.

| 대상 | 허용 | 거부 |
| --- | --- | --- |
| `git add` | 명시 경로, `--dry-run`, `-n` | `-A`, `--all`, `-u`, `--update`, 점 경로, 인자 없음 |
| `git commit` | `-m`, `--message`, `-F`, `--file` | `--no-verify`, `-n`, `--amend`, `--allow-empty`, `--author`, `--date`, `--reset-author` |
| 기타 | `pgrep`, 임의 명령의 `--help`/`-h`, `orca orchestration send` | `orca` 의 다른 서브커맨드 전부 |

**`--no-verify` 거부가 핵심입니다.** 열리면 premerge 전량 테스트 게이트와 커밋
메시지 검증이 통째로 우회됩니다. `git reset`, `push`, `checkout`, `restore`,
`merge`, `rebase`, `worktree add/remove` 는 그대로 보류입니다.

리뷰어가 `-am`·`-nm`·`-mn` 결합 옵션, `--` 분리자 이후 처리, `--help` 판정 순서,
`orca` 인자 검사 네 지점을 전수 추적해 우회 경로가 없음을 확인했습니다.

---

## 5. 감시기 인용 경로 파싱 (완료)

`git status` 가 `core.quotePath` 로 큰따옴표와 C 스타일 이스케이프를 씌운 비ASCII
경로를 해석합니다. 8진수 바이트는 UTF-8 로 합치고, 디코딩할 수 없는 줄은 경고 후
건너뛰어 상시 감시가 멈추지 않습니다. 리뷰어가 잘린 멀티바이트 시퀀스, 미닫힘
따옴표, 빈 줄, NUL 입력에서 예외가 함수 밖으로 나가지 않음을 확인했습니다.

---

## 6. 코디네이터가 낸 사고와 실수

### 6.1 `.env` 비밀값 노출 (조치 필요)

측정을 위해 `LATENCY_SEGMENT_LOGGING` 을 켰다가 원복하는 과정에서, 백업과 현재
파일을 `diff` 로 대조하며 **`.env` 의 실제 값이 출력에 그대로 찍혔습니다.**
AGENTS.md 7장 4번 위반입니다.

노출 항목은 `serviceKey`, `MLOPS_WEBHOOK_URL`, `MEILI_MASTER_KEY`, `SECRET_KEY`,
`CEREBRAS_API_KEY` 와 DB 접속 문자열입니다. **다섯 개 키를 회전하십시오.** 외부
서비스인 `CEREBRAS_API_KEY` 와 Slack 웹훅이 우선입니다.

저장소에는 커밋되지 않았습니다(`.env` 는 gitignore). 이후 비교는 해시로만 했고
임시 백업 파일도 삭제했습니다.

**재발 방지**: `.env` 를 비교할 때는 `diff` 를 쓰지 말고 대상 행을 제외한 해시를
비교하십시오.

```bash
a=$(grep -v '^대상키' .env | shasum | cut -d' ' -f1)
b=$(grep -v '^대상키' <백업> | shasum | cut -d' ' -f1)
[ "$a" = "$b" ] && echo "다른 항목 변경 없음"
```

### 6.2 게이트 병렬 실행이 오탐을 만들었습니다

Level 1 게이트 두 개를 동시에 돌렸고, 각 게이트가 전량 pytest 를 두 번씩 돌려
**최대 4개가 겹쳤습니다.** 두 브랜치 모두 `1 failed` 가 나왔습니다.

**단독 순차 재실행에서 AT1 4,343 passed, AT3 4,299 passed 로 워커 보고와 정확히
일치했습니다.** 스킬 4.3 이 "검증이 공유 자원을 점유하면 직렬"이라 명시하는데
전량 pytest 가 DB·Redis 를 쓴다는 것을 놓쳤습니다.

**게이트는 순차로 돌리십시오.** 측정이 진행 중일 때도 게이트를 돌리면 안 됩니다.

### 6.3 Capsule 범위를 좁게 잡아 워커를 막았습니다

AT2 의 `read_scope` 에 `src/rag/**` 와 fixture 를 빠뜨려 워커가 정당하게 질문했고,
승인했으나 워커가 답을 받기 전에 마무리해 핵심 두 가지가 미확정으로 남았습니다.
AT5 를 따로 띄워 채웠습니다. **조사 Task 의 읽기 범위는 넉넉히 주십시오.**

AT1 에서는 "기존 테스트 수정 금지"가 정책 변경과 충돌했습니다.
`tests/test_orca_auto_approve.py:138` 이 `git commit -m` 을 hold 로 기대하고
있었습니다. 최소 변경을 조건으로 승인했습니다. **정책 자체를 바꾸는 Task 에는 그
정책을 고정하던 기존 기대도 함께 바뀐다는 것을 미리 적으십시오.**

### 6.4 감시기 차단 표시는 두 번 다 오탐이었습니다

워커가 소스를 읽거나 긴 명령 출력을 기다리는 화면을 정체로 오판합니다. 종료 코드는
0 이었습니다. **`[차단]` 표시를 보면 종료 코드를 먼저 확인하고 터미널을 직접
읽으십시오.**

---

## 7. 자원 정리 상태

**전부 회수했습니다.**

- 워크트리: 주 저장소 하나. `orca-at1` ~ `orca-at5` 전부 제거
- 브랜치: `main` 하나. 전부 `main..<branch>` 공집합 확인 후 삭제, `-D` 미사용
- 터미널: 코디네이터 창만 남음
- `orca_settled_session_audit.py` 잔류 없음, reclaimable 0
- 워커·리뷰 보고서는 주 저장소 `.orca/capsules/<task_id>/` 에 복사 보존
- Docker 스택은 측정 전 상태로 원복(`LATENCY_SEGMENT_LOGGING=false`, health 200)

### 7.1 Task 종결 상태 (`run_5c20ff7393cf`)

| Task | 상태 | 비고 |
| --- | --- | --- |
| `task_4e0cb73a3be4` | completed | AT1 빌더 |
| `task_7660c2e610aa` | completed | AT1 리뷰 (pass) |
| `task_12e0b6a575b7` | completed | AT2 조사 |
| `task_39ebe0ba85be` | completed | AT5 조사 확정 |
| `task_3ae7d1b84cbf` | completed | AT3 빌더 |
| `task_b1e1426917d6` | completed | AT3 리뷰 (pass) |
| `task_f46ed335d1fb` | completed | AT4 조사 |

---

## 8. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-18** | `.env` 비밀값 다섯 개 회전 | 없음. **즉시** |
| **R-19** | compare-stats 최적화 구현 | 없음. 조사 완료 (3장) |
| **R-20** | 콜드 SQL 개별 구성비 계측 | 없음. 실험 설계 완료. q03/q08/q25/q31 만 쓰면 비용 낮음 |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 경로가 열려 있습니다 |
| **R-15** | Orca setup 스크립트를 `npm ci` 로 영속 변경 | Orca 앱 UI. CLI 불가 |
| **R-17** | 협상 가격점수 | **차단**. `k` 와 `T` 의 원천이 공고 데이터에 없습니다 |
| **R-21** | SSR E2E Phase 2~4 | 사용자 합의 |
| **R-22** | 관측성 2단계 Prometheus | 메트릭 계측 선행 |
| **R-23** | RPO/RTO 분기 restore drill | 없음 |

### 8.1 하지 말아야 할 것

- 콜드 SQL 의 `sql_ms` 를 "쿼리 실행 시간"이라 부르지 마십시오. 구간 계측값입니다.
- compare-stats 에서 단순 `JOIN` 으로 매칭 건수를 세지 마십시오.
- 파생 집계를 뒤처짐 검출 없이 도입하지 마십시오.
- 캐시 TTL 연장으로 성능 문제를 덮지 마십시오.
- 기술용역의 `B`, `k`, `T` 를 하드코딩하지 마십시오.
- `.env` 를 `diff` 로 비교하지 마십시오.

---

## 9. 원격 반영

세션 중 `7a92e06` 까지 푸시했습니다. 그 뒤 10커밋(`c2b62bc` 까지)은 **로컬에만
있습니다.** 사용자 확인 후 올리십시오.

## 10. 모델 배정

빌더 `gpt-5.6-luna`(codex), 리뷰어 `opencode/muse-spark-1.3-contributor-free` 를
이 웨이브 전체에 썼습니다. 승인 경계를 다루는 AT1 만 effort `high`, 나머지는
`medium` 이었습니다. 리뷰어 Capsule 에는 `builder_provider: codex` 와
`builder_model: gpt-5.6-luna` 를 넣어야 독립성 검사를 통과합니다.

리뷰어 판정 품질은 이번에도 좋았습니다. 다만 **측정으로만 드러나는 것은 리뷰어도
코디네이터도 코드 읽기로 잡지 못합니다.** 콜드 SQL 재현이 그 예이며, 조사 Task 의
결론을 실측으로 확인하는 단계를 빼지 마십시오.
