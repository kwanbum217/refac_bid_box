"""
src/tasks/notifier.py

MLOps 알림 발신. 설계는 `docs/design/mlops_notification_20260805.md`.

실행 백엔드를 Arq 로 옮기면서 Harness 대시보드가 주던 운영 가시성이 사라졌습니다.
재학습이 실패해도, 승격할 만한 챌린저가 나와도 아무 데로도 전달되지 않습니다.
승격이 수동인 이상 그 사실이 사람에게 닿아야 고리가 이어집니다.

**알림 실패가 본 작업을 되돌리면 안 됩니다.** 웹훅이 죽었다고 재학습 결과가
날아가면 본말전도이므로, 이 모듈의 모든 발신은 예외를 삼키고 로그만 남깁니다.
원본 기록은 `retrain_logs` 에 남으므로 재시도도 두지 않습니다.
"""

from __future__ import annotations

import logging
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10.0

LEVEL_PREFIX = {
    "info": "[알림]",
    "warning": "[경고]",
    "action": "[조치 필요]",
}

# 승격 권고 알림에 반드시 따라붙는 문구입니다. 2026-08-05 에 홀드아웃 개선이
# 운영 쌍대 비교에서 세 번 연속 재현되지 않았으므로, 알림이 곧바로 승격을
# 권하는 문구가 되면 안 됩니다.
PAIRED_CHECK_HINT = (
    "승격 전 운영 경로 쌍대 비교를 거치십시오.\n"
    "  uv run python scripts/compare_servc_models_paired.py\n"
    "  uv run python scripts/promote_model.py status\n"
    "  uv run python scripts/promote_model.py promote --model <이름> --apply"
)


def _format_message(title: str, lines: list[str], level: str) -> str:
    prefix = LEVEL_PREFIX.get(level, LEVEL_PREFIX["info"])
    body = "\n".join(f"  {line}" for line in lines)
    return f"{prefix} {title}\n{body}" if body else f"{prefix} {title}"


async def notify(title: str, lines: list[str], *, level: str = "info") -> None:
    """웹훅으로 한 건 보냅니다. URL 이 비어 있으면 아무 일도 하지 않습니다."""
    webhook_url = settings.MLOPS_WEBHOOK_URL
    if not webhook_url:
        return

    text = _format_message(title, lines, level)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(webhook_url, json={"text": text})
            response.raise_for_status()
    # 알림은 부가 기능입니다. 어떤 실패도 호출부로 전파시키지 않습니다.
    except Exception as exc:
        logger.warning("MLOps 알림 발신 실패: %s", exc)


def _format_metrics(metrics: dict[str, Any] | None) -> str:
    if not metrics:
        return "지표 없음"
    parts = []
    for key in ("r2", "rmse", "mape"):
        value = metrics.get(key)
        if value is None:
            continue
        try:
            parts.append(f"{key.upper()} {float(value):.4f}")
        except (TypeError, ValueError):
            continue
    return " / ".join(parts) if parts else "지표 없음"


