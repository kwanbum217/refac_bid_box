"""
tests/test_perf_unit_gate.py

CI 단위 성능 게이트(D-14). HTTP P95 게이트는 규약(600 표본, warmup, 주변 부하
실측)과 러너 성능 편차 때문에 CI 에 둘 수 없으므로, 결정적으로 재현되는 단위
지표를 추적 기준선(data/benchmarks/perf_unit_baseline.json)과 대조한다.

- 판정 지표(결정적): OpenAPI 경로·오퍼레이션 수, 특징 맵 키 집합 SHA256,
  Servc 학습 특징 수와 unservable_features 빈 목록, 홈 컨텍스트 질의 수 상한.
- 관측 지표(시간): 특징 구축 시간은 기준선 대조 없이 파탄 상한만 검사한다.
  wall-clock 은 러너에 따라 수 배씩 벌어지므로 판정에 쓰지 않는다.

기준선은 이 파일의 write_baseline() 으로 실측 생성한다:

    uv run python -c 'from tests.test_perf_unit_gate import write_baseline; write_baseline()'

의도한 변경(기능 추가 등)으로 지표가 움직였다면 위 명령으로 갱신하고,
docs/ops/latency_gate_protocol.md 9장의 갱신 조건(성능 근거 첨부)을 따른다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# pytest 밖에서(write_baseline 직접 호출) 임포트될 수 있으므로 tests/conftest.py 와
# 같은 환경 기본값을 src 임포트 전에 확정한다. SKIP_MODEL_LOAD 값은
# src/ml/model_registry.py 가 "true" 문자열로만 인정한다.
os.environ.setdefault("SKIP_MODEL_LOAD", "true")
os.environ.setdefault("EMBEDDING_PROVIDER", "default")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.services import home_context
from src.ml.features import build_default_feature_map, unservable_features
from src.ml.training_config import training_features_for_category

BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "benchmarks" / "perf_unit_baseline.json"
)

# 파탄 상한(관측 지표). 실측 평균 약 0.01ms 대비 100배 이상의 여유다. 이 값을
# 넘으면 러너나 코드 어딘가가 비정상이므로 원인 규명 전에는 판정 근거로 못 쓴다.
FEATURE_BUILD_PANIC_MS = 5.0

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

_UPDATE_HINT = (
    "의도한 변경이면 기준선을 갱신하십시오: "
    "uv run python -c 'from tests.test_perf_unit_gate import write_baseline; "
    "write_baseline()'"
)


# --------------------------------------------------------------------------- #
# 지표 산출과 기준선
# --------------------------------------------------------------------------- #


def _feature_map_set_sha256() -> str:
    """build_default_feature_map 키 집합(정렬)의 SHA256. 키 순서는 dict 삽입 순서와
    무관하게 정렬해서 잠근다."""
    keys = sorted(build_default_feature_map({}))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def compute_metrics() -> dict[str, Any]:
    """판정 지표를 현재 코드에서 다시 산출한다. DB 와 모델 가중치가 필요 없다."""
    paths = app.openapi()["paths"]
    operations = sum(
        1 for item in paths.values() for method in item if method.lower() in _HTTP_METHODS
    )
    servc_columns = training_features_for_category("Servc")
    return {
        "openapi_paths": len(paths),
        "openapi_operations": operations,
        "feature_map_key_count": len(build_default_feature_map({})),
        "feature_map_set_sha256": _feature_map_set_sha256(),
        "training_features_servc_count": len(servc_columns),
        "unservable_features": unservable_features(servc_columns),
        # 홈 한 번 = 공통 1회 + 분야별 len(DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)회
        # 선별이고, 각 선별은 표본 크기 수(HOME_RECENT_SAMPLE_SIZES)를 넘지 않는다.
        "home_context_query_ceiling": (
            (1 + len(home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES))
            * len(home_context.HOME_RECENT_SAMPLE_SIZES)
        ),
    }


def write_baseline(baseline_path: Path | str = BASELINE_PATH) -> dict[str, Any]:
    """현재 코드의 지표를 실측해 기준선 파일을 만들거나 갱신한다.

    git head 와 생성 시각은 metadata 로 기록할 뿐 판정에 쓰지 않는다. 절대 경로와
    비밀은 넣지 않는다.
    """
    path = Path(baseline_path)
    try:
        # 고정 명령이며 PATH 의 git 을 씁니다. CI 와 로컬 어디서나 존재합니다.
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - 고정 명령이며 PATH 의 git 을 씁니다
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_head = "unknown"
    payload = {
        "schema": "PERF_UNIT_BASELINE_V1",
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_head": git_head,
            "generated_by": (
                "uv run python -c 'from tests.test_perf_unit_gate import "
                "write_baseline; write_baseline()'"
            ),
        },
        **compute_metrics(),
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _load_baseline() -> dict[str, Any]:
    with BASELINE_PATH.open(encoding="utf-8") as file:
        baseline = json.load(file)
    assert baseline.get("schema") == "PERF_UNIT_BASELINE_V1", (
        "기준선 파일 형식이 다릅니다. " + _UPDATE_HINT
    )
    return baseline


def _assert_metric_matches_baseline(baseline: dict[str, Any], key: str) -> None:
    current = compute_metrics()[key]
    expected = baseline[key]
    assert current == expected, f"{key}: 기준선 {expected!r} != 현재 {current!r}. {_UPDATE_HINT}"


# --------------------------------------------------------------------------- #
# 판정 지표
# --------------------------------------------------------------------------- #


def test_openapi_surface_matches_baseline():
    """라우트 표면(경로·오퍼레이션 수)은 기준선과 같아야 한다."""
    baseline = _load_baseline()
    _assert_metric_matches_baseline(baseline, "openapi_paths")
    _assert_metric_matches_baseline(baseline, "openapi_operations")


def test_feature_map_key_set_matches_baseline():
    """특징 맵 키 집합은 기준선 해시와 같아야 한다. 특징 추가·삭제는 학습된 모델과의
    컬럼 계약을 바꾸므로 의도한 변경에서만 허용한다."""
    baseline = _load_baseline()
    _assert_metric_matches_baseline(baseline, "feature_map_key_count")
    _assert_metric_matches_baseline(baseline, "feature_map_set_sha256")


def test_servc_training_features_are_deployable():
    """Servc 학습 특징 전량이 features.py 가 만들어야 배포할 수 있다."""
    baseline = _load_baseline()
    _assert_metric_matches_baseline(baseline, "training_features_servc_count")
    _assert_metric_matches_baseline(baseline, "unservable_features")


def test_home_context_query_count_within_baseline_ceiling():
    """홈 컨텍스트 선별 질의 수는 기준선 상한 이하다.

    tests/test_home_context_query_count.py 와 같은 SQLite 인메모리 +
    SQLAlchemy 이벤트 방식으로 실측한다. 상한 자체는 home_context 상수에서
    결정적으로 유도되므로 기준선 대조의 판정 지표다.
    """
    baseline = _load_baseline()
    db = _new_session()
    _seed(db)
    selection_selects = _selection_select_count(db)

    assert selection_selects <= baseline["home_context_query_ceiling"], (
        f"홈 컨텍스트 선별 SELECT {selection_selects}회가 기준선 상한 "
        f"{baseline['home_context_query_ceiling']}회를 넘습니다. {_UPDATE_HINT}"
    )


# --------------------------------------------------------------------------- #
# 관측 지표(시간은 기준선 대조에 쓰지 않는다)
# --------------------------------------------------------------------------- #


def test_feature_build_time_below_panic_ceiling():
    """특징 구축 시간은 관측만 하고 폭넓은 파탄 상한만 검사한다."""
    iterations = 200
    started = time.perf_counter()
    for _ in range(iterations):
        build_default_feature_map({})
    mean_ms = (time.perf_counter() - started) / iterations * 1000
    assert mean_ms <= FEATURE_BUILD_PANIC_MS, (
        f"특징 구축 평균 {mean_ms:.3f}ms 가 파탄 상한 {FEATURE_BUILD_PANIC_MS}ms 를 "
        "넘습니다. 러너 부하가 아니라 코드 회귀인지 먼저 확인하십시오."
    )


# --------------------------------------------------------------------------- #
# 홈 컨텍스트 질의 수 계측 (tests/test_home_context_query_count.py 방식 축약판)
# --------------------------------------------------------------------------- #

_SEED_BASE_TIME = datetime(2026, 9, 20, 12, 0, 0)


def _new_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _seed(db: Session) -> None:
    """중복 키 압력이 있는 소규모 공고 행. BidResult 는 비워 둔다(빈 결과 조회 경로)."""
    specs = []
    for index in range(40):
        moment = _SEED_BASE_TIME - timedelta(minutes=index)
        specs.append(
            {
                "bid_ntce_no": f"ANN-{index // 2:04d}",
                "bid_ntce_ord": f"{index % 2:03d}",
                "bid_ntce_nm": f"공고 {index:04d}",
                "category": home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES[
                    index % len(home_context.DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES)
                ],
                "base_amount": 1_000_000 + index,
                "presmpt_prce": 990_000 + index,
                "bid_ntce_dt": moment,
                "collected_at": moment,
            }
        )
    db.add_all([BidAnnouncement(**spec) for spec in specs])
    db.commit()


def _selection_select_count(db: Session) -> int:
    """get_home_page_context 한 번의 최근 공고 선별 SELECT 수."""
    marker = f"{BidAnnouncement.__tablename__}.collected_at DESC"
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    connection = db.get_bind()
    event.listen(connection, "before_cursor_execute", record)
    try:
        home_context.get_home_page_context(db)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    return len([s for s in statements if marker in s])
