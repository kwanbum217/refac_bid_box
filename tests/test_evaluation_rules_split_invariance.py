"""적격심사 규칙 레지스트리 모듈 분리 불변성 시험.

src/app/services/evaluation_rules.py 를 시·도(LOCAL) 규칙 모듈(evaluation_rules_local)과
기관(INSTITUTION) 규칙 모듈(evaluation_rules_institution), 공통 자료형 모듈
(evaluation_rules_core)으로 나눈 뒤에도 (가) 규칙 상수의 값과 순서가 그대로인지,
(나) 공개·비공개 이름이 evaluation_rules 모듈에 모두 남아 있는지, (다) LOCAL_RULES·
INSTITUTION_RULES 가 새 모듈의 같은 객체인지, (라) 새 모듈이 evaluation_rules 없이
단독으로 import 되는지를 고정합니다.

기준값은 분리 전 main(35e39086) 에서 계산한 값이며, 이름 목록은 시험 파일 안에 상수로
둡니다. 별도 파일이나 .orca 산출물에 의존하지 않습니다.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from src.app.services import (
    evaluation_rules,
    evaluation_rules_core,
    evaluation_rules_institution,
    evaluation_rules_local,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# main 에서 계산한 sha256(repr(상수))[:16] 지문값. 값을 바꿀 수 없습니다.
EXPECTED_FINGERPRINTS: dict[str, str] = {
    "POST_20260526_RULES": "92dfb7c194d68e3f",
    "POST_20260727_RULES": "dfad0fcd3f7e9987",
    "MOE_CDW_RULES": "8591a0e4ea7a888a",
    "PRE_20250901_RULES": "8462974964f16d17",
    "PRE_20230501_RULES": "77a16139ea892a07",
    "PRE_20260526_RULES": "a09f80a6e80bf80d",
    "LOCAL_RULES": "ed46a9742ea23402",
    "MOIS_ACADEMIC_BAND_RULES": "e7e2960460553ba0",
    "INSTITUTION_RULES": "d7cabe0e33a1e8cf",
}

# main 의 vars(evaluation_rules) 이름 목록. 비공개 이름(_ 로 시작)도 포함합니다.
EXPECTED_NAMES: tuple[str, ...] = (
    "Any",
    "BLOCK_CODE_LOCAL_RULE_NOT_FOUND",
    "BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED",
    "BLOCK_CODE_MANUAL_EVALUATION",
    "BLOCK_CODE_NEGOTIATION_CONTRACT",
    "BLOCK_CODE_NON_PRED_PRICE",
    "BLOCK_CODE_NOT_QUALIFICATION_METHOD",
    "BLOCK_CODE_NOT_SERVC",
    "BLOCK_CODE_RULE_NOT_FOUND",
    "BLOCK_CODE_RULE_REGIME_MISMATCH",
    "BLOCK_CODE_RULE_SCOPE_AMBIGUOUS",
    "BLOCK_CODE_TECH_SERVICE_MISSING_LWLT",
    "CREDIT_GRADE_SCORES",
    "CreditGradeScore",
    "DEMAND_AGENCY_CREDIT_DEDUCTIONS",
    "Decimal",
    "DemandAgencyCreditDeduction",
    "EDU_PPS_FALLBACK_WARNING",
    "EXCLUDE_INSTITUTION_RULES_FOR_PPS_PROXY",
    "EvaluationRule",
    "INSTITUTION_RULES",
    "LOCAL_RULES",
    "MERGED_REGION_CODE",
    "METHOD_FAMILY_BY_CODE",
    "METHOD_FAMILY_QUALIFICATION",
    "METHOD_NAME_PLACEHOLDER",
    "METHOD_SOURCE_ANNOUNCEMENT",
    "METHOD_SOURCE_CODE",
    "MOE_CDW_EFFECTIVE_DATE",
    "MOE_CDW_RULES",
    "MOE_CDW_WARNING",
    "MOIS_ACADEMIC_BAND_RULES",
    "MOIS_ACADEMIC_BAND_WARNING",
    "NEGOTIATION_VARIANT_CONSTRUCTION_ENGINEERING",
    "NEGOTIATION_VARIANT_ENGINEERING",
    "NEGOTIATION_VARIANT_STANDARD",
    "NEGOTIATION_VARIANT_SW",
    "POST_20260526_RULES",
    "POST_20260727_RULES",
    "PRE_20230501_RULES",
    "PRE_20250901_RULES",
    "PRE_20260526_RULES",
    "PriceBand",
    "QUANT_BAND_LABELS",
    "QUANT_BAND_OVER_500M",
    "QUANT_BAND_SINGLE",
    "QUANT_BAND_UNDER_500M",
    "QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED",
    "QUANT_BASIS_INSTITUTION",
    "QUANT_BASIS_REGISTRY",
    "QUANT_ESTIMATED_PRICE_THRESHOLD",
    "QUANT_FIXED_TOTAL_LIMIT",
    "QUANT_ITEM_AFTER_SERVICE",
    "QUANT_ITEM_DISQUALIFICATION",
    "QUANT_ITEM_INSURANCE_ABILITY",
    "QUANT_ITEM_LABOR_PLAN",
    "QUANT_ITEM_MANAGEMENT",
    "QUANT_ITEM_OTHER_PERFORMANCE",
    "QUANT_ITEM_PERFORMANCE",
    "QUANT_ITEM_PRICE",
    "QUANT_ITEM_REPUTATION",
    "QUANT_ITEM_TECHNICAL",
    "QUANT_ITEM_TECHNICAL_CREDIT",
    "QUANT_ITEM_TECHNICAL_INPUT",
    "QUANT_LIMIT_KIND_ABSENT",
    "QUANT_LIMIT_KIND_CREDIT_GRADE",
    "QUANT_LIMIT_KIND_DISQUALIFICATION",
    "QUANT_LIMIT_KIND_PRICE",
    "QUANT_LIMIT_KIND_RANGE",
    "QUANT_LIMIT_KIND_REPUTATION",
    "QUANT_LIMIT_KIND_SCORE",
    "QUANT_LIMIT_KIND_TOTAL_EXCLUDED",
    "QUANT_SCORE_TABLES",
    "QUANT_SECTION_1",
    "QUANT_SECTION_2",
    "QUANT_SECTION_3",
    "QUANT_SECTION_4",
    "QuantScoreBand",
    "QuantScoreItem",
    "QuantScoreTable",
    "QuantTotalAuditRow",
    "REGION_CODE_EQUIVALENTS",
    "REPUTATION_INDUSTRIAL_ACCIDENT_MAX_BONUS",
    "REPUTATION_ITEMS",
    "REPUTATION_ITEMS_BY_CODE",
    "REPUTATION_ITEM_INDUSTRIAL_ACCIDENT",
    "REPUTATION_MAX_BONUS",
    "REPUTATION_MAX_PENALTY",
    "REPUTATION_OPTION_CHOICE",
    "REPUTATION_OPTION_RANGE",
    "RULE_REGIME_BOUNDARIES",
    "RULE_SCOPE_ALL",
    "RULE_SCOPE_INSTITUTION",
    "RULE_SCOPE_REGION",
    "RULE_SCOPE_VALUES",
    "ReputationItem",
    "RuleResolutionResult",
    "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT",
    "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526",
    "SERVC_TECH_QUAL_RULE_IDS",
    "ScoreParamResolution",
    "ScoreTableEntry",
    "Sequence",
    "ThresholdBand",
    "_FISHERY_CLEANUP_RECOMMEND_KEYWORDS",
    "_GWANGJU_DISTRICTS_FOR_LEGACY",
    "_GWANGJU_ELIS_RULE",
    "_INSTITUTION_NOTICE_AMOUNT",
    "_InstitutionBand",
    "_JEONNAM_CITIES_FOR_LEGACY",
    "_JEONNAM_ELIS_RULE",
    "_KAC_INSTITUTION_ALIASES",
    "_LOCAL_COLLECTION",
    "_LOCAL_LWLT_BY_SERVICE",
    "_LOCAL_NOT_FOUND_MESSAGE",
    "_MEASURED_LWLT_UNDER_1B",
    "_METHOD_SERVICE_MARKERS",
    "_MOE_CDW_FALLBACK_BLOCK_CODES",
    "_MOE_CDW_PPS_BAND_RULE_IDS",
    "_MOE_CDW_SOURCE",
    "_MOIS_ACADEMIC_BAND_EXCLUDED_MARKERS",
    "_MOIS_ACADEMIC_BAND_FALLBACK_BLOCK_CODES",
    "_NEGOTIATION_VARIANTS",
    "_PPS_PROXY_CODE_PREFIX",
    "_PPS_PROXY_NAME",
    "_PROCUREMENT_CLASS_KEYS",
    "_PROCUREMENT_SERVICE_MARKERS",
    "_QUANT_NOTE_ABSENT",
    "_QUANT_NOTE_RANGE",
    "_QUANT_NOTE_RANGE_TOTAL",
    "_QUANT_NOTE_REPUTATION",
    "_QUANT_NOTE_UNDER_ONLY",
    "_QUANT_SRC_ATTACH",
    "_QUANT_SRC_BKT",
    "_QUANT_SRC_CREDIT",
    "_QUANT_SRC_REPUTATION",
    "_SCORE_DOC_MEASURED",
    "_SCORE_DOC_POST",
    "_SCORE_DOC_POST_ATTACH_7_9",
    "_SCORE_DOC_PRE",
    "_SCORE_DOC_PRE_20230501",
    "_SCORE_NOTE_B_MANUAL",
    "_SCORE_NOTE_B_SPLIT",
    "_SCORE_NOTE_K_SPLIT",
    "_SCORE_REASON_UNKNOWN_RULE",
    "_SCORE_REASON_UNMAPPED_BAND",
    "_SCORE_SRC_POST",
    "_SCORE_SRC_POST_ATTACH_7_9",
    "_SCORE_SRC_PRE",
    "_SCORE_TABLE_DECLARATIONS",
    "_SCORE_THRESHOLD_88_ATTACHMENTS",
    "_SEOUL_TOP_LWLT_RATES",
    "_SIMPLE_LABOR_RECOMMEND_KEYWORDS",
    "_SME_NON_TARGET_MARKER",
    "_SME_SERVICE_TYPE_BY_BASE",
    "_SME_TARGET_MARKERS",
    "_SRC_BUSAN",
    "_SRC_CB",
    "_SRC_CHUNGNAM_20200201",
    "_SRC_CHUNGNAM_ATTACH_01",
    "_SRC_CHUNGNAM_ATTACH_02",
    "_SRC_CHUNGNAM_ATTACH_03",
    "_SRC_CHUNGNAM_ATTACH_04",
    "_SRC_CHUNGNAM_ATTACH_05",
    "_SRC_CHUNGNAM_ATTACH_2_1",
    "_SRC_CHUNGNAM_HWPX",
    "_SRC_CHUNGNAM_HWPX_REVIEW",
    "_SRC_DAEGU",
    "_SRC_DAEGU_20220930",
    "_SRC_DAEGU_ATTACH_04",
    "_SRC_DAEJEON",
    "_SRC_DAEJEON_20240120",
    "_SRC_GANGWON",
    "_SRC_GB",
    "_SRC_GB_20241212",
    "_SRC_GB_ATTACH_04",
    "_SRC_GG",
    "_SRC_GG_INSURANCE",
    "_SRC_GN",
    "_SRC_GWANGJU_ATTACH_1_3",
    "_SRC_GWANGJU_ATTACH_1_5",
    "_SRC_INCHEON",
    "_SRC_INCHEON_20241204",
    "_SRC_INST_AGENCY",
    "_SRC_INST_CENTRAL",
    "_SRC_INST_KAC",
    "_SRC_INST_KAC_ANNEX32",
    "_SRC_INST_KDHC_PREDECESSOR",
    "_SRC_INST_KOEM",
    "_SRC_INST_KOGAS",
    "_SRC_INST_RECOVER_A",
    "_SRC_JEJU",
    "_SRC_JEONBUK",
    "_SRC_JEONNAM_ATTACH_1_1_4",
    "_SRC_JEONNAM_ATTACH_4_1_4",
    "_SRC_JEONNAM_ATTACH_5_1_4",
    "_SRC_JNGJ",
    "_SRC_LWLT_MEASURED",
    "_SRC_MOIS_ACADEMIC_BAND",
    "_SRC_RECOVER",
    "_SRC_SEJONG",
    "_SRC_SEJONG_EXT",
    "_SRC_SEJONG_FACILITY",
    "_SRC_SEJONG_LT_NON_TARGET",
    "_SRC_SEJONG_LT_TARGET",
    "_SRC_SEJONG_SW_NON_TARGET",
    "_SRC_SEJONG_SW_TARGET",
    "_SRC_SEJONG_WASTE",
    "_SRC_SEJONG_WASTE_HOUSEHOLD",
    "_SRC_SEOUL",
    "_SRC_SEOUL_LWLT_FORMULA",
    "_SRC_ULSAN",
    "_SUBUNIT_TOKEN_MARKERS",
    "_SUBUNIT_TOKEN_SUFFIXES",
    "_allocate_rules_for_announcement",
    "_apply_rule_lwlt",
    "_attachment_1_table",
    "_attachment_2_table",
    "_attachment_3_2_table",
    "_attachment_3_table",
    "_attachment_4_table",
    "_attachment_5_2_table",
    "_attachment_5_table",
    "_attachment_6_table",
    "_attachment_7_table",
    "_attachment_8_table",
    "_attachment_9_table",
    "_axis_matches",
    "_band",
    "_band_lwlt_rate",
    "_chungnam_notice_band_price",
    "_classify_sme_competition",
    "_clean_axis_value",
    "_cleaned_institution_name",
    "_disqualification_item",
    "_five_band_price",
    "_four_band_price",
    "_has_conditional_axis",
    "_inst_band",
    "_institution_band_bound",
    "_institution_band_order",
    "_institution_match_score",
    "_institution_name_matches",
    "_institution_rule",
    "_institution_subunit_code_matches",
    "_institution_subunit_name_matches",
    "_is_gwangju_metro_institution",
    "_is_moe_cdw_fallback_target",
    "_is_pps_proxy_announcement",
    "_is_subunit_token",
    "_labor_item",
    "_legacy_merged_institution_code",
    "_local_price_band",
    "_local_rule",
    "_local_threshold_band",
    "_measured_lwlt_four_band_price",
    "_narrow_rule_scope",
    "_narrow_to_current_regime",
    "_normalize_grade",
    "_normalize_institution_text",
    "_normalized_price",
    "_parse_announcement_date",
    "_performance_section",
    "_price_item",
    "_qi",
    "_recommend_local_service_type",
    "_reputation_item",
    "_resolve_by_method_name",
    "_rule_applies_to_announcement",
    "_rules_for_announcement_date",
    "_score_source",
    "_select_institution_quant_band",
    "_select_institution_rule",
    "_select_local_rule",
    "_select_upper_bound_band",
    "_seoul_five_band_price",
    "_single_threshold",
    "_threshold_30_10",
    "_under_only",
    "_validate_bands",
    "_with_score_table",
    "annotations",
    "credit_score_for_grade",
    "dataclass",
    "date",
    "datetime",
    "demand_agency_credit_deduction",
    "extract_contract_regime",
    "field",
    "find_credit_grade",
    "find_reputation_item",
    "get_rule_by_id",
    "list_all_rules",
    "match_rule_by_mthd_nm",
    "method_name_500m_side",
    "normalize_pattern_string",
    "notice_amount_for_year",
    "quant_band_scored_limit_total",
    "quant_score_table_for_rule",
    "quant_score_tables_total_audit",
    "re",
    "replace",
    "resolve_evaluation_rule",
    "resolve_evaluation_rule_from_raw_data",
    "resolve_local_service_type",
    "resolve_method_name",
    "resolve_score_params",
    "select_moe_cdw_rule",
    "select_mois_academic_band_rule",
    "select_price_band",
    "select_quant_band",
    "select_threshold_band",
)

# list_all_rules() 결과의 지문값
EXPECTED_LIST_ALL_RULES_FINGERPRINT = "87abafd78e7af8f2"


def _fingerprint(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()[:16]


def test_rule_constant_fingerprints_are_unchanged() -> None:
    """규칙 상수의 값과 순서가 분리 전과 같습니다."""
    for name, expected in EXPECTED_FINGERPRINTS.items():
        actual = _fingerprint(getattr(evaluation_rules, name))
        assert actual == expected, f"{name} 지문값이 바뀌었습니다: {actual} != {expected}"


def test_list_all_rules_fingerprint_is_unchanged() -> None:
    """전체 규칙 목록의 구성과 순서가 분리 전과 같습니다."""
    actual = _fingerprint(evaluation_rules.list_all_rules())
    assert actual == EXPECTED_LIST_ALL_RULES_FINGERPRINT


def test_expected_names_remain_module_attributes() -> None:
    """분리 전 evaluation_rules 의 이름이 모두 그대로 남아 있습니다."""
    missing = [name for name in EXPECTED_NAMES if not hasattr(evaluation_rules, name)]
    assert missing == [], f"evaluation_rules 에서 사라진 이름이 있습니다: {missing}"


def test_local_rules_is_same_object_in_new_module() -> None:
    """LOCAL_RULES 는 새 모듈의 같은 객체입니다."""
    assert evaluation_rules.LOCAL_RULES is evaluation_rules_local.LOCAL_RULES


def test_institution_rules_is_same_object_in_new_module() -> None:
    """INSTITUTION_RULES 는 새 모듈의 같은 객체입니다."""
    assert evaluation_rules.INSTITUTION_RULES is evaluation_rules_institution.INSTITUTION_RULES


def test_new_modules_import_without_evaluation_rules() -> None:
    """새 모듈은 evaluation_rules 없이 단독으로 import 됩니다(순환 import 없음)."""
    code = (
        "import sys\n"
        "import src.app.services.evaluation_rules_local\n"
        "import src.app.services.evaluation_rules_institution\n"
        "assert 'src.app.services.evaluation_rules' not in sys.modules, sorted(sys.modules)\n"
    )
    result = subprocess.run(  # noqa: S603 - 고정된 인터프리터와 고정된 코드만 실행합니다
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_core_module_holds_shared_rule_types() -> None:
    """공통 자료형은 core 모듈에 있고 두 규칙 모듈이 같은 객체를 씁니다."""
    assert evaluation_rules.EvaluationRule is evaluation_rules_core.EvaluationRule
    assert evaluation_rules.PriceBand is evaluation_rules_core.PriceBand
    assert evaluation_rules.ThresholdBand is evaluation_rules_core.ThresholdBand
    assert evaluation_rules_local.EvaluationRule is evaluation_rules_core.EvaluationRule
    assert evaluation_rules_institution.EvaluationRule is evaluation_rules_core.EvaluationRule


def test_central_government_and_selection_logic_stay_in_evaluation_rules() -> None:
    """조달청 상수와 선택·매칭 로직은 evaluation_rules 에 남습니다."""
    for name in ("POST_20260526_RULES", "POST_20260727_RULES", "MOE_CDW_RULES"):
        assert hasattr(evaluation_rules, name)
        assert not hasattr(evaluation_rules_local, name)
        assert not hasattr(evaluation_rules_institution, name)
    for name in (
        "_select_local_rule",
        "_select_institution_rule",
        "resolve_evaluation_rule",
        "select_mois_academic_band_rule",
        "select_moe_cdw_rule",
    ):
        assert hasattr(evaluation_rules, name)
        assert not hasattr(evaluation_rules_local, name)
        assert not hasattr(evaluation_rules_institution, name)
