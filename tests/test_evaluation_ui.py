"""
tests/test_evaluation_ui.py

공고 상세 페이지의 '공고 기준 분석' 카드 UI 요소 검증 테스트.
HTML 템플릿에 필수 요소가 모두 포함되어 있는지 정적 분석으로 확인합니다.
"""

import re
from pathlib import Path

import pytest


class TestEvaluationUITemplate:
    """detail.html 템플릿의 공고 기준 분석 카드 검증."""

    @pytest.fixture(scope="class")
    @classmethod
    def template_path(cls):
        return Path("src/app/templates/bids/detail.html")

    @pytest.fixture(scope="class")
    @classmethod
    def template_content(cls, template_path):
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
        """정량평가 입력은 적용 별표 규칙 선언으로 그려지고 배점이 하드코딩되어 있지 않다."""
        assert 'id="quant-attachment"' in template_content
        assert 'id="quant-band-note"' in template_content
        assert 'id="qualification-tbody"' in template_content
        assert 'id="reputation-section"' in template_content
        assert "renderQuantInputs" in template_content
        # 고정 입력란과 단일 가감점 표기(플러스마이너스 5.00)가 사라졌다.
        assert 'id="input-performance"' not in template_content
        assert 'id="input-management"' not in template_content
        assert 'id="input-labor-plan"' not in template_content
        assert 'id="input-credibility"' not in template_content
        assert "\u00b15.00" not in template_content

    def test_labor_plan_is_declared_not_hardcoded(self, template_content):
        """근로조건 이행계획은 별표 2 전용 항목이라 정적으로 고정하지 않고 서버 선언으로 그린다."""
        # 항목명·입력란은 서버 배점표(band.items)에서 만들고 화면에 고정하지 않는다.
        assert "labor_plan" not in template_content
        assert "근로조건 이행계획" not in template_content
        assert "data-quant-item" in template_content
        assert "단순노무용역" in template_content

    def test_disqualification_checkbox_removed(self, template_content):
        """결격사유 체크박스는 제거됐다. 서버가 '미확인'으로 계산한다."""
        assert 'id="input-disqualification"' not in template_content
        assert "결격사유 해당" not in template_content

    def test_evaluate_button_removed(self, template_content):
        """분석 실행 버튼과 내 투찰 금액 입력은 제거됐다. 진입 시 자동으로 계산한다."""
        assert 'id="btn-evaluate"' not in template_content
        assert 'id="btn-predict"' not in template_content
        assert 'id="user-price"' not in template_content
        assert "분석 실행" not in template_content

    # ---------------------------------------------------------------------
    # 3. 예정가격 시나리오 결과표는 추천 계산으로 대체되어 제거됐다
    # ---------------------------------------------------------------------
    def test_scenario_results_removed(self, template_content):
        """/analyze 전용 시나리오 결과표는 제거됐다. 세 금액(최저가·AI 예측가·최상가)이 대체한다."""
        assert 'id="scenario-results"' not in template_content
        assert 'id="scenario-tbody"' not in template_content
        assert "예정가격 시나리오별 평가 결과" not in template_content

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
    def test_ai_prediction_section_reused_for_three_amounts(self, template_content):
        """기존 AI 투찰 금액 분석기 카드가 세 금액 카드로 재사용된다."""
        assert "AI 투찰 금액 분석기" in template_content
        assert 'id="selected-model"' in template_content
        assert 'id="prediction-result"' in template_content
        assert 'id="res-min-price"' in template_content
        assert 'id="res-optimal-price"' in template_content
        assert 'id="res-max-price"' in template_content
        assert 'id="res-prediction-rate"' in template_content
        assert 'id="res-fallback"' in template_content
        # 예측 구간·입력 투찰가 근접도는 제거됐다.
        assert 'id="res-interval"' not in template_content
        assert 'id="res-similarity"' not in template_content

    def test_evaluation_card_is_below_ai_card(self, template_content):
        """공고 기준 분석 카드는 기존 AI 분석기 아래에 배치된다."""
        prediction_end = template_content.index('id="prediction-result"')
        evaluation_start = template_content.index('id="evaluation-card"')
        sidebar_start = template_content.index("Right Column: Sidebar")

        assert prediction_end < evaluation_start < sidebar_start

    def test_prediction_script_has_no_duplicate_or_invalid_helpers(self, template_content):
        """기존 AI 스크립트의 중복 선언과 평가 스크립트 문법 오류가 없다."""
        assert template_content.count("const currencyFormatter") == 1
        assert template_content.count("function escapeHtml") == 1
        assert "precededBy" not in template_content
        assert "candidate_bid_amount: 0" not in template_content

    # ---------------------------------------------------------------------
    # JavaScript 함수 존재 여부 (정적 분석)
    # ---------------------------------------------------------------------
    def test_evaluation_js_functions(self, template_content):
        """추천 자동 계산 관련 JS 함수/핸들러가 정의되어 있다."""
        assert "requestRecommend" in template_content
        assert "scheduleRecommend" in template_content
        assert "recommendUrl" in template_content
        assert "renderRecommendAmounts" in template_content
        assert "getBlockedReasonText" in template_content
        assert "NOT_SERVC" in template_content
        assert "NON_PRED_PRICE" in template_content
        assert "MANUAL_EVALUATION" in template_content
        assert "RULE_NOT_FOUND" in template_content

    # ---------------------------------------------------------------------
    # 서버 계산 원칙 검증 (브라우저 재계산 금지)
    # ---------------------------------------------------------------------
    def test_no_client_side_calculation(self, template_content):
        """브라우저가 세 금액과 점수를 다시 계산하지 않는다."""
        script_match = re.search(r"<script>(.*?)</script>", template_content, re.DOTALL)
        assert script_match, "평가 스크립트 영역을 찾을 수 없음"
        script = script_match.group(1)

        # 추천 결과의 수치 필드는 서버가 계산한 값을 그대로 표시해야 한다.
        # 필드 바로 뒤에 산술 연산자가 붙으면 브라우저 재계산으로 간주한다.
        server_calculated_fields = (
            "data.max_price_score",
            "data.non_price_score",
            "data.pass_threshold",
            "data.required_price_score",
            "bounds.min_bid_amount",
            "bounds.max_bid_amount",
            "bounds.rate_low_percent",
            "bounds.rate_high_percent",
            "prediction.optimal_price",
            "data.participant_stats.average",
        )
        arithmetic_pattern = re.compile(
            r"(?P<field>" + "|".join(map(re.escape, server_calculated_fields)) + r")\s*[*/+-]"
        )
        matches = arithmetic_pattern.findall(script)
        assert not matches, f"서버 응답 필드에 브라우저 산술 연산이 적용됨: {matches}"

        # 세 금액은 서버 응답을 계산 없이 표시 함수에 바인딩한다.
        assert "amountText(prediction.optimal_price)" in script
        assert "amountText(bounds.min_bid_amount)" in script
        assert "amountText(bounds.max_bid_amount)" in script
        # 정량평가 배점 Q 를 100 - B 로 만들지 않는다.
        assert "100 -" not in script
        assert "100-" not in script


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
            "price_compensation",
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
            "quant_items",
            "management_grade",
            "reputation_items",
            "disqualification",
        ]

        for field in input_fields:
            assert field in schema_content, f"입력 스키마에 {field} 필드 누락"

        # 템플릿 입력 필드 id 확인
        template_input_ids = [
            'id="qualification-tbody"',
            'id="reputation-section"',
            'id="input-management-grade"',
            'id="input-max-price-score"',
            'id="input-multiplier"',
            'id="input-pass-threshold"',
        ]

        for tid in template_input_ids:
            assert tid in template_content, f"템플릿에 입력 필드 {tid} 누락"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestEvaluationUIScoreTable:
    """공고문 배점표 입력과 미계산 표기 검증."""

    @pytest.fixture(scope="class")
    @classmethod
    def template_content(cls):
        path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "app"
            / "templates"
            / "bids"
            / "detail.html"
        )
        return path.read_text(encoding="utf-8")

    def test_score_table_inputs_exist(self, template_content):
        """공고문 배점표 B·k·T 입력란이 화면에 있어야 합니다.

        이 셋이 없으면 서버가 MISSING_SCORE_TABLE 로 점수 계산을 차단하므로
        사용자는 정량점수를 입력해도 총점을 볼 수 없습니다. 2026-09-09 에 실제로
        그 상태로 배포돼 모든 시나리오가 부적격으로 보였습니다.
        """
        for field_id in ("input-max-price-score", "input-multiplier", "input-pass-threshold"):
            assert f'id="{field_id}"' in template_content, f"배점표 입력란 {field_id} 누락"

    def test_score_table_is_sent_in_request(self, template_content):
        """배점표 입력값이 추천 계산의 수정값(overrides)으로 실려야 합니다."""
        for key in ("max_price_score", "multiplier", "pass_threshold"):
            assert f"overrides.{key} =" in template_content, f"overrides.{key} 누락"

    def test_analyze_only_scenario_rendering_removed(self, template_content):
        """/analyze 전용 시나리오 렌더링과 미계산 표기는 추천 계산 전환으로 제거됐다."""
        assert "scenario.is_qualified" not in template_content
        assert 'id="scenario-tbody"' not in template_content


