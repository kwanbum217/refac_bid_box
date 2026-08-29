"""
tests/test_measure_llm_quality.py

LLM 품질 평가 실측 하네스 (scripts/measure_llm_quality.py) 단위 테스트.

다음을 검증한다:
(a) 원자 numeric 팩트 중 하나가 답변에 없으면 실패로 잡히는지
(b) forbidden_literal 이 답변에 나오면 위반으로 잡히는지 (대소문자 무시)
(c) 규칙 설명문이 semantic_forbidden_claims 로 분리되어 자동 위반으로 오판되지 않는지
(d) refusal 기대와 실제가 어긋나면 실패로 집계되는지
(e) --expected-model 과 실제 모델이 다르면 통과하지 않는지 (통합 테스트에서 검증)
"""

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.measure_llm_quality import (
    CANONICAL_FIXTURE_HASHES,
    _compare_known_identity,
    _identity_field_known,
    build_provenance,
    compute_file_sha256,
    evaluate_canonical,
    is_refusal,
    main,
    numeric_fact_found,
    retrieved_ids,
    score_item,
    validate_base_url_port,
)


class TestNumericFactFound:
    """numeric_fact_found 함수 단위 테스트."""

    def test_exact_match(self):
        assert numeric_fact_found("낙찰금액은 46,602,100원입니다.", "46602100", 0.01) is True

    def test_within_tolerance(self):
        assert numeric_fact_found("낙찰률 88.51%입니다.", "88.5100", 0.01) is True

    def test_outside_tolerance(self):
        assert numeric_fact_found("낙찰률 88.53%입니다.", "88.5100", 0.01) is False

    def test_missing_fact(self):
        assert numeric_fact_found("낙찰업체는 A사입니다.", "46602100", 0.01) is False

    def test_comma_handling(self):
        assert numeric_fact_found("금액: 1,000,000원", "1000000", 1) is True

    def test_multiple_numbers_finds_correct_one(self):
        # 답변에 여러 숫자가 있어도 기대값과 맞는 것 하나만 찾으면 통과
        assert numeric_fact_found("낙찰금액 100원, 낙찰률 50%", "100", 0) is True
        assert numeric_fact_found("낙찰금액 100원, 낙찰률 50%", "50", 0) is True

    def test_no_numbers_in_answer(self):
        assert numeric_fact_found("답변에 숫자 없음", "100", 0) is False


class TestRetrievedIds:
    """retrieved_ids 함수 단위 테스트."""

    def test_integer_metadata_id(self):
        payload = {"retrieved_docs": [{"metadata": {"id": 10015927}}]}
        assert retrieved_ids(payload) == ["bid_10015927"]

    def test_string_id_with_prefix(self):
        payload = {"retrieved_docs": [{"id": "bid_10015927"}]}
        assert retrieved_ids(payload) == ["bid_10015927"]

    def test_string_id_without_prefix(self):
        payload = {"retrieved_docs": [{"id": "10015927"}]}
        assert retrieved_ids(payload) == ["bid_10015927"]

    def test_mixed_docs(self):
        payload = {
            "retrieved_docs": [
                {"metadata": {"id": 10015927}},
                {"id": "bid_7952020"},
                {"id": "5880526"},
            ]
        }
        assert set(retrieved_ids(payload)) == {"bid_10015927", "bid_7952020", "bid_5880526"}

    def test_empty_or_missing(self):
        assert retrieved_ids({}) == []
        assert retrieved_ids({"retrieved_docs": []}) == []
        assert retrieved_ids({"retrieved_docs": [{}]}) == []


