# 날짜 의존 시험(날짜 시한폭탄) 전수 조사 및 기준일 고정

> **작성일**: 2026-10-04
> **대상**: 저장소 `tests/` 전체의 날짜 의존 시험과 `src/` 13개 시각 사용 모듈
> **계기**: 2026-10-04 `tests/test_result_coverage.py::test_task_notifies_only_when_alert` 가 코드 변경 없이 실행 날짜만 바뀌어 실패(커밋 `ab38428e` 에서 기준일 고정으로 수정)
> **판정**: 실행 날짜에 흔들리던 시험 5건의 기준일을 고정했고, `src/` 운영 코드는 변경하지 않았습니다.
> **상태**: 완료 (시험 5파일, 운영 코드 0파일)

---

## 요약

운영 코드가 `date.today()`/`datetime.now()`/`utcnow()` 로 "지금"을 기준 창을 계산하는데, 시험이 고정 날짜 데이터를 넣으면 실행 날짜가 지나며 두 기준이 어긋나 저절로 깨집니다. 커밋 `ab38428e` 의 낙찰결과 커버리지 시험이 그 첫 사례였습니다.

임시 pytest 플러그인으로 13개 시각 사용 모듈의 `date`/`datetime` 을 +30일, +90일, +365일 미래를 돌려주는 하위 클래스로 바꿔 전체 시험을 돌렸습니다. 수정 전 실패는 +30일 3건, +90일 4건, +365일 5건이었고, 시험 5건(test 5파일)의 기준일을 고정한 뒤 세 시점 모두 실패 0건(6,014 통과)입니다. 특히 `tests/test_kb_builder.py::test_memory_bound_announcements_query_streaming` 는 실측으로 확정한 진짜 시한폭탄으로, 시드 데이터(2026-06-01)가 `utcnow()` 기준 최근 1년 창에서 2027-06-01 이후 밀려나 실패합니다.

---

## 1. 조사 방법

### 1.1 플러그인 요지

`date.today()`·`datetime.now()`·`datetime.utcnow()` 를 오늘 + N일로 돌려주는 하위 클래스를 만들고, 13개 모듈의 모듈 전역 이름 `date`/`datetime` 을 그 하위 클래스로 바꿉니다. `isinstance` 판정이 깨져 생기는 거짓 실패를 막기 위해 메타클래스의 `__instancecheck__` 가 실제 `datetime` 인스턴스도 통과시키게 했습니다. 플러그인 파일은 `.orca/` 스크래치에만 두고 커밋하지 않았습니다.

```python
# date_bomb_plugin.py (임시, 커밋 금지)
import importlib
import os
import sys
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

OFFSET_DAYS = int(os.environ.get("DATE_BOMB_OFFSET_DAYS", "0"))

MODULES = [
    "src.tasks.worker",
    "src.tasks.scheduled_tasks",
    "src.tasks.coverage_tasks",
    "src.app.core.timeutil",
    "src.app.core.observability",
    "src.app.api.v1.chatbot",
    "src.app.services.result_coverage",
    "src.app.services.mysql_stats_freshness",
    "src.app.services.demand_institutions",
    "src.app.services.restore_drill_freshness",
    "src.rag.query_planning",
    "src.rag.structured_data",
    "src.rag.engine",
]


class _InstanceTolerant(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _datetime) or super().__instancecheck__(obj)


class FutureDate(_date, metaclass=_InstanceTolerant):
    @classmethod
    def today(cls):
        return _date.today() + _timedelta(days=OFFSET_DAYS)


class FutureDateTime(_datetime, metaclass=_InstanceTolerant):
    @classmethod
    def now(cls, tz=None):
        return _datetime.now(tz) + _timedelta(days=OFFSET_DAYS)

    @classmethod
    def utcnow(cls):
        return _datetime.utcnow() + _timedelta(days=OFFSET_DAYS)


def _patch(mod):
    if getattr(mod, "date", None) is _date:
        mod.date = FutureDate
    if getattr(mod, "datetime", None) is _datetime:
        mod.datetime = FutureDateTime


def pytest_configure(config):
    patched = []
    for name in MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:
            sys.stderr.write(f"[date_bomb] import skip {name}: {exc}\n")
            continue
        _patch(mod)
        patched.append(name)
    sys.stderr.write(f"[date_bomb] +{OFFSET_DAYS}d patched {len(patched)} modules\n")
```

주의: `src.app.core.timeutil.utcnow()` 를 쓰는 다른 모듈도 플러그인의 영향을 받습니다. `timeutil.datetime` 을 바꾸면 `utcnow()` 반환값이 함께 밀리므로, 13개 목록 밖의 모듈(예: `src/app/services/kb_builder.py`)도 같은 스윕에 포함됩니다.

### 1.2 실행 명령

