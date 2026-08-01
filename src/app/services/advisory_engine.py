"""
src/app/services/advisory_engine.py

선제적 제안 엔진 (원본 apps/chatbot/services/advisory_engine.py 1:1 이식).
시스템 상태, 작업 이력, AI 성능 지표를 분석해 사용자에게 다음 조치를 제안합니다.
카테고리 가중치, 심각도/우선순위 점수, 상위 3건 노출 규칙을 그대로 보존합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.app.models.chatbot import AutomationRequest, KnowledgeBaseStatus
from src.app.schemas.chat import AdvisorySignal

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
HEALTH_CHECK_ACTIONS = ("full_validation", "preflight_check")


class AdvisoryEngine:
    """고도화된 Proactive Advisory 엔진."""

    CATEGORY_WEIGHTS = {
        "preflight": 1.5,  # 시스템 가용성 최우선
        "knowledge_base": 1.3,  # 데이터 신뢰성 중요
        "automation": 1.2,  # 작업 연속성
        "prediction": 1.1,  # 분석 품질
        "ingestion": 1.0,  # 수집 주기
        "general": 0.8,
    }

    def suggest(
        self,
        db: Session,
        *,
        user_id: int | None = None,
        request_obj: AutomationRequest | None = None,
    ) -> list[dict[str, Any]]:
        signals: list[AdvisorySignal] = []
        now = datetime.utcnow()

        # 1. 지식베이스 상태 분석
        latest_kb = db.execute(
            select(KnowledgeBaseStatus).order_by(KnowledgeBaseStatus.updated_at.desc()).limit(1)
        ).scalar_one_or_none()
        if latest_kb and latest_kb.updated_at:
            kb_age = now - latest_kb.updated_at
            if kb_age > timedelta(hours=48):
                signals.append(
                    AdvisorySignal(
                        action_key="kb_refresh",
                        message=(
                            f"KB 최신화가 {int(kb_age.total_seconds() // 3600)}시간 이상 지연돼 "
                            "`kb_refresh` 점검이 필요합니다."
                        ),
                        severity="critical",
                        priority="urgent",
                        category="knowledge_base",
                        reason_code="kb_stale_48h",
                    )
                )
            elif kb_age > timedelta(hours=24):
                signals.append(
                    AdvisorySignal(
                        action_key="kb_refresh",
                        message=(
                            f"KB 최신화가 {int(kb_age.total_seconds() // 3600)}시간 이상 지연돼 "
                            "`kb_refresh` 점검을 권장합니다."
                        ),
                        severity="warning",
                        priority="high",
                        category="knowledge_base",
                        reason_code="kb_stale_24h",
                    )
                )

            if (latest_kb.source_bid_count or 0) <= 0:
                signals.append(
                    AdvisorySignal(
                        action_key="kb_refresh",
                        message="KB 반영 공고 수가 0건이라 `kb_refresh` 재실행이 필요할 수 있습니다.",
                        severity="critical",
                        priority="urgent",
                        category="knowledge_base",
                        reason_code="kb_empty",
                    )
                )

        # 2. 최근 작업 결과 기반 분석
        scoped_request = request_obj or self._latest_request(db, user_id=user_id)
        if scoped_request:
            signals.extend(self._from_result_payload(scoped_request.result_payload or {}))

        # 3. 누적 실패 분석
        recent_failures = self._recent_failure_count(db, user_id=user_id)
        if recent_failures >= 3:
            signals.append(
                AdvisorySignal(
                    action_key="full_validation",
                    message="최근 자동화 실패가 3회 이상 누적되어 `full_validation` 우선 점검이 필요합니다.",
                    severity="critical",
                    priority="urgent",
                    category="automation",
                    reason_code="recent_failures_critical",
                )
            )
        elif recent_failures >= 2:
            signals.append(
                AdvisorySignal(
                    action_key="full_validation",
                    message=(
                        "최근 자동화 실패가 누적되어 `full_validation` 또는 "
                        "`preflight_check` 점검을 권장합니다."
                    ),
                    severity="warning",
                    priority="high",
                    category="automation",
                    reason_code="recent_failures_warning",
                )
            )

        return self._rank_and_format(signals)[:3]

    def suggestion_texts(
        self,
        db: Session,
        *,
        user_id: int | None = None,
        request_obj: AutomationRequest | None = None,
    ) -> list[str]:
        return [item["message"] for item in self.suggest(db, user_id=user_id, request_obj=request_obj)]

    def merge_with_base(
        self,
        db: Session,
        base: list[str],
        *,
        user_id: int | None = None,
        request_obj: AutomationRequest | None = None,
    ) -> list[str]:
        merged = list(base or [])
        for suggestion in self.suggestion_texts(db, user_id=user_id, request_obj=request_obj):
            if suggestion not in merged:
                merged.append(suggestion)
        return merged

    def _rank_and_format(self, signals: list[AdvisorySignal]) -> list[dict[str, Any]]:
        """신호를 점수 기반으로 정렬하고 중복 메시지를 제거합니다."""
        unique: dict[str, AdvisorySignal] = {}
        for signal in signals:
            message = signal.message.strip()
            if not message:
                continue
            existing = unique.get(message)
            if existing is None or signal.get_score(self.CATEGORY_WEIGHTS) > existing.get_score(
                self.CATEGORY_WEIGHTS
            ):
                unique[message] = signal

        ordered = sorted(
            unique.values(), key=lambda s: s.get_score(self.CATEGORY_WEIGHTS), reverse=True
        )
        return [signal.model_dump() for signal in ordered]

    def _latest_request(self, db: Session, *, user_id: int | None = None) -> AutomationRequest | None:
        stmt = select(AutomationRequest).where(
            or_(
                AutomationRequest.result_payload.is_(None),
                AutomationRequest.result_payload != {},
            )
        )
        if user_id is not None:
            stmt = stmt.where(AutomationRequest.user_id == user_id)
        stmt = stmt.order_by(
            AutomationRequest.completed_at.desc(), AutomationRequest.created_at.desc()
        ).limit(1)
        return db.execute(stmt).scalar_one_or_none()

    def _recent_failure_count(self, db: Session, *, user_id: int | None = None) -> int:
        since = datetime.utcnow() - timedelta(days=3)

        health_stmt = select(AutomationRequest).where(
            AutomationRequest.created_at >= since,
            AutomationRequest.status == STATUS_SUCCESS,
            AutomationRequest.action_key.in_(HEALTH_CHECK_ACTIONS),
        )
        if user_id is not None:
            health_stmt = health_stmt.where(AutomationRequest.user_id == user_id)
        latest_health_check = db.execute(
            health_stmt.order_by(
                AutomationRequest.completed_at.desc(), AutomationRequest.created_at.desc()
            ).limit(1)
        ).scalar_one_or_none()

        stmt = select(func.count(AutomationRequest.id)).where(
            AutomationRequest.created_at >= since,
            AutomationRequest.status == STATUS_FAILED,
        )
        if user_id is not None:
            stmt = stmt.where(AutomationRequest.user_id == user_id)
        if latest_health_check is not None:
            checkpoint_at = latest_health_check.completed_at or latest_health_check.created_at
            stmt = stmt.where(AutomationRequest.created_at > checkpoint_at)
        return int(db.scalar(stmt) or 0)

    def _from_result_payload(self, result_payload: dict) -> list[AdvisorySignal]:
        signals: list[AdvisorySignal] = []
        steps = result_payload.get("steps") or {}
        inspect_metrics = (steps.get("inspect") or {}).get("metrics") or {}
        predict_metrics = (steps.get("predict") or {}).get("metrics") or {}
        rag_metrics = (steps.get("rag") or {}).get("metrics") or {}

        today_rows = inspect_metrics.get("today_rows")
        if today_rows is not None and int(today_rows) <= 0:
            signals.append(
                AdvisorySignal(
                    action_key="collect_refresh",
                    message=(
                        "오늘 신규 수집 데이터가 없어 `collect_refresh` 또는 "
                        "`preflight_check` 점검을 권장합니다."
                    ),
                    severity="warning",
                    priority="high",
                    category="ingestion",
                    reason_code="today_rows_zero",
                )
            )

        if inspect_metrics.get("api_check") is False:
            signals.append(
                AdvisorySignal(
                    action_key="preflight_check",
                    message="보호 API 점검 실패 이력이 있어 `preflight_check`를 먼저 권장합니다.",
                    severity="critical",
                    priority="urgent",
                    category="preflight",
                    reason_code="api_check_failed",
                )
            )

        avg_r2 = predict_metrics.get("avg_r2")
        pass_all = predict_metrics.get("pass_all")
        if avg_r2 is not None and float(avg_r2) < 0.5:
            signals.append(
                AdvisorySignal(
                    action_key="prediction_validate",
                    message="최근 예측 성능이 크게 낮아 `prediction_validate` 재실행이 필요합니다.",
                    severity="critical",
                    priority="urgent",
                    category="prediction",
                    reason_code="avg_r2_critical",
                )
            )
        elif avg_r2 is not None and float(avg_r2) < 0.6:
            signals.append(
                AdvisorySignal(
                    action_key="prediction_validate",
                    message="최근 예측 성능이 낮아 `prediction_validate` 재실행을 권장합니다.",
                    severity="warning",
                    priority="high",
                    category="prediction",
                    reason_code="avg_r2_warning",
                )
            )
        elif pass_all is False:
            signals.append(
                AdvisorySignal(
                    action_key="prediction_validate",
                    message="모델 acceptance 기준이 통과되지 않아 `prediction_validate` 확인을 권장합니다.",
                    severity="warning",
                    priority="medium",
                    category="prediction",
                    reason_code="acceptance_failed",
                )
            )

        source_bid_count = rag_metrics.get("source_bid_count")
        if source_bid_count is not None and int(source_bid_count) <= 0:
            signals.append(
                AdvisorySignal(
                    action_key="kb_refresh",
                    message="RAG 반영 공고 수가 부족해 `kb_refresh`를 권장합니다.",
                    severity="warning",
                    priority="high",
                    category="knowledge_base",
                    reason_code="rag_source_empty",
                )
            )
        return signals