class TestIsRefusal:
    """is_refusal 함수 단위 테스트."""

    def test_korean_refusal_phrases(self):
        refusals = [
            "제공할 수 없습니다.",
            "알려드릴 수 없습니다.",
            "확인할 수 없습니다.",
            "답변할 수 없습니다.",
            "정보가 없습니다.",
            "데이터가 없습니다.",
            "근거가 없습니다.",
            "모르겠습니다.",
            "알 수 없습니다.",
            "확인 불가입니다.",
            "제공 불가입니다.",
            "범위 밖입니다.",
            "수집되지 않았습니다.",
        ]
        for text in refusals:
            assert is_refusal(text) is True, f"거절로 판정되어야 함: {text}"

    def test_context_not_included_phrasing_is_refusal(self):
        """근거 부재를 '포함되어 있지 않습니다' 로 말하는 거절도 잡아야 합니다.

        2026-08-25 v2 측정에서 이 표현이 패턴에 없어 정상 거절이 과잉응답으로
        오분류됐고, e2b 의 거절 오답이 7건으로 부풀려졌습니다(실제 2건).
        """
        for answer in (
            "제공된 검색 컨텍스트에는 요청하신 사업에 대한 낙찰 결과 정보가 포함되어 있지 않습니다.",
            "해당 공고는 검색 결과에 포함되지 않습니다.",
            "요청하신 자료는 제공되지 않습니다.",
            "관련 근거를 찾을 수 없습니다.",
        ):
            assert is_refusal(answer), answer

    def test_non_refusal_answers(self):
        non_refusals = [
            "낙찰금액은 46,602,100원입니다.",
            "낙찰업체는 A사이며 금액은 1억원입니다.",
            "공고번호는 R26BK01659912-001입니다.",
            "네, 알려드리겠습니다. 낙찰금액은...",
        ]
        for text in non_refusals:
            assert is_refusal(text) is False, f"거절이 아니어야 함: {text}"

    def test_empty_answer_is_refusal(self):
        assert is_refusal("") is True
        assert is_refusal("   ") is True