async def notify_retrain_result(
    *,
    trigger_source: str,
    recommendation: str,
    champion_version: str,
    challenger_version: str,
    champion_metrics: dict[str, Any] | None,
    challenger_metrics: dict[str, Any] | None,
    samples: int,
    category: str | None = None,
    holdout_is_overfit: bool = False,
    champion_comparable: bool = True,
) -> None:
    """재학습 판정 결과를 알립니다.

    `REJECT_CHALLENGER` 는 **보내지 않습니다.** 대부분의 재학습이 기각으로
    끝나므로 그것까지 보내면 알림이 소음이 되고, 소음이 되면 정작 중요한
    승격 권고를 사람이 읽지 않게 됩니다.

    다만 홀드아웃 분리 실패로 기각된 경우는 예외입니다. 정상 기각이 아니라
    지표 자체를 믿을 수 없다는 신호이며, 표본 부족은 수집 쪽 문제입니다.
    """
    label = f"{category or '전체'} 모델"

    # 비교 대상이 없어 기각된 것은 정상 기각이 아닙니다. 게이트가 판단을
    # 못 한 상태이며, 담당자가 직접 봐야 진도가 나갑니다.
    if not champion_comparable:
        await notify(
            f"{label} 재학습 승격 판정 불가",
            [
                "서빙 중인 모델에 지표가 없어 챌린저와 비교할 수 없습니다.",
                f"challenger {challenger_version}  {_format_metrics(challenger_metrics)}",
                f"표본 {samples:,} / 트리거 {trigger_source}",
                "",
                "  uv run python scripts/promote_model.py status",
            ],
            level="warning",
        )
        return

    if holdout_is_overfit:
        await notify(
            f"{label} 재학습 지표 신뢰 불가",
            [
                "표본이 적어 홀드아웃 분리에 실패했습니다. 승격 판정을 신뢰할 수 없습니다.",
                f"표본 {samples:,} / 트리거 {trigger_source}",
            ],
            level="warning",
        )
        return

    if recommendation != "PROMOTE_CHALLENGER":
        return

    await notify(
        f"{label} 승격 권고",
        [
            f"champion   {champion_version or '없음'}  {_format_metrics(champion_metrics)}",
            f"challenger {challenger_version}  {_format_metrics(challenger_metrics)}",
            f"표본 {samples:,} / 트리거 {trigger_source}",
            "",
            *PAIRED_CHECK_HINT.split("\n"),
        ],
        level="action",
    )


async def notify_task_failure(task_name: str, error: str, *, detail: str = "") -> None:
    """스케줄·태스크 실패를 알립니다."""
    lines = [f"사유: {error}"]
    if detail:
        lines.append(detail)
    await notify(f"{task_name} 실패", lines, level="warning")


async def notify_empty_training_data(trigger_source: str, category: str | None) -> None:
    """학습 데이터가 비었음을 알립니다. 수집 파이프라인 이상 신호입니다."""
    await notify(
        "재학습 건너뜀: 학습 데이터 없음",
        [
            f"대상 {category or '전체'} / 트리거 {trigger_source}",
            "수집 파이프라인을 확인하십시오.",
        ],
        level="warning",
    )


async def notify_drift_detected(
    *,
    model_name: str,
    model_version: str,
    drift_features: list[dict[str, Any]],
    total_features_checked: int,
    evaluation_window_days: int,
    baseline_version: str,
    recent_samples: int,
) -> None:
    """PSI 드리프트 감지 시 조치 필요 알림을 발신합니다.

    자동 재학습이나 자동 승격으로 이어지지 않으며, 사람이 데이터 품질 및
    시장 변화를 검토한 뒤 수동 재학습 여부를 결정하도록 권고합니다.
    """
    lines = [
        f"모델: {model_name} (v{model_version})",
        f"기준 분포: {baseline_version}",
        f"평가 윈도우: 최근 {evaluation_window_days}일 / 표본 {recent_samples:,}건",
        f"전체 특징 {total_features_checked}개 중 {len(drift_features)}개에서 드리프트 감지 (PSI >= 0.2)",
        "",
    ]
    for feat in drift_features:
        feat_name = feat.get("feature", "unknown")
        psi_val = float(feat.get("psi", 0.0))
        sample_size = int(feat.get("sample_size", recent_samples))
        lines.append(f"  - {feat_name}: PSI={psi_val:.4f} (임계 0.2, 표본 {sample_size:,})")
    lines.extend(
        [
            "",
            "권장 조치:",
            "  1. 수집 파이프라인 데이터 품질 확인",
            "  2. 제도 변경·시장 환경 변화 여부 검토",
            "  3. 필요 시 수동 재학습 실행: uv run python scripts/retrain.py --category <코드>",
        ]
    )
    await notify(f"{model_name} 드리프트 감지", lines, level="action")
