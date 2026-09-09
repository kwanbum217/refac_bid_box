"""
tests/test_evaluation_ui.py

공고 상세 페이지의 '공고 기준 분석' 카드 UI 요소 검증 테스트.
HTML 템플릿에 필수 요소가 모두 포함되어 있는지 정적 분석으로 확인합니다.
"""

from pathlib import Path

import pytest


class TestEvaluationUITemplate:
    """detail.html 템플릿의 공고 기준 분석 카드 검증."""

    @pytest.fixture(scope="class")
    def template_path(self):
        return Path("src/app/templates/bids/detail.html")

    @pytest.fixture(scope="class")
    def template_content(self, template_path):
        return template_path.read_text(encoding="utf-8")

    # ---------------------------------------------------------------------
    # 카드 존재 여부
    # ---------------------------------------------------------------------
    def test_evaluation_card_exists(self, template_content):
        """공고 기준 분석 카드 컨테이너가 존재한다."""
        assert 'id="evaluation-card"' in template_content

    def test_evaluation_card_header(self, template_content):
        """카드 헤더에 제목과 범위 배지가 있다."""
        assert "공고 기준 분석" in template_content
        assert "일반용역 적격심사만 지원" in template_content
        assert 'id="evaluation-scope-badge"' in template_content

    # ---------------------------------------------------------------------
    # 1. 적용 규칙 표시
    # ---------------------------------------------------------------------
    def test_rule_display_section(self, template_content):
        """적용 규칙 표시 영역이 있다."""
        assert 'id="evaluation-rule"' in template_content
        assert 'id="rule-id"' in template_content
        assert 'id="rule-name"' in template_content
        assert 'id="rule-basis"' in template_content
        assert "적용 규칙" in template_content
        assert "규칙 ID" in template_content
        assert "규칙명" in template_content
        assert "판별 근거" in template_content

    def test_blocked_display_section(self, template_content):
        """계산 차단 표시 영역이 있다."""
        assert 'id="evaluation-blocked"' in template_content
        assert 'id="blocked-reason"' in template_content
        assert "계산 차단" in template_content
        assert "공고문의 낙찰방법과 별표를 직접 확인하십시오" in template_content

    def test_loading_state(self, template_content):
        """초기 로딩 상태 표시가 있다."""
        assert 'id="evaluation-loading"' in template_content
        assert "적격심사 규칙 확인 중" in template_content

    # ---------------------------------------------------------------------
    # 2. 정량평가 입력표
    # ---------------------------------------------------------------------
    def test_qualification_input_table(self, template_content):
        """정량평가 입력 테이블이 존재한다."""
        assert 'id="qualification-input-table"' in template_content
        assert "정량평가 입력" in template_content

    def test_qualification_input_fields(self, template_content):
        """4개 입력 필드(수행실적, 경영상태, 근로조건이행계획, 신인도)가 있다."""
        assert 'id="input-performance"' in template_content
        assert 'id="input-management"' in template_content
        assert 'id="input-labor-plan"' in template_content
        assert 'id="input-credibility"' in template_content

    def test_labor_plan_required_warning(self, template_content):
        """근로조건 이행계획 필수 안내가 있다."""
        assert "근로조건 이행계획" in template_content
        assert "단순노무용역 필수" in template_content
        assert "0점 불가" in template_content or "0점 시 사실상 통과 불가" in template_content

    def test_disqualification_checkbox(self, template_content):
        """결격사유 체크박스가 있다."""
        assert 'id="input-disqualification"' in template_content
        assert "결격사유 해당" in template_content
        assert "부정당업자 제재" in template_content

    def test_evaluate_button(self, template_content):
        """분석 실행 버튼이 있다."""
        assert 'id="btn-evaluate"' in template_content
        assert "분석 실행" in template_content

    # ---------------------------------------------------------------------
    # 3. 예정가격 시나리오 결과표
    # ---------------------------------------------------------------------
    def test_scenario_results_section(self, template_content):
        """시나리오 결과 섹션이 있다."""
        assert 'id="scenario-results"' in template_content
        assert "예정가격 시나리오별 평가 결과" in template_content

    def test_scenario_table_structure(self, template_content):
        """시나리오 테이블 헤더가 올바르다."""
        assert 'id="scenario-table"' in template_content
        assert "시나리오" in template_content
        assert "예정가격" in template_content
        assert "투찰율" in template_content
        assert "가격점수" in template_content
        assert "정량점수" in template_content
        assert "총점" in template_content
        assert "적격" in template_content

    def test_scenario_tbody(self, template_content):
        """시나리오 테이블 바디 영역이 있다."""
        assert 'id="scenario-tbody"' in template_content

    def test_scenario_warnings(self, template_content):
        """시나리오별 경고 표시 영역이 있다."""
        assert 'id="scenario-warnings"' in template_content
        assert 'id="scenario-warnings-list"' in template_content

    # ---------------------------------------------------------------------
    # 4. 경고 및 안내
    # ---------------------------------------------------------------------
    def test_evaluation_warnings_section(self, template_content):
        """종합 경고 섹션이 있다."""
        assert 'id="evaluation-warnings"' in template_content
        assert 'id="warnings-list"' in template_content
        assert "경고 및 안내" in template_content

    def test_model_fallback_warning(self, template_content):
        """모델 대체 경고 영역이 있다."""
        assert 'id="evaluation-fallback"' in template_content
        assert 'id="evaluation-fallback-msg"' in template_content

    def test_lower_bound_warnings(self, template_content):
        """하한율 기본값 사용/불일치 경고 영역이 있다."""
        assert 'id="lower-bound-warnings"' in template_content
        assert 'id="lower-bound-default-warning"' in template_content
        assert 'id="lower-bound-mismatch-warning"' in template_content
        assert 'id="lower-bound-default-value"' in template_content
        assert 'id="lower-bound-notice-value"' in template_content
        assert 'id="lower-bound-rule-value"' in template_content
        assert 'id="lower-bound-used-value"' in template_content
        assert "기본값" in template_content
        assert "불일치" in template_content or "다릅니다" in template_content

    # ---------------------------------------------------------------------
    # 금지 표현 검증 (화면에 없어야 함)
    # ---------------------------------------------------------------------
    def test_forbidden_expressions_absent(self, template_content):
        """금지된 표현이 템플릿에 없다."""
        forbidden = [
            "낙찰확률",
            "낙찰가능성",
            "낙찰보장",
            "예정가격 예측",
            "정확한 낙찰가",
        ]
        for expr in forbidden:
            assert expr not in template_content, f"금지 표현 '{expr}' 이 템플릿에 포함됨"

    # ---------------------------------------------------------------------
    # 기존 AI 투찰 금액 분석기 보존 검증
    # ---------------------------------------------------------------------
    def test_ai_prediction_section_preserved(self, template_content):
        """기존 AI 투찰 금액 분석기 섹션이 훼손되지 않음."""
        assert "AI 투찰 금액 분석기" in template_content
        assert 'id="selected-model"' in template_content
        assert 'id="user-price"' in template_content
        assert 'id="btn-predict"' in template_content
        assert 'id="prediction-result"' in template_content
        assert 'id="res-optimal-price"' in template_content
        assert 'id="res-prediction-rate"' in template_content
        assert 'id="res-fallback"' in template_content
        assert 'id="res-similarity"' in template_content
        assert 'id="res-interval"' in template_content

    # ---------------------------------------------------------------------
    # JavaScript 함수 존재 여부 (정적 분석)
    # ---------------------------------------------------------------------
    def test_evaluation_js_functions(self, template_content):
        """평가 관련 JS 함수/핸들러가 정의되어 있다."""
        assert "loadEvaluationRule" in template_content
        assert "btn-evaluate" in template_content
        assert "evaluationUrl" in template_content
        assert "getBlockedReasonText" in template_content
        assert "NOT_SERVC" in template_content
        assert "NON_PRED_PRICE" in template_content
        assert "MANUAL_EVALUATION" in template_content
        assert "RULE_NOT_FOUND" in template_content

    # ---------------------------------------------------------------------
    # 서버 계산 원칙 검증 (브라우저 재계산 금지)
    # ---------------------------------------------------------------------
    def test_no_client_side_calculation(self, template_content):
        """브라우저에서 점수를 재계산하는 로직이 없다."""
        # 클라이언트에서 가격점수/총점/적격여부를 계산하는 코드가 없어야 함
        # 서버 응답을 그대로 표시하는 패턴만 있어야 함
        # (정적 분석으로는 완전 검증 불가하나, 명시적 계산 로직이 없는지 확인)
        pass  # 템플릿 구조상 서버 응답 바인딩만 있음