class TestScoreItem:
    """score_item 함수 단위 테스트."""

    def make_item(self, **overrides) -> dict[str, Any]:
        base = {
            "id": "q01",
            "context_sufficient": True,
            "expected_evidence_ids": ["bid_10015927"],
            "expected_facts": [
                {
                    "statement": "낙찰금액은 46,602,100원 임",
                    "fact_type": "numeric",
                    "expected_value": "46602100",
                    "unit": "원",
                    "tolerance": 1,
                    "verification_criterion": "낙찰금액 46,602,100원(±1원) 명시",
                },
                {
                    "statement": "낙찰률은 88.5100% 임",
                    "fact_type": "numeric",
                    "expected_value": "88.5100",
                    "unit": "%",
                    "tolerance": 0.01,
                    "verification_criterion": "낙찰률 88.5100%(±0.01%p) 명시",
                },
            ],
            "forbidden_literals": ["Servc", "Thng", "Cnstwk", "Frgcpt"],
            "semantic_forbidden_claims": ["낙찰업체를 다른 업체로 허위 기재하거나 금액 왜곡"],
            "citation_required": True,
            "refusal_expected": False,
        }
        base.update(overrides)
        return base

    def make_payload(self, response: str, retrieved: list[dict] | None = None) -> dict[str, Any]:
        payload = {"response": response}
        if retrieved is not None:
            payload["retrieved_docs"] = retrieved
        return payload

    def test_atomic_numeric_fact_missing_fails(self):
        """(a) 원자 numeric 팩트 중 하나가 답변에 없으면 실패로 잡히는지."""
        item = self.make_item()
        # 낙찰금액만 있고 낙찰률이 없는 답변
        payload = self.make_payload("낙찰금액은 46,602,100원입니다.")
        result = score_item(item, payload)

        assert result["numeric_all_found"] is False
        # 두 팩트 중 첫 번째(금액)만 found=True, 두 번째(비율)는 False
        found_values = [r["found"] for r in result["numeric_facts"]]
        assert found_values == [True, False]

    def test_both_atomic_numeric_facts_present_passes(self):
        """두 원자 numeric 팩트가 모두 있으면 통과."""
        item = self.make_item()
        payload = self.make_payload("낙찰금액은 46,602,100원이며 낙찰률은 88.5100%입니다.")
        result = score_item(item, payload)

        assert result["numeric_all_found"] is True
        assert all(r["found"] for r in result["numeric_facts"])

    def test_forbidden_literal_detected_case_insensitive(self):
        """(b) forbidden_literal 이 답변에 나오면 위반으로 잡히는지 (대소문자 무시)."""
        item = self.make_item()
        # 소문자로 나와도 감지되어야 함
        payload = self.make_payload("내부 코드 servc 가 사용되었습니다.")
        result = score_item(item, payload)

        assert len(result["forbidden_literal_violations"]) == 1
        violation = result["forbidden_literal_violations"][0]
        assert violation["literal"] == "Servc"
        assert violation["matched_text"].lower() == "servc"
        assert "context" in violation

    def test_forbidden_literal_not_in_answer_no_violation(self):
        """답변에 금지 리터럴이 없으면 위반 없음."""
        item = self.make_item()
        payload = self.make_payload("정상적인 답변입니다. 낙찰금액은 46,602,100원입니다.")
        result = score_item(item, payload)

        assert result["forbidden_literal_violations"] == []

    def test_semantic_forbidden_claims_not_auto_violated(self):
        """(c) 규칙 설명문이 semantic_forbidden_claims 로 분리되어 자동 위반으로 오판되지 않는지."""
        item = self.make_item()
        # semantic_forbidden_claims 에 있는 문구가 답변에 나와도 자동 위반으로 처리되지 않음
        payload = self.make_payload(
            "낙찰업체를 다른 업체로 허위 기재하거나 금액 왜곡하는 것은 안 됩니다. "
            "낙찰금액은 46,602,100원입니다."
        )
        result = score_item(item, payload)

        # semantic_forbidden_claims 는 기록만 되고 자동 판정하지 않음
        assert (
            "낙찰업체를 다른 업체로 허위 기재하거나 금액 왜곡"
            in result["semantic_forbidden_claims"]
        )
        # forbidden_literal_violations 에는 없어야 함 (literal 매칭이 아니므로)
        assert result["forbidden_literal_violations"] == []

    def test_refusal_expected_true_actual_refusal_correct(self):
        """(d) refusal_expected=True 이고 실제 거절이면 통과."""
        item = self.make_item(refusal_expected=True, expected_facts=[])
        payload = self.make_payload("해당 정보는 제공할 수 없습니다.")
        result = score_item(item, payload)

        assert result["refusal_expected"] is True
        assert result["actual_refusal"] is True
        assert result["refusal_correct"] is True

    def test_refusal_expected_true_but_answered_fails(self):
        """(d) refusal_expected=True 인데 답변하면 실패."""
        item = self.make_item(refusal_expected=True, expected_facts=[])
        payload = self.make_payload("낙찰금액은 100원입니다.")
        result = score_item(item, payload)

        assert result["refusal_expected"] is True
        assert result["actual_refusal"] is False
        assert result["refusal_correct"] is False

    def test_refusal_expected_false_but_refused_fails(self):
        """(d) refusal_expected=False 인데 거절하면 실패."""
        item = self.make_item(refusal_expected=False)
        payload = self.make_payload("정보가 없어 답변할 수 없습니다.")
        result = score_item(item, payload)

        assert result["refusal_expected"] is False
        assert result["actual_refusal"] is True
        assert result["refusal_correct"] is False

    def test_refusal_expected_false_answered_correct(self):
        """(d) refusal_expected=False 이고 답변하면 통과."""
        item = self.make_item(refusal_expected=False)
        payload = self.make_payload("낙찰금액은 46,602,100원입니다.")
        result = score_item(item, payload)

        assert result["refusal_expected"] is False
        assert result["actual_refusal"] is False
        assert result["refusal_correct"] is True

    def test_evidence_recall_calculated(self):
        """evidence_recall 이 올바르게 계산되는지."""
        item = self.make_item(expected_evidence_ids=["bid_10015927", "bid_7952020"])
        payload = self.make_payload(
            "답변",
            retrieved=[{"metadata": {"id": 10015927}}],  # 하나만 검색됨
        )
        result = score_item(item, payload)

        assert result["evidence_recall"] == 0.5
        assert result["evidence_hit"] == ["bid_10015927"]

    def test_citation_checked(self):
        """citation_required=True 일 때 대괄호 인용 표기 검사."""
        item = self.make_item(citation_required=True)
        payload_with_citation = self.make_payload("답변입니다 [1].")
        payload_without_citation = self.make_payload("답변입니다.")

        result_with = score_item(item, payload_with_citation)
        result_without = score_item(item, payload_without_citation)

        assert result_with["citation_present"] is True
        assert result_without["citation_present"] is False

    def test_citation_not_required_returns_none(self):
        """citation_required=False 일 때 citation_present 는 None."""
        item = self.make_item(citation_required=False)
        payload = self.make_payload("답변입니다.")
        result = score_item(item, payload)

        assert result["citation_present"] is None


