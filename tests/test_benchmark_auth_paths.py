"""인증 경로 레이턴시 벤치마크 하니스(scripts/benchmark_auth_paths.py) 단위 테스트.

검증 대상:
1. 세션 쿠키(bidbox_session) 추출 로직 (cookies 객체 및 Set-Cookie 헤더 대응)
2. 대상 엔드포인트 선별 및 부작용(DB 쓰기, 외부 수집) 경로 제외 보장
3. 백분위수(P50, P95) 및 통계량 집계 로직
4. 자격 증명 해석 및 기본값 하드코딩 부재 검증
5. 드라이런 모드 및 모의 클라이언트를 통한 단일 웜/동시성 하니스 동작
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.benchmark_auth_paths import (
    EXCLUDED_ENDPOINTS,
    SESSION_COOKIE_NAME,
    TARGET_ENDPOINTS,
    EndpointSpec,
    calculate_percentile,
    extract_session_cookie_from_response,
    filter_endpoints,
    login_and_obtain_session_cookie,
    main,
    measure_single_warm,
    resolve_credentials,
    summarize_latencies,
)

# =============================================================================
# 1. 세션 쿠키 추출 검증
# =============================================================================


def test_extract_cookie_from_cookies_dict():
    """response.cookies 객체에 bidbox_session 이 있을 때 정상 추출하는지 검증."""
    request = httpx.Request("POST", "http://127.0.0.1:8000/api/v1/accounts/login")
    response = httpx.Response(
        status_code=200,
        request=request,
        headers={"content-type": "application/json"},
    )
    response.cookies.set(SESSION_COOKIE_NAME, "test_session_token_123")

    cookie = extract_session_cookie_from_response(response)
    assert cookie == "test_session_token_123"


def test_extract_cookie_from_set_cookie_header():
    """Set-Cookie 헤더에서 속성(Path, HttpOnly 등)이 포함되어 있어도 토큰만 정확히 파싱하는지 검증."""
    headers = [
        (
            "set-cookie",
            "bidbox_session=header_token_abc; Max-Age=1209600; Path=/; HttpOnly; SameSite=lax",
        )
    ]
    response = httpx.Response(
        status_code=200,
        headers=headers,
    )

    cookie = extract_session_cookie_from_response(response)
    assert cookie == "header_token_abc"


def test_extract_cookie_missing_raises_value_error():
    """응답에 bidbox_session 쿠키가 없으면 ValueError 가 발생하는지 검증."""
    response = httpx.Response(
        status_code=200,
        headers=[("set-cookie", "other_cookie=xyz; Path=/")],
    )

    with pytest.raises(ValueError, match=SESSION_COOKIE_NAME):
        extract_session_cookie_from_response(response)


# =============================================================================
# 2. 대상 경로 선별 및 부작용 경로 제외 검증
# =============================================================================


def test_target_endpoints_have_no_side_effects():
    """측정 대상 경로가 모두 GET 메서드이며 부작용 없는 순수 조회인지 검증."""
    assert len(TARGET_ENDPOINTS) >= 3

    for ep in TARGET_ENDPOINTS:
        # DB 쓰기나 외부 호출을 동반하는 메서드(POST, PUT, DELETE, PATCH)가 아니어야 함
        assert ep.method == "GET", f"{ep.name}의 메서드가 GET이 아닙니다: {ep.method}"
        # 대상 경로는 사양에 정의된 안전한 읽기 경로여야 함
        assert ep.path in (
            "/api/v1/accounts/me",
            "/api/v1/evaluations/profiles",
            "/api/v1/evaluations/snapshots",
        )


def test_excluded_endpoints_include_critical_side_effects():
    """부작용이 있는 핵심 엔드포인트들이 제외 목록에 등록되어 있고 사유가 기재되어 있는지 검증."""
    excluded_paths = {item["path"]: item["reason"] for item in EXCLUDED_ENDPOINTS}

    # 나라장터 수집 실행
    assert "/api/v1/bids/collect" in excluded_paths
    assert "수집" in excluded_paths["/api/v1/bids/collect"]

    # 적격심사 통합 분석 (내부적으로 스냅샷을 DB에 commit하므로 제외 필수)
    assert "/api/v1/evaluations/analyze" in excluded_paths
    assert "commit" in excluded_paths["/api/v1/evaluations/analyze"]

    # 프로필 생성/수정/삭제
    assert "/api/v1/evaluations/profiles" in excluded_paths
    assert "/api/v1/evaluations/profiles/{profile_id}" in excluded_paths

    # 자동화 실행
    assert "/api/v1/automation/run/*" in excluded_paths
    assert "/api/v1/automation/job/{job_id}/confirm" in excluded_paths

    # 계정 생성/로그아웃
    assert "/api/v1/accounts/signup" in excluded_paths
    assert "/api/v1/accounts/logout" in excluded_paths


def test_filter_endpoints_selection():
    """이름 필터링으로 원하는 엔드포인트만 선별할 수 있는지 검증."""
    selected = filter_endpoints("accounts_me,evaluations_profiles")
    names = [ep.name for ep in selected]
    assert names == ["accounts_me", "evaluations_profiles"]

    # None 또는 빈 문자열이면 전체 반환
    all_selected = filter_endpoints(None)
    assert len(all_selected) == len(TARGET_ENDPOINTS)


def test_filter_endpoints_invalid_name_raises():
    """존재하지 않는 엔드포인트 이름 지정 시 ValueError 가 발생하는지 검증."""
    with pytest.raises(ValueError, match="선택된 엔드포인트가 없습니다"):
        filter_endpoints("invalid_endpoint_name")


# =============================================================================
# 3. 백분위수 및 집계 로직 검증
# =============================================================================


def test_calculate_percentile_empty_returns_nan():
    """빈 표본에 대해 nan 을 반환하는지 검증."""
    assert math.isnan(calculate_percentile([], 50.0))


def test_calculate_percentile_known_samples():
    """알려진 표본에 대해 백분위수를 선형 보간으로 정확히 계산하는지 검증."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    # P50 (중앙값) = 30.0
    assert calculate_percentile(values, 50.0) == pytest.approx(30.0)
    # P0 (최소) = 10.0
    assert calculate_percentile(values, 0.0) == pytest.approx(10.0)
    # P100 (최대) = 50.0
    assert calculate_percentile(values, 100.0) == pytest.approx(50.0)
    # P95: index = 4 * 0.95 = 3.8 -> 40.0 * 0.2 + 50.0 * 0.8 = 48.0
    assert calculate_percentile(values, 95.0) == pytest.approx(48.0)