```sh
mkdir -p /tmp/date_bomb_audit
# 위 코드를 /tmp/date_bomb_audit/date_bomb_plugin.py 로 저장

# 시점별 전량 시험 (미래 시점에서만 실패하는 시험 = 날짜 시한폭탄)
PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=30  uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short
PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=90  uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short
PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=365 uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short

# 고친 시험만 빠르게 재확인
PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=365 uv run pytest -q -p date_bomb_plugin \
  tests/test_monitor_catchup.py tests/test_query_planning.py \
  tests/test_rag_multi_institution.py tests/test_kb_builder.py
```

---

## 2. 13개 시각 사용 모듈의 날짜 호출 지점과 시험 고정 여부

| 모듈 | 날짜 호출 지점 | 시험 고정 여부 |
| --- | --- | --- |
| `src/tasks/worker.py` | `datetime.now(UTC).isoformat()` (`_now_iso`) | 형식만 검증. 기준일 무관 |
| `src/tasks/scheduled_tasks.py` | `datetime.now().astimezone().tzinfo` (`resolve_schedule_timezone`) | 타임존 주입·오프셋만 검증. 기준일 무관 |
| `src/tasks/coverage_tasks.py` | `date.today()` 를 `as_of` 로 사용 | `ab38428e` 에서 고정. `test_monitor_catchup` 추가 고정 |
| `src/app/core/timeutil.py` | `datetime.now(UTC)` (`utcnow`) | 시험이 이 함수로 상대 시각을 시드해 창과 함께 이동. 자체 정합 |
| `src/app/core/observability.py` | `datetime.now(UTC).isoformat()` (내보내기 시각) | 형식만 검증. 기준일 무관 |
| `src/app/api/v1/chatbot.py` | `datetime.now().strftime(...)` (trace_id) | 형식만 검증. 기준일 무관 |
| `src/app/services/result_coverage.py` | `today` 미지정 시 `date.today()` (억제 판정) | 시험은 `today=` 를 명시 주입 |
| `src/app/services/mysql_stats_freshness.py` | `datetime.now()` 폴백 (DB 시각 부재 시) | 시험은 DB 조회 시각/명시 값을 사용 |
| `src/app/services/demand_institutions.py` | `date.today()` 를 수집 종료일로 사용 | 시험은 `collect_demand_institutions` 에 시작·종료일 명시 |
| `src/app/services/restore_drill_freshness.py` | `now or datetime.now(UTC)` | 시험은 `now=NOW` 명시 주입 |
| `src/rag/query_planning.py` | `date.today()` (최근 창, 연도) | `_FROZEN_TODAY` 로 기준일 고정 |
| `src/rag/structured_data.py` | `date.today()` (relative_years, 분기 기본값) | 시험은 명시 필터/`as_of` 주입 |
| `src/rag/engine.py` | `date.today()` (years 창), `datetime.now()` (trace) | 명시 연도 필터/형식 검증. 기준일 무관 |
| `src/app/services/kb_builder.py` (추가 발견) | `utcnow()` 기준 최근 1년 창 | `_KB_REFERENCE_NOW` 로 기준 시각 고정 |

`kb_builder` 는 `date.today()`/`datetime.now()` 를 직접 부르지 않아 1차 목록에는 없었지만, `timeutil.utcnow()` 를 통해 같은 스윕에 걸려 실측으로 확정되었습니다.

---

## 3. 시점별 실패 목록 (수정 전)

`-m 'not data_assets'` 전량 시험 기준입니다. 실패 시험이 시점에 따라 늘어나는 것이 날짜 시한폭탄의 특징입니다.

| 시험 | +30일 (2026-11-03) | +90일 (2027-01-02) | +365일 (2027-10-04) | 성격 |
| --- | --- | --- | --- | --- |
| `tests/test_monitor_catchup.py::test_collect_snapshot_reads_suppression_from_settings` | 실패 | 실패 | 실패 | 기준일 미고정 |
| `tests/test_query_planning.py::test_retrieval_plan_adversarial_fixture_v1_snapshot_invariance` | 실패 (`adv_inj_03`) | 실패 | 실패 | 기준일 미고정 |
| `tests/test_rag_multi_institution.py::test_multi_institution_aggregation_and_source_snapshot` | 실패 (`bid_count 0`) | 실패 | 실패 | 기준일 미고정 |
| `tests/test_query_planning.py::test_quarter_and_half_year_parsing` | 통과 | 실패 (`2027-07-01 != 2026-07-01`) | 실패 | 연도 경계 통과 시 실패 |
| `tests/test_kb_builder.py::test_memory_bound_announcements_query_streaming` | 통과 | 통과 | 실패 (`status failed`) | 최근 1년 창에서 시드가 밀림 |

실패 요약: +30일 3건, +90일 4건, +365일 5건.