class TestValidateBaseUrlPort:
    """validate_base_url_port 함수 단위 테스트 (mock 사용)."""

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_localhost_port_match_passes(self, mock_check_output):
        """localhost 와 발행 포트가 일치하면 통과."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://localhost:8000", "test-container")
        assert ok is True
        assert "matches" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_127_0_0_1_port_match_passes(self, mock_check_output):
        """127.0.0.1 과 발행 포트가 일치하면 통과."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://127.0.0.1:8000", "test-container")
        assert ok is True
        assert "matches" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_ipv6_loopback_bracketed_passes(self, mock_check_output):
        """IPv6 loopback [::1] 과 발행 포트가 일치하면 통과."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://[::1]:8000", "test-container")
        assert ok is True
        assert "matches" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_remote_hostname_fails_even_if_port_matches(self, mock_check_output):
        """비로컬 hostname은 발행 포트가 일치해도 거부 (fail-closed)."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://other-host:8000", "test-container")
        assert ok is False
        assert "호스트명" in msg

        ok, msg = validate_base_url_port("http://192.168.1.100:8000", "test-container")
        assert ok is False
        assert "호스트명" in msg

    def test_userinfo_in_base_url_fails(self):
        """사용자 정보(userinfo)가 포함된 base_url 은 거부."""
        ok, msg = validate_base_url_port("http://user:pass@localhost:8000", "test-container")
        assert ok is False
        assert "사용자 정보" in msg

    def test_invalid_scheme_fails(self):
        """http/https 외의 scheme 은 거부."""
        ok, msg = validate_base_url_port("ftp://localhost:8000", "test-container")
        assert ok is False
        assert "scheme" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_port_mismatch_fails(self, mock_check_output):
        """컨테이너 발행 포트와 base_url 포트가 다르면 실패."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://localhost:9000", "test-container")
        assert ok is False
        assert "not bound" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_docker_error_fails(self, mock_check_output):
        """docker 명령 실패 시 실패."""
        mock_check_output.side_effect = subprocess.CalledProcessError(1, "docker")

        ok, msg = validate_base_url_port("http://localhost:8000", "test-container")
        assert ok is False
        assert "포트 검증 실패" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_malformed_port_returns_false_without_exception(self, mock_check_output):
        """malformed port(비숫자)는 예외 없이 false 를 반환한다."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        ok, msg = validate_base_url_port("http://localhost:abc", "test-container")
        assert ok is False
        assert "포트가 올바르지 않습니다" in msg

        ok, msg = validate_base_url_port("http://localhost:80abc", "test-container")
        assert ok is False
        assert "포트가 올바르지 않습니다" in msg

    @patch("scripts.measure_llm_quality.subprocess.check_output")
    def test_out_of_range_port_returns_false_without_exception(self, mock_check_output):
        """범위 밖 port(65535 초과)는 예외 없이 false 를 반환한다."""
        mock_check_output.return_value = '{"8000/tcp": [{"HostPort": "8000"}]}'

        for url in ("http://localhost:99999", "http://localhost:70000"):
            ok, msg = validate_base_url_port(url, "test-container")
            assert ok is False
            assert "포트가 올바르지 않습니다" in msg