def test_summarize_latencies_computes_stats():
    """summarize_latencies 가 P50, P95, 최대, 최소, 평균 및 요청 수를 정확히 집계하는지 검증."""
    ep = EndpointSpec("test_ep", "GET", "/test", "설명")
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = summarize_latencies(
        endpoint=ep,
        mode="single_warm",
        total_requests=5,
        latencies=latencies,
        errors=0,
    )

    assert result.endpoint_name == "test_ep"
    assert result.mode == "single_warm"
    assert result.total_requests == 5
    assert result.successful_requests == 5
    assert result.error_count == 0
    assert result.p50_ms == pytest.approx(30.0)
    assert result.p95_ms == pytest.approx(48.0)
    assert result.max_ms == pytest.approx(50.0)
    assert result.min_ms == pytest.approx(10.0)
    assert result.mean_ms == pytest.approx(30.0)


def test_summarize_latencies_all_errors():
    """모든 요청이 실패했을 때 통계치가 None 으로 설정되고 에러 건수가 보존되는지 검증."""
    ep = EndpointSpec("test_ep", "GET", "/test", "설명")
    result = summarize_latencies(
        endpoint=ep,
        mode="concurrency",
        total_requests=10,
        latencies=[],
        errors=10,
    )

    assert result.total_requests == 10
    assert result.successful_requests == 0
    assert result.error_count == 10
    assert result.p50_ms is None
    assert result.p95_ms is None


# =============================================================================
# 4. 자격 증명 해석 검증
# =============================================================================


def test_resolve_credentials_from_args():
    """명령줄 인자로 전달된 계정이 최우선으로 해석되는지 검증."""
    user, pwd, cookie = resolve_credentials(
        username="cli_user",
        password="cli_password",
        session_cookie=None,
    )
    assert user == "cli_user"
    assert pwd == "cli_password"  # noqa: S105
    assert cookie is None


def test_resolve_credentials_from_env(monkeypatch):
    """환경변수 BENCHMARK_USERNAME, BENCHMARK_PASSWORD 가 정상 해석되는지 검증."""
    monkeypatch.setenv("BENCHMARK_USERNAME", "env_user")
    monkeypatch.setenv("BENCHMARK_PASSWORD", "env_pass")

    user, pwd, cookie = resolve_credentials(None, None, None)
    assert user == "env_user"
    assert pwd == "env_pass"  # noqa: S105
    assert cookie is None


