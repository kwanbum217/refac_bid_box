# Orca v2 프록시 지표 원장

> **작성일**: 2026-08-15
> **작성자**: Orca Worker (task_6bd7cee23f01)
> **버전**: v1.0.0
> **관련 설계**: 설계 23장 (성공 지표 추적)

---

## 1. 목적

Orca v2 도입 효과를 정량으로 추적하기 위한 append-only 원장입니다.
Task Dispatch 를 완료할 때마다 Capsule 길이, 보고 길이, 읽은 파일 수,
왕복 횟수 등의 프록시 지표를 한 행으로 기록하고, `summary` 명령으로 집계합니다.

### 1.1 한계 사항

v2 도입 이전 데이터는 확보가 불가능하다고 이미 판정했습니다.
따라서 도입 전 값을 추정으로 채우지 않습니다.
`before` 열은 없으며, v2 이후 기준선부터 행이 누적됩니다.
비교 분석은 충분한 행이 쌓인 뒤에 수행합니다.

---

## 2. 원장 파일 위치

기본 경로: `docs/ops/orca_v2_metrics_ledger.jsonl`

`--ledger <경로>` 인자로 바꿀 수 있습니다.
원장 JSONL 파일 자체는 Git 에 커밋하지 않습니다.

---

### 2.1 인터프리터

**`uv run python` 으로 실행합니다.** 이 도구는 `scripts/orca_coordinator_usage.py` 를 import 하고 그 모듈은 `datetime.UTC`(Python 3.11+)를 씁니다. `pyproject.toml` 의 `requires-python` 이 `>=3.11,<3.14` 이므로 규격 내이지만, macOS 의 `python3` 는 Xcode 가 제공하는 3.9 로 해석될 수 있어 `ImportError: cannot import name 'UTC'` 가 납니다.

```bash
python3 --version        # 3.9.6 일 수 있습니다
uv run python --version  # 프로젝트가 고정한 3.12
```

코드를 3.9 호환으로 낮추지 마십시오. 선언한 하한과 어긋납니다.

---

## 3. 행 스키마

원장의 각 행은 JSON 객체 한 줄입니다. 행 하나가 Dispatch 한 건에 대응합니다.

| 필드 | 타입 | 자동 도출 | 설명 |
| --- | --- | --- | --- |
| `ledger_schema` | str | 예 | 스키마 버전 상수 (`ORCA_V2_METRICS_ROW_1`) |
| `recorded_at` | str | 예 | ISO 8601 로컬 시각 |
| `run_id` | str | 아니오 | Orca Run ID (`--run`) |
| `task_id` | str | 아니오 | Task ID (`--task`) |
| `dispatch_id` | str | 아니오 | Dispatch ID (`--dispatch`) |
| `role` | str | 아니오 | 워커 역할 (`builder`, `reviewer` 등) |
| `model` | str | 아니오 | 모델 식별자 (`--model`) |
| `capsule_path` | str | 아니오 | Capsule 파일 경로 |
| `report_path` | str | 아니오 | 보고 JSON 파일 경로 |
| `capsule_chars` | int | 예 | Capsule 원문 문자 수 |
| `report_chars` | int | 예 | 보고 원문 문자 수 |
| `read_files_count` | int | 예 | 보고의 `read_files` 항목 수 |
| `changed_files_count` | int | 예 | 보고의 `files_modified` 항목 수 |
| `verification_count` | int | 예 | 보고의 `verification` 항목 수 |
| `verdict` | str | 예 | 보고의 `verdict` 또는 `outcome` 값 |
| `status` | str | 예 | 보고의 `status` 값 |
| `roundtrips` | int or null | 아니오 | 왕복 횟수. 미지정 시 null |
| `first_useful_seconds` | int or null | 아니오 | 첫 유용 산출 소요 초. 미지정 시 null |
| `coordinator_input_tokens` | int or null | 조건부 | 코디네이터 입력 토큰 총합. **세션 간 비교 금지** (3.1 절) |
| `coordinator_fresh_input_tokens` | int or null | 조건부 | 캐시 재읽기를 제외한 신선 입력 토큰. **위임 비교 대표 지표** |
| `coordinator_output_tokens` | int or null | 조건부 | 코디네이터 출력 토큰 |
| `usage_window_start` | str or null | 아니오 | 토큰 집계 창 시작 (`--usage-since`) |
| `usage_window_end` | str or null | 아니오 | 토큰 집계 창 종료 (`--usage-until`) |
| `usage_concurrent_dispatches` | int or null | 아니오 | 그 창을 공유한 동시 Dispatch 수. 2 이상이면 행 간 합산 불가 |
| `usage_lookup_status` | str or null | 예 | `ok`, `no_transcript_dir`, `no_session_file`, `empty_window` |

> **null 원칙**: 측정하지 않은 값은 절대 0 이나 추정치로 채우지 않습니다.
> null 인 행은 해당 지표의 집계에서 제외하고, 유효 행 수를 함께 보고합니다.

### 3.1 코디네이터 토큰 대표 지표

`--usage-since` 를 주면 `scripts/orca_coordinator_usage.py` 가 Claude Code 세션
트랜스크립트에서 세 값을 자동으로 채웁니다. `/usage` 를 수동으로 옮겨 적지 않습니다.

**위임 절감 비교에는 `coordinator_fresh_input_tokens` 만 씁니다.**
`coordinator_input_tokens` 는 `input_tokens + cache_creation + cache_read` 의 합이고,
2026-08-16 실측에서 `cache_read` 가 **99.5 퍼센트**(399,563,803 중 397,513,915)를
차지했습니다. `cache_read` 는 매 assistant 메시지가 캐시된 접두부 전체를 다시 읽어
누적되므로 대화 턴 수에 비례하고 위임 여부와 무관합니다. 이 값으로 비교하면 위임을
잘한 세션이 턴이 많다는 이유로 더 나빠 보입니다.

