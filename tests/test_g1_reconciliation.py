"""
tests/test_g1_reconciliation.py

G1 무손실 검증 6단계: collected_at 기준 이행 원본/수집 성장분 분리 대조.

5단계 누적 하한 검사는 수집이 늘면 그대로 통과하므로, 이행 시점 유실을
수집 성장분이 가리는 결함이 있다. 이 테스트 묶음은 운영 read-only 경로인
`verify_reconciliation` 의 분기 6가지를 SQLite 인메모리 픽스처로 검증한다.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scripts import verify_migration
from src.app.core.db import Base
from src.app.models import bids as bids_models
from src.app.models.bids import BidAnnouncement, BidResult

CUTOVER_TS = verify_migration.MIGRATION_CUTOVER_TS
assert CUTOVER_TS.tzinfo is not None, "이행 시점 경계는 tz-aware 여야 한다"


@pytest.fixture
def recon_engine():
    """SQLite 인메모리 DB 위에 G1 reconciliation 검증용 테이블을 만듭니다.

    `Base.metadata.create_all` 만 수행하며 DDL 외 DML 은 테스트가 직접
    insert 한다. 운영 경로(SessionLocal) 와 분리된 픽스처다.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def recon_session(recon_engine):
    """recon_engine 에 바인딩된 sessionmaker."""
    factory = sessionmaker(bind=recon_engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _add_announcement(
    session, *, collected_at: datetime, idx: int, prefix: str = "ANN"
) -> BidAnnouncement:
    # (bid_ntce_no, bid_ntce_ord, category) UNIQUE 제약조건을 지키기 위해
    # category 와 ord_suffix 를 함께 분산한다. 같은 픽스처 안에서 같은
    # prefix 의 idx 가 중복되면 충돌하므로 호출자가 prefix 를 다르게
    # 주거나 인덱스 범위를 분리한다.
    categories = ("Thng", "Cnstwk", "Servc", "Frgcpt")
    category = categories[idx % len(categories)]
    ord_suffix = f"{(idx // len(categories)) % 1000:03d}"
    obj = BidAnnouncement(
        bid_ntce_no=f"{prefix}-{idx:08d}",
        bid_ntce_ord=ord_suffix,
        category=category,
        collected_at=collected_at,
    )
    session.add(obj)
    return obj


def _add_result(session, *, collected_at: datetime, idx: int, prefix: str = "RES") -> BidResult:
    categories = ("Thng", "Cnstwk", "Servc", "Frgcpt")
    category = categories[idx % len(categories)]
    ord_suffix = f"{(idx // len(categories)) % 1000:02d}"
    obj = BidResult(
        bid_ntce_no=f"{prefix}-{idx:08d}",
        bid_ntce_ord=ord_suffix,
        category=category,
        collected_at=collected_at,
    )
    session.add(obj)
    return obj


def _write_reconciliation_baseline(path: Path, tables: dict[str, int], engine) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "cutover_timestamp": CUTOVER_TS.isoformat(),
                "tables": tables,
                "metadata": verify_migration.build_source_metadata(engine),
            }
        ),
        encoding="utf-8",
    )


def test_reconciliation_creates_baseline_and_passes(tmp_path, recon_session):
    """기준선 부재는 FAIL 하고 명시적 생성 후 검증은 PASS 한다."""
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"
    assert not baseline_path.exists()

    # 원본 3행 + 성장분 1행(영향 없어야 함)
    for i in range(3):
        _add_announcement(recon_session, collected_at=CUTOVER_TS - timedelta(hours=1), idx=i)
    for i in range(2):
        _add_result(recon_session, collected_at=CUTOVER_TS - timedelta(hours=1), idx=i)
    _add_announcement(recon_session, collected_at=CUTOVER_TS + timedelta(hours=1), idx=99)
    recon_session.commit()

    session_factory = sessionmaker(bind=recon_session.get_bind())
    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
        auto_save_baseline=True,
    )

    assert ok is False
    assert "기준선 파일 없음" in msg
    assert not baseline_path.exists()

    generated, generated_msg = verify_migration.generate_reconciliation_baseline(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )

    assert generated is True
    assert "기준선 생성 완료" in generated_msg
    assert baseline_path.exists()
    saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert saved["cutover_timestamp"] == CUTOVER_TS.isoformat()
    assert saved["tables"]["bid_announcements"] == 3
    assert saved["tables"]["bid_results"] == 2
    assert "metadata" in saved

    ok2, msg2 = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )
    assert ok2 is True
    assert "원본/성장분 대조 일치" in msg2


def test_reconciliation_passes_when_baseline_matches(tmp_path, recon_session):
    """명시적으로 생성한 baseline과 일치하면 PASS 한다."""
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"

    for i in range(5):
        _add_announcement(recon_session, collected_at=CUTOVER_TS - timedelta(minutes=10), idx=i)
    for i in range(4):
        _add_result(recon_session, collected_at=CUTOVER_TS - timedelta(minutes=10), idx=i)
    recon_session.commit()

    session_factory = sessionmaker(bind=recon_session.get_bind())
    generated, generated_msg = verify_migration.generate_reconciliation_baseline(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )
    assert generated is True
    assert "기준선 생성 완료" in generated_msg

    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )

    assert ok is True
    assert "원본/성장분 대조 일치" in msg


