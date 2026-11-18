"""투찰가 추천 계산 안내 숨김 시험.

정본: .orca/capsules/task_210af1d4715b/capsule.yaml
 - 추천 결과가 정상으로 그려지면 하단 '투찰가 추천 계산' 라벨과 #recommend-status 를 숨긴다.
 - 요청 실패, 계산 미지원, 입력 필요 응답처럼 결과가 그려지지 않는 경로에서는 숨기지 않는다.
 - 페이지 진입 직후와 #recommend-stale, #recommend-loading, #recommend-unavailable 의
   표시 조건은 그대로 둔다.

템플릿 문자열만 검사하며 로컬 .env 나 운영 DB 에 기대지 않는다.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"
).as_posix()
GUIDE_HIDE_MARKERS = (
    "$('#recommend-guide-label').addClass('hidden');",
    "$('#recommend-status').addClass('hidden');",
)


def _source() -> str:
    return Path(TEMPLATE_PATH).read_text(encoding="utf-8")


def _function_body(source: str, header: str, stop_marker: str) -> str:
    start = source.index(header)
    end = source.index(stop_marker, start)
    return source[start:end]


def test_guide_label_has_target_id() -> None:
    """하단 안내 라벨은 새 id 로 대상을 특정할 수 있다."""
    source = _source()

    assert 'id="recommend-guide-label" class="detail-label">투찰가 추천 계산' in source
    assert 'id="recommend-status"' in source


def test_result_path_hides_guide_label_and_status() -> None:
    """결과를 그리는 함수에서 라벨과 #recommend-status 를 숨긴다."""
    render_amounts = _function_body(
        _source(), "function renderRecommendAmounts", "let recommendInFlight"
    )

    for marker in GUIDE_HIDE_MARKERS:
        assert marker in render_amounts, f"결과 표시 경로에 숨김 코드가 없음: {marker}"


def test_hide_code_runs_only_after_blocked_early_return() -> None:
    """차단 응답은 조기 반환 뒤이므로 숨김 코드가 실행되지 않는다."""
    render_amounts = _function_body(
        _source(), "function renderRecommendAmounts", "let recommendInFlight"
    )
    blocked_return = render_amounts.index("if (data.blocked) {")
    blocked_end = render_amounts.index("return;", blocked_return) + len("return;")
    first_hide = min(render_amounts.index(marker) for marker in GUIDE_HIDE_MARKERS)

    assert blocked_end < first_hide


def test_form_and_failure_paths_do_not_hide_guide() -> None:
    """사전 요청·오류 응답 경로에서는 안내를 숨기지 않는다."""
    source = _source()
    render_form = _function_body(
        source, "function renderEvaluationForm", "function loadEvaluationForm"
    )
    load_form = _function_body(source, "function loadEvaluationForm", "function requestRecommend")
    request_recommend = _function_body(source, "function requestRecommend", "$('#evaluation-card')")

    error_start = request_recommend.index("error: function(xhr) {")
    error_handler = request_recommend[error_start : request_recommend.index("complete: function()")]

    for block in (render_form, load_form, error_handler):
        for marker in GUIDE_HIDE_MARKERS:
            assert marker not in block, f"결과 표시 경로 밖에서 안내를 숨김: {marker}"


def test_other_status_visibility_unchanged() -> None:
    """나머지 상태 요소의 표시 조건은 그대로 남는다."""
    source = _source()

    for element_id in ("recommend-stale", "recommend-loading", "recommend-unavailable"):
        assert f'id="{element_id}"' in source
    assert "$('#recommend-stale').addClass('hidden');" in source
    assert "$('#recommend-stale').removeClass('hidden');" in source
    assert "$('#recommend-loading').removeClass('hidden');" in source
    assert "$('#recommend-loading').addClass('hidden');" in source
