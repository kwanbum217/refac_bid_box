"""
src/app/services/automation_callbacks.py

자동화 워커 콜백 배달 및 경로 결정 모듈.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.app.core.config import settings
from src.app.models.chatbot import AutomationRequest

# 워커가 결과를 되돌려 보낼 API 경로 (automation 라우터와 일치해야 합니다)
CALLBACK_PATH_TEMPLATE = "/api/v1/automation/job/{job_id}/callback"


@dataclass(frozen=True)
class CallbackDelivery:
    """워커 실행 결과가 요청 레코드로 되돌아오는 경로."""

    mode: str
    configured: bool
    callback_url: str
    base_url: str
    reason: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "callback_mode": self.mode,
            "callback_configured": self.configured,
            "callback_reason": self.reason,
            "callback_url": self.callback_url,
            "callback_base_url": self.base_url,
        }


def _is_worker_unreachable_host(hostname: str) -> bool:
    """워커가 도달할 수 없는 호스트인지 판정합니다.

    원본은 외부 SaaS(Harness)가 호출자였기 때문에 사설 대역 전체를 거부했습니다.
    Arq 워커는 같은 네트워크 안에 있으므로 그 규칙을 그대로 쓰면 안 됩니다.
    `http://app:8000`, `http://10.0.0.5` 같은 사설 주소가 오히려 정상 설정입니다.

    거부 대상은 루프백뿐입니다. 워커가 별도 컨테이너일 때 루프백은 앱이 아니라
    워커 자기 자신을 가리키므로 결과가 영영 돌아오지 않습니다.
    """
    host = (hostname or "").strip().lower().strip("[]")
    if not host:
        return True
    # 바인딩이 아니라 로컬 호스트 판별용 비교입니다
    if host in {"localhost", "0.0.0.0", "::1"} or host.endswith(".localhost"):  # nosec B104
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # 호스트명은 컨테이너 서비스명일 수 있으므로 통과시킵니다.
        return False
    return bool(address.is_loopback or address.is_unspecified)


def resolve_callback_delivery(job_id: str) -> CallbackDelivery:
    """실행 결과 수신 경로를 결정합니다 (원본 resolve_callback_delivery 의 Arq 판).

    | 조건 | 모드 |
    | --- | --- |
    | 콜백 주소 없음 + 워커가 DB 공유 | `direct` (워커가 DB 에 바로 기록) |
    | 콜백 주소 없음 + DB 미공유 | `polling` (되돌릴 경로 없음) |
    | 콜백 주소 형식 오류 / 루프백 | `polling` 또는 DB 공유 시 `direct` 로 강등 |
    | 콜백 주소 정상 | `callback` (워커가 HTTP 로 보고) |
    """
    base_url = (settings.AUTOMATION_CALLBACK_BASE_URL or "").strip()
    shares_db = bool(settings.AUTOMATION_WORKER_SHARES_DB)

    def _fallback(reason: str, checked_base_url: str = "") -> CallbackDelivery:
        if shares_db:
            return CallbackDelivery(
                mode="direct",
                configured=True,
                callback_url="",
                base_url=checked_base_url,
                reason=reason,
            )
        return CallbackDelivery(
            mode="polling",
            configured=False,
            callback_url="",
            base_url=checked_base_url,
            reason=reason,
        )

    if not base_url:
        return _fallback(
            "워커가 앱과 같은 DB 에 결과를 직접 기록합니다."
            if shares_db
            else "워커 콜백 주소가 없고 DB 도 공유하지 않아 상태 조회로만 확인합니다."
        )

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _fallback("워커 콜백 주소 형식이 올바르지 않습니다.", base_url)

    if _is_worker_unreachable_host(parsed.hostname or ""):
        return _fallback(
            "워커 콜백 주소가 루프백이라 별도 프로세스인 워커가 앱에 도달할 수 없습니다.",
            base_url.rstrip("/"),
        )

    normalized = base_url.rstrip("/")
    return CallbackDelivery(
        mode="callback",
        configured=True,
        callback_url=f"{normalized}{CALLBACK_PATH_TEMPLATE.format(job_id=job_id)}",
        base_url=normalized,
        reason="",
    )


def _callback_metadata(request_obj: AutomationRequest) -> dict[str, Any]:
    payload = dict(request_obj.payload or {})
    return {
        "callback_mode": str(payload.get("callback_mode") or "polling"),
        "callback_configured": bool(payload.get("callback_configured")),
        "callback_reason": str(payload.get("callback_reason") or ""),
        "callback_url": str(payload.get("callback_url") or ""),
        "callback_base_url": str(payload.get("callback_base_url") or ""),
    }


def _callback_status_lines(request_obj: AutomationRequest) -> list[str]:
    metadata = _callback_metadata(request_obj)
    mode = metadata["callback_mode"]
    if mode in {"callback", "direct"}:
        lines = [f"- 결과 수신 방식: `{mode}`"]
        # direct 는 정상 경로지만 콜백 설정이 잘못돼 강등된 경우를 알려줍니다.
        if mode == "direct" and metadata["callback_base_url"]:
            lines.append(f"- 안내: {metadata['callback_reason']}")
        return lines

    reason = (
        metadata["callback_reason"] or "워커 콜백이 설정되지 않아 polling으로 상태를 확인합니다."
    )
    return ["- 결과 수신 방식: `polling`", f"- 안내: {reason}"]