def test_reconciliation_rejects_baseline_without_metadata(tmp_path, recon_session):
    """출처 메타데이터가 없는 baseline은 DB 대조 전에 거부한다."""
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "cutover_timestamp": CUTOVER_TS.isoformat(),
                "tables": {"bid_announcements": 0, "bid_results": 0},
            }
        ),
        encoding="utf-8",
    )
    session_factory = sessionmaker(bind=recon_session.get_bind())

    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )

    assert ok is False
    assert "기준선 메타데이터 누락" in msg


def test_reconciliation_fails_when_original_rows_decrease(tmp_path, recon_session):
    """이행 원본 행이 줄면 즉시 FAIL 한다(가장 중요한 단언)."""
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"
    _write_reconciliation_baseline(
        baseline_path,
        {"bid_announcements": 10, "bid_results": 10},
        recon_session.get_bind(),
    )

    # 원본 5행만 남긴다(baseline 10행 대비 5행 부족)
    for i in range(5):
        _add_announcement(recon_session, collected_at=CUTOVER_TS - timedelta(hours=2), idx=i)
    for i in range(5):
        _add_result(recon_session, collected_at=CUTOVER_TS - timedelta(hours=2), idx=i)
    recon_session.commit()

    session_factory = sessionmaker(bind=recon_session.get_bind())
    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )

    assert ok is False
    assert "이행 원본 행 수 부족" in msg
    assert "bid_announcements" in msg


def test_reconciliation_ignores_growth_rows(tmp_path, recon_session, capsys):
    """수집으로 행이 늘어도(collected_at >= cutover) 검증은 PASS 한다.

    이 단언이 '수집 성장분이 가리지 않음'의 핵심이다. baseline 이 3/3 일 때
    원본 3행을 유지하면서 성장분 1,000행을 추가해도 PASS 여야 한다.
    """
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"
    _write_reconciliation_baseline(
        baseline_path,
        {"bid_announcements": 3, "bid_results": 3},
        recon_session.get_bind(),
    )

    for i in range(3):
        _add_announcement(
            recon_session, collected_at=CUTOVER_TS - timedelta(minutes=1), idx=i, prefix="ORIG-A"
        )
        _add_result(
            recon_session, collected_at=CUTOVER_TS - timedelta(minutes=1), idx=i, prefix="ORIG-R"
        )
    # 성장분 1,000행 — 누적은 늘지만 원본은 그대로여야 PASS.
    # prefix 를 다르게 두어 UNIQUE(bid_ntce_no, bid_ntce_ord, category) 충돌을 피한다.
    for i in range(1000):
        _add_announcement(
            recon_session,
            collected_at=CUTOVER_TS + timedelta(seconds=1),
            idx=i,
            prefix="GROW-A",
        )
    recon_session.commit()

    session_factory = sessionmaker(bind=recon_session.get_bind())
    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )
    captured = capsys.readouterr()

    assert ok is True
    assert "원본/성장분 대조 일치" in msg
    # 성장분 관측값은 stdout 의 [6/6] 출력에 들어간다(관측 의무).
    assert "성장분 1,000행" in captured.out


def test_reconciliation_fails_when_db_session_factory_raises(tmp_path):
    """DB 조회 자체가 실패하면 FAIL 로 보고한다(통과로 위장 금지)."""

    def _raising_session_factory():
        class _Session:
            def __enter__(self):  # pragma: no cover - 호환용
                return self

            def __exit__(self, *exc):  # pragma: no cover - 호환용
                return False

            def execute(self, *args, **kwargs):
                raise RuntimeError("DB 연결 실패 (테스트 픽스처)")

        return _Session()

    baseline_path = tmp_path / "nope.json"
    _write_reconciliation_baseline(
        baseline_path,
        {"bid_announcements": 1, "bid_results": 1},
        None,
    )

    ok, msg = verify_migration.verify_reconciliation(
        session_factory=_raising_session_factory,
        baseline_path=baseline_path,
    )

    assert ok is False
    assert "DB 조회 실패" in msg
    # 통과로 위장하지 않음을 확인 — 메시지에 '건너뜀'이나 '신규 기록'이
    # 포함되면 안 된다.
    assert "건너뜀" not in msg
    assert "신규 기록" not in msg


def test_reconciliation_skips_when_db_is_empty(tmp_path, recon_session, capsys):
    """두 테이블 모두 누적 0행이면 'DB 가 비어있어 건너뜀' 메시지로 PASS 한다.

    빈 DB 자체의 판정은 5단계가 담당하며, 6단계는 baseline 대조가 무의미함을
    알리고 단언 가능한 신호만 남긴다.
    """
    baseline_path = tmp_path / "row_count_reconciliation_baseline.json"

    session_factory = sessionmaker(bind=recon_session.get_bind())
    generated, generated_msg = verify_migration.generate_reconciliation_baseline(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )
    assert generated is True
    assert "기준선 생성 완료" in generated_msg

    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )

    assert ok is True
    assert "DB 가 비어있어" in msg
    assert "건너뜀" in msg
    # 명시적 생성 경로가 만든 baseline은 검증 경로에서 유지되어야 한다.
    assert baseline_path.exists()

    captured = capsys.readouterr()
    assert "DB 가 비어있어 reconciliation 건너뜀" in captured.out