class TestEvaluationUIPriceCompensationRemoved:
    """정량점수 부족분의 입찰가격 보완 영역은 세 금액 추천으로 대체되어 제거됐다.

    /recommend 응답에는 price_compensation 이 없어 마크업과 렌더 함수를 함께
    제거했다. 남아 있으면 화면이 채우지 못하는 빈 영역이 된다.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def template_content(cls):
        path = Path("src/app/templates/bids/detail.html")
        return path.read_text(encoding="utf-8")

    def test_price_compensation_section_removed(self, template_content):
        """보완 영역 마크업과 렌더 함수가 제거됐다."""
        assert 'id="price-compensation"' not in template_content
        assert 'id="pc-scenario-table"' not in template_content
        assert "renderPriceCompensation" not in template_content
        assert "입찰가격 보완 분석" not in template_content


class TestEvaluationUIScoreTableDeclaration:
    """규칙 선언 배점표(B·k·T) 자동 채움과 집중 미확인·덮어쓰기 표시 검증.

    값의 정본은 서버 응답(score_table)이며, 화면은 규칙 선언값을 입력란 기본값으로
    채우고 사용자가 바꾼 필드는 덮어쓰기로 구분해 표시합니다.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def template_content(cls):
        path = Path("src/app/templates/bids/detail.html")
        return path.read_text(encoding="utf-8")

    def test_declared_score_table_block_exists(self, template_content):
        """규칙 선언 배점표 블록과 B·k·T 표시 요소가 있다."""
        assert 'id="score-table-rule"' in template_content
        assert 'id="score-table-b"' in template_content
        assert 'id="score-table-k"' in template_content
        assert 'id="score-table-t"' in template_content
        assert 'id="score-table-source"' in template_content
        assert "규칙 선언 배점표" in template_content

    def test_unconfirmed_warning_exists(self, template_content):
        """미확정(None) 규칙을 알리는 집중 미확인 경고 경로가 있다."""
        assert 'id="score-table-unconfirmed"' in template_content
        assert 'id="score-table-unconfirmed-fields"' in template_content
        assert "집중 미확인" in template_content

    def test_override_notice_exists(self, template_content):
        """사용자 직접 입력을 덮어쓰기로 구분해 표시하는 경로가 있다."""
        assert 'id="score-table-override"' in template_content
        assert 'id="score-table-override-fields"' in template_content
        assert "덮어씁니다" in template_content

    def test_autofill_reads_server_payload(self, template_content):
        """서버 응답의 선언값·미확정·덮어쓰기 필드를 그대로 사용한다."""
        assert "renderRuleScoreTable" in template_content
        assert "fillScoreTableInput" in template_content
        assert "scoreTable.missing_fields" in template_content
        assert "scoreTable.override_fields" in template_content
        assert "scoreTable.source" in template_content
        assert 'id="score-table-modal"' in template_content
        assert "function openScoreTableModal" in template_content
        assert ".text(scoreTable.source" not in template_content

    def test_autofill_does_not_overwrite_user_input(self, template_content):
        """규칙 선언값은 비어 있는 입력란에만 채워 사용자가 넣은 값을 덮지 않는다."""
        assert "$.trim($input.val()) === ''" in template_content

    def test_declared_table_rendered_in_recommend_flow(self, template_content):
        """추천 계산 응답에서 선언 배점표를 반영한다."""
        assert template_content.count("renderRuleScoreTable(data.score_table)") == 1