def test_resolve_credentials_session_cookie_strips_prefix():
    """세션 쿠키에 bidbox_session= 접두사가 있어도 토큰 값만 추출되는지 검증."""
    user, pwd, cookie = resolve_credentials(
        username=None,
        password=None,
        session_cookie="bidbox_session=raw_token_xyz",
    )
    assert user is None
    assert pwd is None
    assert cookie == "raw_token_xyz"


def test_resolve_credentials_none_when_empty(monkeypatch):
    """인자나 환경변수가 모두 없을 때 None을 반환하는지 검증 (기본 계정 하드코딩 부재)."""
    monkeypatch.delenv("BENCHMARK_USERNAME", raising=False)
    monkeypatch.delenv("BENCHMARK_PASSWORD", raising=False)
    monkeypatch.delenv("BENCHMARK_AUTH_USERNAME", raising=False)
    monkeypatch.delenv("BENCHMARK_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("BENCHMARK_SESSION_COOKIE", raising=False)

    user, pwd, cookie = resolve_credentials(None, None, None)
    assert user is None
    assert pwd is None
    assert cookie is None


# =============================================================================
# 5. 로그인 및 측정 하니스 동작 검증
# =============================================================================


def test_login_and_obtain_session_cookie_success(monkeypatch):
    """로그인 요청 1회로 세션 쿠키를 성공적으로 받아오는지 모의 검증."""

    def fake_post(url, json, timeout):
        req = httpx.Request("POST", url)
        resp = httpx.Response(
            status_code=200,
            request=req,
            headers=[
                ("set-cookie", f"{SESSION_COOKIE_NAME}=mock_issued_session_token; Path=/; HttpOnly")
            ],
            json={"username": json["username"]},
        )
        return resp

    monkeypatch.setattr(httpx, "post", fake_post)

    token = login_and_obtain_session_cookie(
        base_url="http://127.0.0.1:8000",
        username="test_admin",
        password="test_password",
    )
    assert token == "mock_issued_session_token"  # noqa: S105


def test_login_and_obtain_session_cookie_failure(monkeypatch):
    """로그인 실패 시 RuntimeError 를 발생시키는지 검증."""

    def fake_post(url, json, timeout):
        return httpx.Response(status_code=401, text="인증 실패")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(RuntimeError, match="로그인 실패"):
        login_and_obtain_session_cookie(
            base_url="http://127.0.0.1:8000",
            username="test_admin",
            password="wrong_password",
        )


def test_measure_single_warm_runs_warmup_and_rounds():
    """measure_single_warm 이 워밍업과 본 측정 횟수만큼 클라이언트를 호출하는지 검증."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = httpx.Response(status_code=200)

    ep = EndpointSpec("test_ep", "GET", "/api/v1/accounts/me", "설명")

    res = measure_single_warm(
        client=mock_client,
        endpoint=ep,
        warmup_rounds=2,
        rounds=5,
    )

    # 총 호출 횟수 = 워밍업 2회 + 본 측정 5회 = 7회
    assert mock_client.request.call_count == 7
    assert res.total_requests == 5
    assert res.successful_requests == 5
    assert res.error_count == 0
    assert res.p50_ms is not None


def test_dry_run_flag_exits_cleanly(capsys):
    """--dry-run 실행 시 실제 네트워크 없이 0으로 정상 종료되고 사양이 출력되는지 검증."""
    with patch("sys.argv", ["benchmark_auth_paths.py", "--dry-run"]):
        code = main()
        assert code == 0

    captured = capsys.readouterr()
    assert "인증 경로 레이턴시 벤치마크 (DRY RUN)" in captured.out
    assert "accounts_me" in captured.out
    assert "POST /api/v1/bids/collect" in captured.out


def test_main_missing_credentials_returns_code_2(monkeypatch, capsys):
    """자격 증명이 없을 때 측정을 시작하지 않고 exit_code 2 로 거부하는지 검증."""
    monkeypatch.delenv("BENCHMARK_USERNAME", raising=False)
    monkeypatch.delenv("BENCHMARK_PASSWORD", raising=False)
    monkeypatch.delenv("BENCHMARK_SESSION_COOKIE", raising=False)

    with patch("sys.argv", ["benchmark_auth_paths.py"]):
        code = main()
        assert code == 2

    captured = capsys.readouterr()
    assert "자격 증명이 주어지지 않았습니다" in captured.err