def test_reconciliation_does_not_run_ddl_or_dml(tmp_path, recon_session):
    """read-only 검증: 운영 경로가 DDL 이나 DML 을 실행하지 않음을 단언한다.

    `verify_reconciliation` 이 기준선을 읽는 검증 경로에서 DB에 어떤 변경도
    가하지 않음을 확인한다. 기준선은 명시적 생성 경로로 먼저 만들며, 검증
    경로가 해당 파일을 수정하지 않는지도 함께 확인합니다.
    """
    baseline_path = tmp_path / "outside_db" / "row_count_reconciliation_baseline.json"
    for i in range(2):
        _add_announcement(recon_session, collected_at=CUTOVER_TS - timedelta(hours=1), idx=i)
    for i in range(2):
        _add_result(recon_session, collected_at=CUTOVER_TS - timedelta(hours=1), idx=i)
    recon_session.commit()

    initial_ann = recon_session.query(BidAnnouncement).count()
    initial_res = recon_session.query(BidResult).count()

    session_factory = sessionmaker(bind=recon_session.get_bind())
    generated, generated_msg = verify_migration.generate_reconciliation_baseline(
        session_factory=session_factory,
        baseline_path=baseline_path,
    )
    assert generated is True
    assert "기준선 생성 완료" in generated_msg
    before_baseline = baseline_path.read_text(encoding="utf-8")

    ok, msg = verify_migration.verify_reconciliation(
        session_factory=session_factory,
        baseline_path=baseline_path,
        auto_save_baseline=True,
    )
    assert ok is True
    assert "원본/성장분 대조 일치" in msg

    # DB 행 수는 그대로여야 한다(read-only).
    assert recon_session.query(BidAnnouncement).count() == initial_ann
    assert recon_session.query(BidResult).count() == initial_res
    # 명시적 생성 경로의 baseline은 검증 경로에서 변경되지 않는다.
    assert baseline_path.exists()
    assert baseline_path.read_text(encoding="utf-8") == before_baseline


def test_reconciliation_baseline_path_constant_is_single_source():
    """이행 시점 경계가 여러 곳에 하드코딩되지 않고 한 곳에서 나온 값인지.

    Capsule 금지 조항이다. MIGRATION_CUTOVER_TS 와 MIGRATION_CUTOVER_BASELINE_PATH
    가 verify_migration 모듈에서 단일 정본이며, 동일 모듈 안에서 다른
    정의를 갖지 않음을 단언한다.
    """
    import scripts.verify_migration as mod

    assert isinstance(mod.MIGRATION_CUTOVER_TS, datetime)
    assert mod.MIGRATION_CUTOVER_TS.tzinfo is not None
    assert isinstance(mod.MIGRATION_CUTOVER_BASELINE_PATH, Path)
    # baseline 파일은 스키마 서명 baseline 과 같은 디렉터리에 둔다
    # (스키마 서명 baseline 의 패턴을 따른다).
    assert mod.MIGRATION_CUTOVER_BASELINE_PATH.parent == mod.SCHEMA_BASELINE_PATH.parent
    # 모듈 안에 동일 이름의 다른 정의가 없는지(한 곳에 모였는지) 확인.
    # 패턴은 실제 정의 형태(MIGRATION_CUTOVER_TS: datetime = ...)와 같다.
    source = Path(mod.__file__).read_text(encoding="utf-8")
    ts_def_count = source.count("MIGRATION_CUTOVER_TS:")
    path_def_count = source.count("MIGRATION_CUTOVER_BASELINE_PATH:")
    assert ts_def_count == 1, f"MIGRATION_CUTOVER_TS 정의가 {ts_def_count}건 발견"
    assert path_def_count == 1, f"MIGRATION_CUTOVER_BASELINE_PATH 정의가 {path_def_count}건 발견"


# 모듈 로드 검증 — 운영 import 가 깨지지 않는지.
def test_verify_migration_module_imports_cleanly():
    """스크립트가 운영 경로에서 import 가능함을 보장한다."""
    assert hasattr(verify_migration, "verify_reconciliation")
    assert hasattr(verify_migration, "MIGRATION_CUTOVER_TS")
    assert hasattr(verify_migration, "MIGRATION_CUTOVER_BASELINE_PATH")
    assert hasattr(verify_migration, "_count_rows_by_cutover")
    # 모델 모듈이 import 되어야 한다.
    assert hasattr(bids_models, "BidAnnouncement")
    assert hasattr(bids_models, "BidResult")
    # 격리 워크트리 의존성 보강: 모듈이 import 가능한지.
    assert "scripts.verify_migration" in sys.modules
