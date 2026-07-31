"""
src/app/services/metric_interpreter.py

자동화 실행 지표 해석기 (원본 apps/chatbot/services/metric_interpreter.py 1:1 이식).
health_status(stable/warning/critical), insights, recommended_actions 산출 규칙을 보존합니다.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


class MetricInterpreter:
    def interpret(self, result_payload: dict | None) -> dict[str, Any]:
        payload = result_payload or {}
        steps = payload.get("steps") or {}
        insights: list[str] = []
        recommendations: list[str] = []
        severities: list[str] = []

        inspect_metrics = (steps.get("inspect") or {}).get("metrics") or {}
        predict_metrics = (steps.get("predict") or {}).get("metrics") or {}
        rag_metrics = (steps.get("rag") or {}).get("metrics") or {}
        final_metrics = (steps.get("final") or {}).get("metrics") or {}

        self._interpret_inspect(inspect_metrics, insights, recommendations, severities)
        self._interpret_predict(predict_metrics, insights, recommendations, severities)
        self._interpret_rag(rag_metrics, insights, recommendations, severities)
        self._interpret_final(final_metrics, steps, insights, recommendations, severities)

        return {
            "health_status": self._health_status(severities),
            "insights": list(dict.fromkeys(insights)),
            "recommended_actions": list(dict.fromkeys(recommendations)),
        }

    def _interpret_inspect(
        self,
        metrics: dict[str, Any],
        insights: list[str],
        recommendations: list[str],
        severities: list[str],
    ) -> None:
        if not metrics:
            return

        today_rows = metrics.get("today_rows")
        recent_bid_results = metrics.get("recent_bid_results")
        recent_bid_announcements = metrics.get("recent_bid_announcements")
        fresh_ingest_results = metrics.get("fresh_ingest_results")
        fresh_ingest_announcements = metrics.get("fresh_ingest_announcements")
        vector_count = metrics.get("vector_count")
        api_check = metrics.get("api_check")
        model_check = metrics.get("model_check")

        if today_rows is not None:
            if int(today_rows) <= 0:
                insights.append("오늘 신규 수집 데이터가 없어 수집 파이프라인 점검이 필요할 수 있습니다.")
                recommendations.extend(["collect_refresh 실행 검토", "preflight_check로 기본 상태 확인"])
                severities.append("warning")
            else:
                insights.append(f"오늘 신규 수집 데이터가 {int(today_rows)}건 반영되어 최신성은 유지되고 있습니다.")

        recent_values = [v for v in (recent_bid_results, recent_bid_announcements) if v is not None]
        if recent_values and max(int(v) for v in recent_values) <= 0:
            insights.append("최근 구간의 공고·낙찰 데이터가 비어 있어 추세 해석 신뢰도가 낮습니다.")
            recommendations.append("data_refresh 실행 검토")
            severities.append("warning")

        fresh_values = [v for v in (fresh_ingest_results, fresh_ingest_announcements) if v is not None]
        if fresh_values and max(int(v) for v in fresh_values) <= 0:
            insights.append("최근 수집 이력이 없어 배치 실행 누락 가능성을 확인해야 합니다.")
            recommendations.extend(["collect_refresh 실행 검토", "preflight_check로 기본 상태 확인"])
            severities.append("warning")

        if vector_count is not None:
            if int(vector_count) <= 0:
                insights.append("KB 벡터가 비어 있어 문맥 검색 품질이 크게 떨어질 수 있습니다.")
                recommendations.append("kb_refresh 실행 검토")
                severities.append("critical")
            elif int(vector_count) < 100:
                insights.append(f"KB 벡터 수가 {int(vector_count)}건으로 낮아 문맥 근거가 제한적일 수 있습니다.")
                recommendations.append("kb_refresh 실행 검토")
                severities.append("warning")
            else:
                insights.append(f"KB 벡터는 {int(vector_count)}건으로 유지되고 있습니다.")

        if api_check is False:
            insights.append("보호 API 체크가 실패해 서비스 응답 상태를 추가 점검해야 합니다.")
            recommendations.append("full_validation 실행 검토")
            severities.append("warning")

        if model_check is False:
            insights.append("모델 검증 단계가 생략되었거나 실패해 예측 결과 해석에 주의가 필요합니다.")
            recommendations.append("prediction_validate 실행 검토")
            severities.append("warning")

    def _interpret_predict(
        self,
        metrics: dict[str, Any],
        insights: list[str],
        recommendations: list[str],
        severities: list[str],
    ) -> None:
        if not metrics:
            return

        avg_r2 = metrics.get("avg_r2")
        pass_all = metrics.get("pass_all")
        model_name = metrics.get("model_name")

        if avg_r2 is not None:
            avg_r2_value = float(avg_r2)
            if avg_r2_value >= 0.8:
                insights.append(
                    f"예측 모델({model_name or 'unknown'}) 성능은 avg_r2={avg_r2_value:.3f}로 안정적인 수준입니다."
                )
            elif avg_r2_value >= 0.6:
                insights.append(
                    f"예측 모델 성능은 avg_r2={avg_r2_value:.3f}로 사용 가능하지만 추가 검증이 권장됩니다."
                )
                recommendations.append("prediction_validate 재실행 검토")
                severities.append("warning")
            else:
                insights.append(f"예측 모델 성능이 avg_r2={avg_r2_value:.3f}로 낮아 품질 점검이 필요합니다.")
                recommendations.append("prediction_validate 실행 검토")
                severities.append("critical")

        if pass_all is False:
            insights.append("모델 acceptance 기준이 통과되지 않아 예측 결과 활용에 주의가 필요합니다.")
            recommendations.append("prediction_validate 실행 검토")
            severities.append("critical")

    def _interpret_rag(
        self,
        metrics: dict[str, Any],
        insights: list[str],
        recommendations: list[str],
        severities: list[str],
    ) -> None:
        if not metrics:
            return

        source_bid_count = metrics.get("source_bid_count")
        if source_bid_count is None:
            return

        count = int(source_bid_count)
        if count <= 0:
            insights.append("KB 반영 공고 수가 0건이라 RAG 근거가 최신 상태를 반영하지 못할 수 있습니다.")
            recommendations.append("kb_refresh 실행 검토")
            severities.append("critical")
        else:
            insights.append(f"KB 반영 공고 수는 {count}건으로 기록되어 있습니다.")

    def _interpret_final(
        self,
        final_metrics: dict[str, Any],
        steps: dict[str, Any],
        insights: list[str],
        recommendations: list[str],
        severities: list[str],
    ) -> None:
        completed_steps = final_metrics.get("completed_steps") or []
        if completed_steps:
            insights.append("완료 단계: " + ", ".join(str(step) for step in completed_steps))

        expected_steps = {"preflight", "collect", "rag", "predict", "inspect"}
        present_steps = {name for name, payload in steps.items() if payload}
        missing_steps = sorted(expected_steps - present_steps)
        if missing_steps and present_steps.intersection(expected_steps):
            insights.append(
                "일부 단계 결과가 누락되어 전체 실행 맥락 해석이 제한됩니다: " + ", ".join(missing_steps)
            )
            recommendations.append("full_validation 실행 검토")
            severities.append("warning")

    def _health_status(self, severities: list[str]) -> str:
        if not severities:
            return "stable"
        counts = Counter(severities)
        if counts.get("critical"):
            return "critical"
        if counts.get("warning"):
            return "warning"
        return "stable"
