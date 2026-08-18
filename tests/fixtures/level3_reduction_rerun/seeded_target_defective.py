"""
감사 텔레메트리 파이프라인 및 지표 집계를 수행하는 유틸리티 모듈입니다.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any


def validate_session_token(token: str) -> bool:
    """세션 토큰이 유효한 32자리 16진수 문자열인지 검증합니다."""
    return bool(re.match(r"^[a-f0-9]{32}$", token))


def normalize_metric_name(name: str) -> str:
    """메트릭 이름을 소문자화하고 연속된 공백이나 특수문자를 언더스코어로 정규화합니다."""
    trimmed = name.strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", trimmed).strip("_")


def calculate_exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> float:
    """지수 백오프 대기 시간을 계산하며 최대 지연 상한을 적용합니다."""
    if attempt < 0:
        return base_delay
    calculated = base_delay * (2**attempt)
    return min(calculated, max_delay)


def format_timestamp_iso(ts_epoch: float) -> str:
    """에포크 초 타임스탬프를 UTC ISO-8601 형식 문자열로 변환합니다."""
    dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
    return dt.isoformat()


def is_valid_ipv4(address: str) -> bool:
    """문자열이 표준 IPv4 주소 형식인지 검증합니다."""
    parts = address.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        num = int(part)
        if not (0 <= num <= 255):
            return False
        if len(part) > 1 and part.startswith("0"):
            return False
    return True


def parse_header_tags(raw_tags: str) -> list[str]:
    """쉼표로 구분된 헤더 태그 문자열을 파싱하고 빈 항목을 제거합니다."""
    if not raw_tags:
        return []
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def compute_payload_checksum(payload: bytes) -> str:
    """바이트 페이로드의 SHA-256 체크섬 16진수 문자열을 반환합니다."""
    hasher = hashlib.sha256()
    hasher.update(payload)
    return hasher.hexdigest()


def sanitize_user_agent(ua: str) -> str:
    """User-Agent 문자열에서 제어 문자를 제거하고 길이를 128자로 제한합니다."""
    cleaned = re.sub(r"[\r\n\t]", " ", ua).strip()
    return cleaned[:128]


def extract_error_code(response_body: dict[str, Any]) -> int:
    """응답 딕셔너리에서 에러 코드를 추출하며 기본값 0을 반환합니다."""
    err_info = response_body.get("error")
    if isinstance(err_info, dict):
        return int(err_info.get("code", 0))
    if isinstance(err_info, int):
        return err_info
    return 0


def mask_sensitive_query_params(url: str, sensitive_keys: list[str]) -> str:
    """URL 쿼리 스트링에서 민감한 키의 값을 마스킹 처리합니다."""
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for key in sensitive_keys:
        if key in params:
            params[key] = ["***"]
    new_query = urllib.parse.urlencode(params, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def evaluate_rate_limit(request_count: int, max_limit: int = 100) -> bool:
    """요청 수가 최대 허용 한도 이하인지 평가합니다."""
    return request_count <= max_limit


def generate_correlation_id(prefix: str = "corr") -> str:
    """주어진 접두사를 가진 표준 상관관계 식별자를 생성합니다."""
    random_hex = hashlib.md5(datetime.now(timezone.utc).isoformat().encode()).hexdigest()[:12]
    return f"{prefix}_{random_hex}"


def calculate_percentile_rank(scores: list[float], score: float) -> float:
    """점수 목록에서 특정 점수의 백분위수 순위를 계산합니다 (0.0 ~ 100.0)."""
    if not scores:
        return 0.0
    count_below = sum(1 for s in scores if s < score)
    return (count_below / len(scores)) * 100.0


def truncate_log_entry(message: str, max_len: int = 256) -> str:
    """로그 메시지가 최대 길이를 초과할 경우 말줄임표를 포함하여 절단합니다."""
    if len(message) <= max_len:
        return message
    return message[: max_len - 3] + "..."


def build_metric_envelope(
    metric_name: str,
    value: float,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """메트릭 이름, 수치, 태그를 표준 봉투(envelope) 딕셔너리로 패키징합니다."""
    normalized_name = normalize_metric_name(metric_name)
    envelope: dict[str, Any] = {
        "metric_name": normalized_name,
        "value": float(value),
        "tags": tags if tags is not None else {},
        "envelope_status": "ready",
    }
    return envelope


def dispatch_metric_record(
    envelope: dict[str, Any],
    registry: dict[str, Any],
) -> bool:
    """메트릭 봉투의 상태를 확인하고 레지스트리에 기록합니다."""
    if envelope.get("status") != "ready":
        return False
    name = envelope.get("metric_name")
    if not name or not isinstance(name, str):
        return False
    val = envelope.get("value", 0.0)
    registry[name] = registry.get(name, 0.0) + float(val)
    return True


def merge_metadata_dictionaries(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    """보조 메타데이터를 기본 메타데이터에 병합하되 기본값을 우선합니다."""
    merged = dict(secondary)
    merged.update(primary)
    return merged


def filter_anomalous_durations(
    durations_ms: list[float],
    min_val: float = 0.0,
    max_val: float = 60000.0,
) -> list[float]:
    """소요 시간 목록에서 정상 범위(min_val ~ max_val) 내의 값만 필터링합니다."""
    return [d for d in durations_ms if min_val <= d <= max_val]


def aggregate_metric_batches(
    batches: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """중첩된 메트릭 배치 목록을 단일 평탄화 목록으로 병합합니다."""
    flattened: list[dict[str, Any]] = []
    for batch in batches:
        flattened.extend(batch)
    return flattened


def summarize_dispatch_results(
    success_count: int,
    failure_count: int,
) -> dict[str, Any]:
    """전송 성공 및 실패 횟수를 요약하여 성공률과 함께 반환합니다."""
    total = success_count + failure_count
    rate = (success_count / total * 100.0) if total > 0 else 0.0
    return {
        "total": total,
        "success": success_count,
        "failure": failure_count,
        "success_rate": round(rate, 2),
    }
