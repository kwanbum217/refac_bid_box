"""
tests/test_evaluation_models.py

적격심사 정량평가 ORM 모델, Pydantic 스키마, Alembic 마이그레이션 정의 검증 테스트.
- G1 데이터 무손실: 기존 테이블 변경 없음, 신규 테이블만 추가
- 재현 가능성: rule_id, input_json, result_json 보존
- 소유권 강제: user_id 인덱스 및 식별
- 증빙 메타데이터 전용: 파일 경로/바이너리 컬럼 부재 검증
- 입출력 스키마: 근로조건 이행계획 점수 포함, 응답 필수 필드 완비
- 금지어 검증: '낙찰확률', '낙찰보장', '예정가격 예측' 미사용 확인
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

from sqlalchemy import (
    create_engine,
    select,
)
from sqlalchemy.orm import sessionmaker

from src.app.core.db import Base
from src.app.models.evaluations import (
    BidEvaluationEvidence,
    BidEvaluationProfile,
    BidEvaluationSnapshot,
)
from src.app.schemas.evaluations import (
    EvaluationRequest,
    EvaluationResponse,
    PriceScenarioConfig,
    QualificationInput,
    ScenarioEvaluationResult,
)

# ============================================================================
# 1. ORM 모델 테이블 정의 및 컬럼 무결성 검증
# ============================================================================


def test_evaluation_table_names() -> None:
    """신규 3개 테이블이 Base.metadata에 올바른 이름으로 등록되어 있는지 검증."""
    table_names = set(Base.metadata.tables.keys())
    assert "bid_evaluation_profiles" in table_names
    assert "bid_evaluation_snapshots" in table_names
    assert "bid_evaluation_evidence" in table_names


def test_profile_table_columns_and_ownership() -> None:
    """bid_evaluation_profiles 컬럼 및 user_id 소유권 인덱스 검증."""
    table = Base.metadata.tables["bid_evaluation_profiles"]
    column_names = {c.name for c in table.columns}
    expected_columns = {
        "id",
        "user_id",
        "name",
        "framework",
        "input_schema_version",
        "input_json",
        "created_at",
        "updated_at",
    }
    assert expected_columns.issubset(column_names)

    # user_id 인덱스 존재 확인
    index_columns = [[col.name for col in idx.columns] for idx in table.indexes]
    assert any("user_id" in cols for cols in index_columns)

    # user_id 소유권 제약 (user_id, name 유니크 제약 확인)
    unique_constraints = [
        [col.name for col in uc.columns] for uc in table.constraints if hasattr(uc, "columns")
    ]
    assert any(set(cols) == {"user_id", "name"} for cols in unique_constraints)


def test_snapshot_table_columns_and_reproducibility() -> None:
    """bid_evaluation_snapshots 테이블이 재현에 필요한 필드를 온전히 담는지 검증."""
    table = Base.metadata.tables["bid_evaluation_snapshots"]
    column_names = {c.name for c in table.columns}
    expected_columns = {
        "id",
        "bid_id",
        "user_id",
        "rule_id",
        "model_id",
        "model_version",
        "input_json",
        "result_json",
        "created_at",
    }
    assert expected_columns.issubset(column_names)

    # user_id 인덱스 및 bid_id 인덱스 확인
    index_columns = [[col.name for col in idx.columns] for idx in table.indexes]
    assert any("user_id" in cols for cols in index_columns)
    assert any("bid_id" in cols for cols in index_columns)
    assert any("rule_id" in cols for cols in index_columns)


def test_evidence_table_metadata_only_no_file_columns() -> None:
    """증빙 테이블에 파일 경로나 바이너리 컬럼이 일절 없음을 엄격히 검증."""
    table = Base.metadata.tables["bid_evaluation_evidence"]
    column_names = {c.name for c in table.columns}
    expected_columns = {
        "id",
        "snapshot_id",
        "item_code",
        "issuer",
        "reference_no",
        "valid_from",
        "valid_to",
        "note",
    }
    assert column_names == expected_columns

    # 파일 관련 컬럼이 없음을 명시적으로 확인
    forbidden_col_keywords = ["file", "path", "binary", "data_blob", "attachment", "url", "upload"]
    for col in column_names:
        for keyword in forbidden_col_keywords:
            assert keyword not in col.lower(), (
                f"증빙 테이블에 파일 관련 컬럼({col})이 포함되어서는 안 됩니다."
            )


# ============================================================================
# 2. Pydantic 스키마 검증
# ============================================================================


def test_qualification_input_contains_labor_plan_score() -> None:
    """근로조건 이행계획 점수가 스키마에 반드시 포함되어야 함."""
    schema_fields = QualificationInput.model_fields
    assert "labor_plan_score" in schema_fields
    assert "performance_score" in schema_fields
    assert "management_score" in schema_fields
    assert "credibility_score" in schema_fields
    assert "disqualification" in schema_fields
    assert "evidence_date" in schema_fields

    # 인스턴스 생성 및 기본값 테스트
    q_input = QualificationInput(
        performance_score=20.0,
        management_score=10.0,
        labor_plan_score=5.0,
        credibility_score=0.0,
        disqualification=False,
    )
    assert q_input.labor_plan_score == 5.0
    assert q_input.disqualification is False


def test_evaluation_request_schema() -> None:
    """분석 요청 스키마 유효성 및 필수 필드 검증."""
    req_fields = EvaluationRequest.model_fields
    assert "bid_id" in req_fields
    assert "selected_model" in req_fields
    assert "candidate_bid_amount" in req_fields
    assert "qualification_input" in req_fields
    assert "price_scenarios" in req_fields

    req = EvaluationRequest(
        bid_id=12345,
        candidate_bid_amount=95000000,
        qualification_input=QualificationInput(
            performance_score=18.5,
            management_score=9.5,
            labor_plan_score=5.0,
        ),
        price_scenarios=[
            PriceScenarioConfig(
                scenario_name="기준",
                scenario_type="base",
                estimated_price=100000000,
            )
        ],
    )
    assert req.bid_id == 12345
    assert req.candidate_bid_amount == 95000000
    assert req.qualification_input.labor_plan_score == 5.0
    assert len(req.price_scenarios or []) == 1


def test_evaluation_response_schema() -> None:
    """분석 응답 스키마가 rule_id, 판별 근거, 차단 사유, 모델 출처, 시나리오별 결과를 담는지 검증."""
    res_fields = EvaluationResponse.model_fields
    required_keys = {
        "status",
        "rule_id",
        "rule_basis",
        "blocked",
        "blocked_reason",
        "requested_model",
        "actual_model",
        "fallback_used",
        "scenario_results",
        "warnings",
    }
    assert required_keys.issubset(set(res_fields.keys()))

    res = EvaluationResponse(
        status="success",
        rule_id="servc_facility_under_500m",
        rule_name="시설분야용역 적격심사 추정가격 5억원 미만",
        rule_basis="raw_data.sucsfbidMthdNm 문자열 매칭",
        blocked=False,
        requested_model="catboost_servc_v1",
        actual_model="catboost_servc_v1",
        fallback_used=False,
        base_rate=89.995,
        lower_bound_rate=89.995,
        a_value_amount=3500000,
        min_bid_amount_with_a=90495250,
        min_possible_bid_rate=89.995,
        scenario_results=[
            ScenarioEvaluationResult(
                scenario_name="기준",
                scenario_type="base",
                estimated_price=100000000,
                bid_to_estimated_ratio=0.8999,
                price_score=69.95,
                qualification_score=25.0,
                total_score=94.95,
                pass_threshold=95.0,
                is_qualified=False,
                warnings=["통과 기준 95점에 0.05점 미달"],
            )
        ],
        warnings=["공고 하한율 기본값 적용"],
    )
    assert res.rule_id == "servc_facility_under_500m"
    assert res.blocked is False
    assert len(res.scenario_results) == 1
    assert res.scenario_results[0].is_qualified is False


def test_forbidden_words_in_schemas_and_models() -> None:
    """'낙찰확률', '낙찰보장', '예정가격 예측' 단어가 필드명, 설명, docstring에 포함되지 않음을 검증."""
    import src.app.models.evaluations as models_mod
    import src.app.schemas.evaluations as schemas_mod

    forbidden_terms = ["낙찰확률", "낙찰보장", "예정가격 예측"]

    # schemas 소스코드 검사
    schemas_source = inspect.getsource(schemas_mod)
    for term in forbidden_terms:
        assert term not in schemas_source, f"스키마에 금지어 '{term}'가 포함되어 있습니다."

    # models 소스코드 검사
    models_source = inspect.getsource(models_mod)
    for term in forbidden_terms:
        assert term not in models_source, f"모델에 금지어 '{term}'가 포함되어 있습니다."


# ============================================================================
# 3. Alembic 마이그레이션 파일 정합성 검증
# ============================================================================


def test_migration_file_specifications() -> None:
    """마이그레이션 파일의 리비전 체인, 신규 테이블 생성, downgrade 역순 삭제 검증."""
    migration_path = Path("migrations/versions/f8a9b0c1d2e3_add_bid_evaluation_tables.py")
    assert migration_path.exists(), "마이그레이션 파일이 존재해야 합니다."

    content = migration_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    # revision 및 down_revision 변수 확인
    revisions = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in ("revision", "down_revision")
                    and isinstance(stmt.value, ast.Constant)
                ):
                    revisions[target.id] = stmt.value.value
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id in ("revision", "down_revision")
            and isinstance(stmt.value, ast.Constant)
        ):
            revisions[stmt.target.id] = stmt.value.value

    assert revisions.get("revision") == "f8a9b0c1d2e3"
    assert revisions.get("down_revision") == "e7f8a9b0c1d2"

    # 기존 테이블 ALTER (alter_table, add_column 등)가 없음을 확인
    assert "alter_table" not in content
    assert "op.add_column" not in content
    assert "op.drop_column" not in content

    # 신규 3개 테이블 생성 호출 확인
    assert "bid_evaluation_profiles" in content
    assert "bid_evaluation_snapshots" in content
    assert "bid_evaluation_evidence" in content


# ============================================================================
# 4. SQLite 메모리 DB 실기 CRUD 및 관계 동작 검증
# ============================================================================


def test_sqlite_in_memory_crud_and_reproducibility() -> None:
    """메모리 DB에서 프로필, 스냅샷, 증빙의 실제 저장 및 재현 기능 검증."""
    engine = create_engine("sqlite:///:memory:")

    # 필요 테이블만 메타데이터에서 골라 생성 (외부 테이블 의존 없이 독립 검증)
    target_tables = [
        Base.metadata.tables["bid_evaluation_profiles"],
        Base.metadata.tables["bid_evaluation_snapshots"],
        Base.metadata.tables["bid_evaluation_evidence"],
    ]
    Base.metadata.create_all(engine, tables=target_tables)

    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        # 1. 프로필 생성 및 저장
        profile = BidEvaluationProfile(
            user_id=42,
            name="기본 시설관리 평가 세팅",
            framework="servc_qualification",
            input_schema_version="1.0",
            input_json={
                "performance_score": 20.0,
                "management_score": 10.0,
                "labor_plan_score": 5.0,
                "credibility_score": 0.0,
            },
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)

        assert profile.id is not None
        assert profile.user_id == 42
        assert profile.input_json["labor_plan_score"] == 5.0

        # 2. 분석 스냅샷 및 증빙 생성 (재현 가능성 확인)
        snapshot_inputs = {
            "bid_id": 999,
            "candidate_bid_amount": 91500000,
            "qualification_input": {
                "performance_score": 20.0,
                "management_score": 10.0,
                "labor_plan_score": 5.0,
                "credibility_score": 0.0,
                "disqualification": False,
            },
        }
        snapshot_results = {
            "rule_id": "servc_facility_under_500m",
            "base_rate": 89.995,
            "total_score": 95.0,
            "is_qualified": True,
        }

        snapshot = BidEvaluationSnapshot(
            bid_id=999,
            user_id=42,
            rule_id="servc_facility_under_500m",
            model_id="catboost_servc_v1",
            model_version="2026.09.01",
            input_json=snapshot_inputs,
            result_json=snapshot_results,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        # 3. 증빙 메타데이터 첨부
        evidence = BidEvaluationEvidence(
            snapshot_id=snapshot.id,
            item_code="performance",
            issuer="한국소프트웨어산업협회",
            reference_no="KOSA-2026-0909",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            note="이행실적 확인서",
        )
        session.add(evidence)
        session.commit()

        # 4. 재현 대조 쿼리
        stmt = select(BidEvaluationSnapshot).where(BidEvaluationSnapshot.id == snapshot.id)
        loaded = session.scalars(stmt).one()
        assert loaded.rule_id == "servc_facility_under_500m"
        assert loaded.input_json == snapshot_inputs
        assert loaded.result_json == snapshot_results
        assert len(loaded.evidence_items) == 1
        assert loaded.evidence_items[0].reference_no == "KOSA-2026-0909"

        # 5. 캐스케이드 삭제 검증
        session.delete(loaded)
        session.commit()

        ev_stmt = select(BidEvaluationEvidence).where(
            BidEvaluationEvidence.snapshot_id == snapshot.id
        )
        assert session.scalars(ev_stmt).first() is None