class TestCompareKnownIdentity:
    """_compare_known_identity 헬퍼 단위 테스트."""

    def test_known_identity_field_known(self):
        assert _identity_field_known("abc1234") is True
        assert _identity_field_known(False) is True
        assert _identity_field_known(True) is True
        assert _identity_field_known("unknown") is False
        assert _identity_field_known(None) is False

    def test_both_known_equal_no_mismatch(self):
        mismatches = _compare_known_identity(
            {"git_sha": "abc1234", "git_dirty": False},
            {"git_sha": "abc1234", "git_dirty": False},
        )
        assert mismatches == []

    def test_both_known_dirty_mismatch(self):
        mismatches = _compare_known_identity(
            {"git_sha": "abc1234", "git_dirty": False},
            {"git_sha": "abc1234", "git_dirty": True},
        )
        assert any("git_dirty" in m for m in mismatches)

    def test_one_side_unknown_sha_ignored(self):
        mismatches = _compare_known_identity(
            {"git_sha": "abc1234", "git_dirty": False},
            {"git_sha": "unknown", "git_dirty": False},
        )
        assert mismatches == []

    def test_one_side_none_dirty_ignored(self):
        mismatches = _compare_known_identity(
            {"git_sha": "abc1234", "git_dirty": None},
            {"git_sha": "abc1234", "git_dirty": False},
        )
        assert mismatches == []

    def test_both_known_sha_mismatch_detected(self):
        mismatches = _compare_known_identity(
            {"git_sha": "sha_start", "git_dirty": False},
            {"git_sha": "sha_end", "git_dirty": False},
        )
        assert any("git_sha" in m for m in mismatches)


class TestBuildProvenance:
    """build_provenance 함수 단위 테스트."""

    def test_build_provenance_preserves_start_and_end_identities(self):
        provenance = build_provenance(
            start_sha="sha_start",
            start_dirty=False,
            end_sha="sha_end",
            end_dirty=False,
            started_model="gemma4:e4b",
            ended_model="gemma4:e4b",
            base_url="http://localhost:8000",
            app_container="test-container",
            canonical=True,
        )

        assert provenance["git_sha"] == "sha_start"
        assert provenance["git_dirty"] is False
        assert provenance["canonical"] is True
        assert provenance["source_identity_start"] == {
            "git_sha": "sha_start",
            "git_dirty": False,
        }
        assert provenance["source_identity_end"] == {
            "git_sha": "sha_end",
            "git_dirty": False,
        }
        assert provenance["serving_model_consistent"] is True


