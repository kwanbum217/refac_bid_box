"""
src/app/services/action_catalog.py

자동화 액션 카탈로그 (원본 apps/chatbot/services/action_catalog.py 1:1 이식).
실행 백엔드는 Harness 대신 Arq 태스크 큐를 사용하지만, 액션 키/의도/키워드/정책은 원본과 동일합니다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationAction:
    action_key: str
    intent: str
    display_name: str
    pipeline_id: str
    run_mode: str
    mutating: bool
    high_cost: bool
    followup_after_completion: bool
    keywords: tuple[str, ...]


STAGING_PIPELINE_ID = "BIDBOX_Personal_Pipeline_Staging"
DEFAULT_POLL_AFTER_MS = 3000

ACTION_CATALOG = {
    "preflight_check": AutomationAction(
        action_key="preflight_check",
        intent="preflight_check",
        display_name="스테이징 사전 점검",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="preflight_only",
        mutating=False,
        high_cost=False,
        followup_after_completion=False,
        keywords=("사전 점검", "프리플라이트", "preflight", "연결 확인", "상태 점검"),
    ),
    "collect_refresh": AutomationAction(
        action_key="collect_refresh",
        intent="collect_refresh",
        display_name="입찰 수집 실행",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="collect_only",
        mutating=True,
        high_cost=False,
        followup_after_completion=False,
        keywords=("수집", "공고 업데이트", "신규 공고 반영", "데이터 다시"),
    ),
    "kb_refresh": AutomationAction(
        action_key="kb_refresh",
        intent="kb_refresh",
        display_name="지식베이스 갱신",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="kb_only",
        mutating=True,
        high_cost=False,
        followup_after_completion=False,
        keywords=(
            "kb 업데이트",
            "kb 최신화",
            "지식베이스",
            "지식베이스 업데이트",
            "지식베이스 최신화",
            "벡터 갱신",
            "벡터 업데이트",
            "벡터 최신화",
            "임베딩 갱신",
            "임베딩 업데이트",
            "임베딩 최신화",
            "색인 갱신",
            "색인 업데이트",
            "색인 최신화",
        ),
    ),
    "prediction_validate": AutomationAction(
        action_key="prediction_validate",
        intent="prediction_validate",
        display_name="예측 모델 검증",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="predict_only",
        mutating=False,
        high_cost=False,
        followup_after_completion=False,
        keywords=("예측 다시", "예측 재실행", "투찰가 다시", "예측 돌려", "모델 검증"),
    ),
    "data_refresh": AutomationAction(
        action_key="data_refresh",
        intent="data_refresh",
        display_name="데이터 갱신 후 분석",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="refresh_data",
        mutating=True,
        high_cost=False,
        followup_after_completion=True,
        keywords=("데이터 갱신", "최신 데이터 반영", "새로고침", "업데이트 후", "갱신해서"),
    ),
    "full_validation": AutomationAction(
        action_key="full_validation",
        intent="full_validation",
        display_name="스테이징 전체 검증",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="manual_full",
        mutating=True,
        high_cost=True,
        followup_after_completion=True,
        keywords=("전체 실행", "manual_full", "풀 파이프라인", "종합 점검", "전체 점검"),
    ),
    "model_retrain": AutomationAction(
        action_key="model_retrain",
        intent="model_retrain",
        display_name="예측 모델 재학습",
        pipeline_id=STAGING_PIPELINE_ID,
        run_mode="retrain_only",
        mutating=True,
        high_cost=True,
        followup_after_completion=True,
        keywords=("모델 재학습", "재학습 실행", "재훈련", "모델 다시 학습"),
    ),
}

ACTION_KEY_BY_INTENT = {action.intent: action.action_key for action in ACTION_CATALOG.values()}

LEGACY_INTENT_TO_ACTION = {
    "run_collect_bids": "collect_refresh",
    "run_update_hybrid_kb": "kb_refresh",
    "run_prediction": "prediction_validate",
    "run_manual_full": "full_validation",
}


def get_action(action_key: str) -> AutomationAction | None:
    return ACTION_CATALOG.get(action_key)


def get_action_by_intent(intent: str) -> AutomationAction | None:
    mapped_key = LEGACY_INTENT_TO_ACTION.get(intent, intent)
    return ACTION_CATALOG.get(mapped_key)