`kb_builder` 사례는 실행 중 실패 로그 `src/app/services/kb_builder.py:268 지식베이스 구축 실패` 와 함께 `status='failed'` 로 나타났습니다. 시드 공고일 2026-06-01 이 `one_year_ago = utcnow() - 365일` 보다 과거가 되는 시점(2027-06-01 이후)부터 창에서 빠져 색인 대상이 0건이 되기 때문입니다. 다른 네 건은 시험이 실행 시각을 그대로 기대값에 쓰는데 플러그인이 계획기 시계만 밀어 두 기준이 어긋난 경우로, 기준일을 고정하면 두 기준이 다시 일치합니다.

---

## 4. 고친 시험과 방식

단언은 약화·삭제하지 않았고 `skip`/`xfail` 을 추가하지 않았습니다. 운영 코드(`src/`)는 손대지 않았습니다. 시험 데이터와 맞는 기준일을 시험 안에서 `monkeypatch` 로 고정했습니다.

| 시험 파일 | 고정 방식 |
| --- | --- |
| `tests/test_monitor_catchup.py` | `coverage_tasks.date` 를 `_FrozenDate`(2026-10-04) 로 고정하고 `captured["today"] == reference` 를 단언 |
| `tests/test_query_planning.py` | 모듈 상단에 `_FROZEN_TODAY = date(2026, 10, 4)` 와 `_FrozenDate` 를 두고, 스냅샷·분기 시험에서 `query_planning.date` 를 고정. `_expected_filters` 는 `relative_to_today` 오프셋을 `_FROZEN_TODAY` 기준으로 계산. 함수 내부 `from datetime import date` 를 제거하고 `today_year = _FROZEN_TODAY.year` 사용 |
| `tests/test_rag_multi_institution.py` | 시드 기준 시각을 `_FROZEN_NOW = datetime(2026, 10, 4, 12, 0, 0)` 로 고정하고 `query_planning.date` 를 `_FrozenDate` 로 고정 |
| `tests/test_kb_builder.py` | `_KB_REFERENCE_NOW = datetime(2026, 6, 2, 12, 0, 0)` 를 두고 `src.app.services.kb_builder.utcnow` 를 이 값으로 고정. 최근 1년 창이 시드 2026-06-01 을 항상 포함 |

`relative_to_today` 스냅샷 구조와 `as_of` 주입처럼 이미 실행 날짜와 무관하게 설계된 시험은 그대로 두었습니다.

---

## 5. 검증

수정 후 세 미래 시점 전량 시험이 모두 통과했습니다.

| 명령 | 결과 |
| --- | --- |
| `PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=30 uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short` | 6014 passed, 40 skipped, 3 deselected |
| `PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=90 uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short` | 6014 passed, 40 skipped, 3 deselected |
| `PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=365 uv run pytest tests/ -q -m 'not data_assets' -p date_bomb_plugin --tb=short` | 6014 passed, 40 skipped, 3 deselected |

수정 전후 고정 시험만 추린 재확인(모두 통과):

```sh
PYTHONPATH=/tmp/date_bomb_audit DATE_BOMB_OFFSET_DAYS=365 uv run pytest -q -p date_bomb_plugin \
  tests/test_monitor_catchup.py tests/test_query_planning.py \
  tests/test_rag_multi_institution.py tests/test_kb_builder.py
```

오늘 날짜 전량 시험과 규칙 검증:

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/ -q -m 'not data_assets' --tb=short` | 6014 passed, 40 skipped, 3 deselected |
| `uv run mypy src` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |

`src/` 변경은 0파일입니다.

---

## 6. 운영 코드 변경 없이는 못 고치는 항목

없습니다. 확정된 시험 5건 모두 시험 안 기준일 고정만으로 해결했고 `src/` 는 그대로입니다.

---

## 7. 비고와 한계

- 스윕 시점은 +30일, +90일, +365일입니다. 단조 창(최근 N일, 최근 1년)에서는 이 셋이 구간 내 모든 고정 날짜를 덮습니다.
- `datetime` 하위 클래스를 모듈 전역에 주입하면 `isinstance(x, datetime)` 판정이 깨질 수 있습니다. 메타클래스 `__instancecheck__` 로 실제 인스턴스를 통과시켜 `tests/test_mysql_stats_freshness_nightly.py` 의 거짓 실패를 제거했습니다. 이 시험은 DB 조회 시각을 쓰므로 진짜 시한폭탄이 아니었습니다.
- `tests/test_kb_builder.py` 의 메모리 회귀 시험(`test_memory_bound_proportional_to_chunk_size` 등)은 부하가 큰 전량 실행에서 자원 상태에 따라 드물게 흔들릴 수 있습니다. 시각과 무관한 자원 민감 시험이며 이번 조사 대상이 아닙니다.
- 플러그인과 스윕 로그는 `.orca/capsules/task_c1cac9dbb70e/scratch/` 에만 두고 커밋하지 않았습니다.