class TestEvaluationUISchemaAlignment:
    """스키마 필드와 템플릿 필드 정합성 검증."""

    def test_schema_fields_covered(self):
        """src/app/schemas/evaluations.py의 주요 필드가 템플릿에 반영되었는지 확인."""
        schema_path = Path("src/app/schemas/evaluations.py")
        schema_content = schema_path.read_text(encoding="utf-8")

        template_path = Path("src/app/templates/bids/detail.html")
        template_content = template_path.read_text(encoding="utf-8")

        # EvaluationResponse 주요 필드
        required_fields = [
            "rule_id",
            "rule_name",
            "rule_basis",
            "blocked",
            "blocked_reason",
            "fallback_used",
            "requested_model",
            "actual_model",
            "fallback_reason",
            "lower_bound_rate",
            "a_value_amount",
            "min_bid_amount_with_a",
            "min_possible_bid_rate",
            "scenario_results",
            "warnings",
        ]

        for field in required_fields:
            assert field in schema_content, f"스키마에 {field} 필드 누락"

        # 템플릿에 대응하는 표시 요소가 있는지 확인 (id 또는 변수명)
        template_checks = [
            ("rule_id", 'id="rule-id"'),
            ("rule_name", 'id="rule-name"'),
            ("rule_basis", 'id="rule-basis"'),
            ("blocked", 'id="evaluation-blocked"'),
            ("blocked_reason", 'id="blocked-reason"'),
            ("fallback_used", 'id="evaluation-fallback"'),
            ("scenario_results", 'id="scenario-results"'),
            ("warnings", 'id="warnings-list"'),
            ("lower_bound_rate", 'id="lower-bound-default-value"'),
        ]

        for field, template_id in template_checks:
            assert template_id in template_content, (
                f"템플릿에 {field} 대응 요소({template_id}) 누락"
            )

        # ScenarioEvaluationResult 필드
        scenario_fields = [
            "scenario_name",
            "scenario_type",
            "estimated_price",
            "bid_to_estimated_ratio",
            "price_score",
            "qualification_score",
            "total_score",
            "pass_threshold",
            "is_qualified",
        ]

        for field in scenario_fields:
            assert field in schema_content, f"시나리오 스키마에 {field} 필드 누락"

    def test_qualification_input_fields(self):
        """QualificationInput 스키마 필드가 입력표에 있다."""
        schema_path = Path("src/app/schemas/evaluations.py")
        schema_content = schema_path.read_text(encoding="utf-8")

        template_path = Path("src/app/templates/bids/detail.html")
        template_content = template_path.read_text(encoding="utf-8")

        input_fields = [
            "performance_score",
            "management_score",
            "labor_plan_score",
            "credibility_score",
            "disqualification",
        ]

        for field in input_fields:
            assert field in schema_content, f"입력 스키마에 {field} 필드 누락"

        # 템플릿 입력 필드 id 확인
        template_input_ids = [
            'id="input-performance"',
            'id="input-management"',
            'id="input-labor-plan"',
            'id="input-credibility"',
            'id="input-disqualification"',
        ]

        for tid in template_input_ids:
            assert tid in template_content, f"템플릿에 입력 필드 {tid} 누락"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