class TestComputeFileSha256:
    """compute_file_sha256 함수 단위 테스트."""

    def test_compute_file_sha256(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text("hello world", encoding="utf-8")
        import hashlib

        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_file_sha256(f) == expected


class TestEvaluateCanonical:
    """evaluate_canonical 순수 함수 단위 테스트 및 각 게이트 검증."""

    CANONICAL_HASH = "2c98c636a478cfc92870533513b4442704d8441bd217e303489c9bcf0752e483"
    NON_CANONICAL_HASH = "af7ab5fa35ee9cb94592b6e2cfd5c47db0184c2ea28c561918ec484eda6ac36f"

    def _valid_kwargs(self, **overrides) -> dict[str, Any]:
        kwargs = {
            "fixture_sha256": self.CANONICAL_HASH,
            "limit": 0,
            "item_count": 32,
            "total_fixture_items": 32,
            "repetitions": 3,
            "request_failures": 0,
            "start_sha": "abc1234",
            "start_dirty": False,
            "end_sha": "abc1234",
            "end_dirty": False,
            "model_mismatch": False,
            "port_ok": True,
            "allow_unknown_provenance": False,
        }
        kwargs.update(overrides)
        return kwargs

    def test_canonical_fixture_registry(self):
        """정본 fixture 해시 레지스트리에 v2 32문항 해시가 포함되어 있는지 검증."""
        assert self.CANONICAL_HASH in CANONICAL_FIXTURE_HASHES
        assert len(CANONICAL_FIXTURE_HASHES) >= 1

    def test_canonical_passes_all_gates(self):
        """(f) 정본 fixture 로 전량 3회 무실패면 true 이고 canonical_failed_gates 는 빈 목록."""
        is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs())
        assert is_canonical is True
        assert failed_gates == []

    def test_noncanonical_fixture_hash_fails(self):
        """(a) 비정본 fixture 해시면 canonical 이 false 이고 fixture_sha256_canonical 게이트 실패."""
        is_canonical, failed_gates = evaluate_canonical(
            **self._valid_kwargs(fixture_sha256=self.NON_CANONICAL_HASH)
        )
        assert is_canonical is False
        assert "fixture_sha256_canonical" in failed_gates

    def test_limit_nonzero_fails(self):
        """(b) limit 이 0 이 아니면 false 이고 limit_zero 게이트 실패."""
        is_canonical, failed_gates = evaluate_canonical(
            **self._valid_kwargs(limit=10, item_count=10)
        )
        assert is_canonical is False
        assert "limit_zero" in failed_gates

    def test_item_count_less_than_total_fails(self):
        """(c) item_count 가 fixture 전체 문항 수보다 적으면 false 이고 item_count_full 게이트 실패."""
        is_canonical, failed_gates = evaluate_canonical(
            **self._valid_kwargs(item_count=20, total_fixture_items=32)
        )
        assert is_canonical is False
        assert "item_count_full" in failed_gates

    def test_repetitions_less_than_three_fails(self):
        """(d) repetitions 가 3 미만(예: 1 또는 2)이면 false 이고 repetitions_minimum 게이트 실패."""
        for rep in (1, 2):
            is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs(repetitions=rep))
            assert is_canonical is False
            assert "repetitions_minimum" in failed_gates

    def test_request_failures_present_fails(self):
        """(e) request_failures 가 1 이상이면 false 이고 no_request_failures 게이트 실패."""
        is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs(request_failures=1))
        assert is_canonical is False
        assert "no_request_failures" in failed_gates

    def test_multiple_failed_gates_recorded(self):
        """여러 게이트 위반 시 모든 실패 게이트가 canonical_failed_gates 에 기록."""
        is_canonical, failed_gates = evaluate_canonical(
            **self._valid_kwargs(
                fixture_sha256=self.NON_CANONICAL_HASH,
                limit=5,
                repetitions=1,
                request_failures=2,
            )
        )
        assert is_canonical is False
        assert "fixture_sha256_canonical" in failed_gates
        assert "limit_zero" in failed_gates
        assert "repetitions_minimum" in failed_gates
        assert "no_request_failures" in failed_gates

    def test_provenance_gates_still_enforced(self):
        """기존 provenance / 모델 / 포트 게이트 검증 유지 확인."""
        is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs(start_dirty=True))
        assert is_canonical is False
        assert "start_clean" in failed_gates

        is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs(model_mismatch=True))
        assert is_canonical is False
        assert "model_match_expected" in failed_gates

        is_canonical, failed_gates = evaluate_canonical(**self._valid_kwargs(port_ok=False))
        assert is_canonical is False
        assert "port_validated" in failed_gates


class TestCliArguments:
    """CLI 인자 파싱 단위 테스트."""

    def test_missing_fixture_arg_fails(self, capsys):
        """(g) --fixture 없이 호출하면 인자 파싱이 실패하는지 검증."""
        argv = [
            "measure_llm_quality.py",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--output",
            "output.json",
        ]
        with patch("sys.argv", argv):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "required" in captured.err.lower() or "--fixture" in captured.err