| 지표 | 2026-08-16 세션 전체 | 20분 창 (워커 3대 Dispatch) |
| --- | ---: | ---: |
| `coordinator_input_tokens` | 399,563,803 | 6,984,330 |
| `coordinator_fresh_input_tokens` | 2,049,888 | 150,929 |
| 배율 | 195배 | 46배 |

### 3.2 계측 이전 행과 조회 실패 행

원장은 append-only 이므로 계측 도입 이전 8 행의 토큰 필드는 null 로 남습니다. 소급
수정하지 않습니다.

`usage_lookup_status` 는 계측되지 않은 행이 계측된 것처럼 보이는 것을 막습니다.
`ok` 가 아닌 행은 토큰이 null 이며, `no_transcript_dir` 은 대개 워크트리에서 실행해
슬러그가 달라진 경우입니다. 이때는 `--usage-transcript-dir` 로 주 저장소의 트랜스크립트
디렉터리를 명시합니다.

세션 선택 기본값은 수정 시각이 가장 최근인 파일 **하나**입니다. 이 저장소는 같은
프로젝트에 병렬 Claude 세션이 뜬 이력이 있어 전체 합산이 기본값이면 다른 세션의 토큰이
섞입니다. 명시 지정은 `--usage-session`, 전체 합산은 `--usage-all-sessions` 입니다.
집계에 기여한 파일명은 항상 stderr 로 출력됩니다.

`usage_concurrent_dispatches` 가 2 이상인 행은 창을 여러 Dispatch 가 공유했다는 뜻이라
`summary` 의 코디네이터 토큰 집계에서 제외되고, 제외된 행 수가 함께 출력됩니다.

---

## 4. 사용 예

### 4.1 record: 한 건 기록

```bash
uv run python scripts/orca_metrics_ledger.py record \
  --run run_659389fed248 \
  --task task_6bd7cee23f01 \
  --dispatch ctx_0d555d0bb609 \
  --role builder \
  --model claude-sonnet-4-6 \
  --capsule /Users/kwanbum/orca/capsules/run_659389fed248/w3/capsule.yaml \
  --report /Users/kwanbum/orca/capsules/run_659389fed248/w3/worker_done.json \
  --roundtrips 2
```

왕복 횟수를 모르면 `--roundtrips` 를 생략합니다. null 로 저장됩니다.

JSON 형식 출력:

```bash
uv run python scripts/orca_metrics_ledger.py record ... --json
```

원장 파일 경로 변경:

```bash
uv run python scripts/orca_metrics_ledger.py --ledger /tmp/test.jsonl record ...
```

### 4.2 summary: 집계 출력

```bash
uv run python scripts/orca_metrics_ledger.py summary
```

날짜 필터:

```bash
uv run python scripts/orca_metrics_ledger.py summary --since 2026-08-01
```

역할 필터:

```bash
uv run python scripts/orca_metrics_ledger.py summary --role builder
```

모델 필터:

```bash
uv run python scripts/orca_metrics_ledger.py summary --model claude-sonnet-4-6
```

JSON 출력:

```bash
uv run python scripts/orca_metrics_ledger.py summary --json
```

### 4.3 summary 출력 예

```
원장 행 수: 5 (전체: 5, 손상: 0)

지표별 집계:
  capsule_chars: 유효 5/5행, 중앙값=8500.0, 평균=8700.0
  report_chars: 유효 5/5행, 중앙값=3200.0, 평균=3150.0
  read_files_count: 유효 5/5행, 중앙값=4.0, 평균=4.2
  changed_files_count: 유효 5/5행, 중앙값=2.0, 평균=2.0
  roundtrips: 유효 2/5행, 중앙값=3.0, 평균=3.5 [표본 부족]
  first_useful_seconds: 유효 0/5행, 중앙값=null, 평균=null [표본 부족]

verdict 분포:
  succeeded: 5행

역할별 행 수:
  builder: 4행
  reviewer: 1행

모델별 통계:
  claude-sonnet-4-6: 5행, report_chars 중앙값=3200.0
```

---

## 5. append-only 규칙

- 원장은 추가 전용입니다. 기존 행을 수정하거나 삭제하는 코드 경로가 없습니다.
- 같은 `(task_id, dispatch_id)` 조합이 이미 존재하면 종료 코드 1 과 안내 메시지를 냅니다.
- `--force` 같은 덮어쓰기 플래그는 없습니다.

---

## 6. 손상 행 처리

JSON 파싱 실패 행은 조용히 건너뛰지 않습니다.
`summary` 출력에 손상 행 수를 표시하며, 손상 행은 집계에서 제외됩니다.

---

## 7. 지표 방향

설계 23장의 기준에 따른 개선 방향입니다.

| 지표 | 목표 방향 | 비고 |
| --- | --- | --- |
| `capsule_chars` | 감소 | Capsule 이 작을수록 컨텍스트 효율이 높음 |
| `report_chars` | 감소 | 보고가 간결할수록 처리 비용이 낮음 |
| `read_files_count` | 감소 | 불필요한 탐색 제거 |
| `roundtrips` | 감소 | 왕복이 적을수록 조율 오버헤드 감소 |
| `first_useful_seconds` | 감소 | 빠른 첫 산출이 목표 |
| 회귀 | 증가 금지 | 수락 기준 이상의 회귀는 차단 |