class TestIntegrationMainHarness:
    """main() 실측 하네스 통합 및 provenance fail-closed 테스트 (mock 사용)."""

    def _setup_mocks(
        self,
        mock_validate_port,
        mock_check_output,
        mock_urlopen,
        mock_git_status,
        mock_verify=None,
        *,
        git_status_return=None,
        git_status_side_effect=None,
        started_model="gemma4:e4b",
        ended_model="gemma4:e4b",
    ):
        mock_validate_port.return_value = (True, "ok")
        if git_status_side_effect is not None:
            mock_git_status.side_effect = git_status_side_effect
        else:
            mock_git_status.return_value = git_status_return or ("abc1234", False)

        mock_check_output.side_effect = [started_model, ended_model]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"response": "낙찰금액은 46,602,100원입니다. [1]", "retrieved_docs": []}
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        if mock_verify is not None:
            mock_verify.return_value = True

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_git_status_called_exactly_twice_start_and_end(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """get_git_status mock 호출 순서가 시작 1회, 측정 종료 1회로 총 2회 관측되고 start identity 가 보존되는지 검증."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_side_effect=[("start_sha_123", False), ("start_sha_123", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v2.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "3",
            "--app-container",
            "test-container",
            "--output",
            str(out_file),
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        assert mock_git_status.call_count == 2
        assert out_file.exists()
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is True
        assert saved["provenance"]["source_identity_start"]["git_sha"] == "start_sha_123"
        assert saved["provenance"]["source_identity_end"]["git_sha"] == "start_sha_123"

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_start_dirty_true_fails_closed(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """시작 시점에 dirty=True 이면 fail-closed 로 거부하고 파일 저장하지 않음."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_return=("abc1234", True),
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--output",
            str(out_file),
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 3
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_start_dirty_true_cannot_be_bypassed_with_allow_unknown(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """--allow-unknown-provenance 옵션을 주어도 dirty=True 는 우회 불가."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_return=("abc1234", True),
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--allow-unknown-provenance",
            "--output",
            str(out_file),
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 3
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_start_sha_unknown_fails_closed_by_default(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """기본 strict 모드에서 start SHA 가 unknown 이면 fail-closed."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_return=("unknown", False),
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--output",
            str(out_file),
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 3
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_allow_unknown_provenance_saves_with_canonical_false(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """--allow-unknown-provenance 가 주어지면 unknown SHA 가 허용되되 canonical=false 로 저장."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_side_effect=[("unknown", False), ("unknown", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--allow-unknown-provenance",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        assert out_file.exists()
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is False

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_mid_run_mutation_clean_to_dirty_fails_closed(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """측정 중 clean 에서 dirty 로 변하면 exit non-zero 이고 canonical 결과 파일을 저장하지 않음."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_side_effect=[("abc1234", False), ("abc1234", True)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code != 0
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_mid_run_mutation_sha_change_fails_closed(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """측정 중 Git SHA 가 변하면 exit non-zero 이고 결과 파일을 저장하지 않음."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_side_effect=[("sha_start", False), ("sha_end", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 4
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_end_sha_unknown_fails_closed(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """종료 시점 SHA 가 unknown 이면 strict 모드에서 fail-closed."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            git_status_side_effect=[("sha_start", False), ("unknown", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 3
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    @patch("scripts.measure_llm_quality.verify_provenance_consistency")
    def test_expected_model_mismatch_returns_5_and_saves_debug(
        self,
        mock_verify,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """(e) --expected-model 과 실제 모델이 다르면 5 반환 및 디버그 파일 저장."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            mock_verify,
            started_model="gemma4:e2b",
            ended_model="gemma4:e2b",
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--app-container",
            "test-container",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            exit_code = main()

        assert exit_code == 5
        assert not out_file.exists()
        debug_file = out_file.with_suffix(".debug.json")
        assert debug_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    def test_strict_mode_uses_real_verify_provenance_consistency(
        self,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """strict 모드에서 실제 verify_provenance_consistency 를 mock 없이 사용해 일치 시 통과한다.

        identity 가 일치하면 실제 함수가 raise 하지 않고 통과해야 한다.
        """
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            git_status_side_effect=[("abc1234", False), ("abc1234", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v2.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "3",
            "--output",
            str(out_file),
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is True
        assert saved["provenance"]["source_identity_start"]["git_sha"] == "abc1234"
        assert saved["provenance"]["source_identity_end"]["git_sha"] == "abc1234"

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    def test_allow_unknown_side_unknown_sha_allowed_noncanonical(
        self,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """allow-unknown 에서 한쪽만 unknown SHA 면 noncanonical 로 허용한다 (mock 없이 실제 경로)."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            git_status_side_effect=[("abc1234", False), ("unknown", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--allow-unknown-provenance",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is False
        assert saved["provenance"]["source_identity_start"]["git_sha"] == "abc1234"
        assert saved["provenance"]["source_identity_end"]["git_sha"] == "unknown"

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    def test_allow_unknown_side_dirty_none_allowed_noncanonical(
        self,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """allow-unknown 에서 한쪽만 dirty None(확인 불가)이면 noncanonical 로 허용한다."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            git_status_side_effect=[("abc1234", None), ("abc1234", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--allow-unknown-provenance",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is False
        assert saved["provenance"]["source_identity_start"]["git_dirty"] is None
        assert saved["provenance"]["source_identity_end"]["git_dirty"] is False

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    def test_allow_unknown_both_known_sha_mutation_blocked(
        self,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
    ):
        """allow-unknown 이어도 양쪽 known SHA 가 실제로 다르면 차단한다."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            git_status_side_effect=[("sha_start", False), ("sha_end", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--allow-unknown-provenance",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 4
        assert not out_file.exists()

    @patch("scripts.measure_llm_quality.validate_base_url_port")
    @patch("scripts.measure_llm_quality.subprocess.check_output")
    @patch("scripts.measure_llm_quality.urlrequest.urlopen")
    @patch("scripts.measure_llm_quality.get_git_status")
    def test_noncanonical_measurement_saves_failed_gates_and_warns(
        self,
        mock_git_status,
        mock_urlopen,
        mock_check_output,
        mock_validate_port,
        tmp_path,
        capsys,
    ):
        """v1 fixture 및 limit 지정 시 canonical=false, failed_gates 및 stderr 경고 검증."""
        out_file = tmp_path / "result.json"
        self._setup_mocks(
            mock_validate_port,
            mock_check_output,
            mock_urlopen,
            mock_git_status,
            git_status_side_effect=[("sha_clean", False), ("sha_clean", False)],
        )

        argv = [
            "measure_llm_quality.py",
            "--fixture",
            "data/eval/llm_quality_fixture_v1.json",
            "--base-url",
            "http://localhost:8000",
            "--model-label",
            "test-model",
            "--expected-model",
            "gemma4:e4b",
            "--repetitions",
            "1",
            "--output",
            str(out_file),
            "--limit",
            "1",
        ]
        with patch("sys.argv", argv):
            code = main()

        assert code == 0
        assert out_file.exists()
        saved = json.loads(out_file.read_text(encoding="utf-8"))
        assert saved["canonical"] is False
        assert "fixture_sha256_canonical" in saved["canonical_failed_gates"]
        assert "limit_zero" in saved["canonical_failed_gates"]
        assert "repetitions_minimum" in saved["canonical_failed_gates"]
        assert "item_count_full" in saved["canonical_failed_gates"]
        assert "fixture_sha256" in saved
        assert saved["limit"] == 1
        captured = capsys.readouterr()
        assert "비정본(canonical=false)" in captured.err


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
