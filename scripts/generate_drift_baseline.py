"""학습 없이 drift baseline 을 만드는 정식 진입점.

학습 성공 경로(`ModelTrainer.train_and_register`) 밖에서 지정한 데이터 구간으로
`ml_registry/{model_name}/baseline/` 아티팩트를 생성합니다. 분포 계산은
`src.ml.monitoring.save_baseline_distributions` 를 재사용하며 새로 구현하지
않습니다. 특징 생성은 `src/ml/features.py` 단일 공급원만 사용합니다.

기본 동작은 dry-run 입니다. 인자 없이 실행하면 어떤 파일도 쓰지 않고 대상
구간, 조회 행 수, 특징 수, 저장될 경로만 출력합니다. 실제 기록은 `--write`
명시 플래그가 있을 때만 수행합니다.

`--baseline-version` 은 학습 버전이 아니라 baseline 식별자입니다. 존재하지
않는 학습 버전 문자열을 찍으면 provenance 가 거짓이 되므로 호출자가 명시해야
합니다.

구간 기준일은 `BidResult.rl_openg_dt` 반열림 구간(`[start_at, end_at)`)이며,
`--start-at` 참고 기준으로 `src/ml/features.py` 의 `REGIME_SHIFT_DATE`
(2026-05-26 낙찰하한율 2%p 일괄 인상 시행일)를 안내합니다. 구간 인자를
생략하면 전체 이력이 되므로 `--start-at` 없이 `--write` 를 쓰는 것은
거부합니다. 레짐 전환 이전 구간이 섞인 baseline 실수 생성을 막기 위함입니다.

사용 예::

    # 기록 없이 확인만 (dry-run)
    uv run python scripts/generate_drift_baseline.py \\
        --category Servc --start-at 2026-05-26 --baseline-version b_20260906_servc_post_regime
    # 실제 기록 (코디네이터 검토 후 직접 수행)
    uv run python scripts/generate_drift_baseline.py \\
        --category Servc --start-at 2026-05-26 --baseline-version b_20260906_servc_post_regime --write
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.db import SessionLocal  # noqa: E402
from src.ml.dataset import build_training_dataset  # noqa: E402
from src.ml.features import (  # noqa: E402
    REGIME_SHIFT_DATE,
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.monitoring import DEFAULT_MIN_SAMPLES, save_baseline_distributions  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import ModelTrainer  # noqa: E402
from src.ml.training_config import (  # noqa: E402
    model_name_for_category,
    training_features_for_category,
)

DEFAULT_REGISTRY_DIR = "ml_registry"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """명령행 인자를 해석합니다."""
    parser = argparse.ArgumentParser(
        description="학습 없이 지정 구간으로 drift baseline 을 생성합니다. 기본은 dry-run 입니다.",
        epilog=(
            "--baseline-version 은 학습 버전이 아니라 baseline 식별자입니다. "
            f"--start-at 참고 기준: REGIME_SHIFT_DATE={REGIME_SHIFT_DATE.date()} "
            "(src/ml/features.py, 2026-05-26 낙찰하한율 2%p 일괄 인상 시행일)."
        ),
    )
    parser.add_argument("--category", required=True, help="카테고리 코드 (예: Servc)")
    parser.add_argument(
        "--start-at",
        default=None,
        help="구간 시작 (BidResult.rl_openg_dt 이상, 예: 2026-05-26). 없으면 전체 이력.",
    )
    parser.add_argument(
        "--end-at",
        default=None,
        help="구간 종료 (BidResult.rl_openg_dt 미만, 예: 2026-09-06). 없으면 최신까지.",
    )
    parser.add_argument(
        "--baseline-version",
        required=True,
        help="baseline 식별자 (필수). 학습 버전과 다른 값이며 호출자가 명시합니다.",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="미지정 시 category 매핑(model_name_for_category)으로 결정됩니다.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="명시할 때만 실제 기록합니다. 기본(dry-run)은 어떤 파일도 쓰지 않습니다.",
    )
    parser.add_argument(
        "--registry-dir",
        default=DEFAULT_REGISTRY_DIR,
        help=f"레지스트리 루트 (기본: {DEFAULT_REGISTRY_DIR})",
    )
    return parser.parse_args(argv)


def resolve_model_name(category: str, model_name: str | None) -> str:
    """모델명을 확정합니다. 미지정 시 category 매핑을 사용합니다."""
    if model_name and model_name.strip():
        return model_name.strip()
    return model_name_for_category(category)


def build_feature_frame_for_baseline(df_raw, category_code: str):
    """원시 학습 프레임에서 baseline용 특징 프레임을 만듭니다.

    학습 경로(`ModelTrainer.train_and_register`)와 같은 순서로 기관 이력과
    재발주 이력을 붙인 뒤 단일 공급원 `build_feature_frame` 으로 특징을
    산출하고 저장된 범주 수준으로 dtype 을 복원합니다.
    """
    df_aug = attach_institution_history(df_raw)
    df_aug = attach_repeat_history(df_aug)
    records = df_aug.to_dict(orient="records")
    features_list = build_feature_frame(records)
    import pandas as pd

    df_feat = pd.DataFrame(features_list)
    category_levels = collect_category_levels(df_feat)
    df_feat = apply_categorical_dtypes(df_feat, category_levels)
    feature_columns = training_features_for_category(category_code)
    return df_feat, feature_columns


def check_min_samples(df_feat, feature_columns: list[str]) -> str | None:
    """최소 표본 기준 미달 시 사유 문자열을 돌려줍니다. 충족 시 None.

    전체 표본과 `lwlt_rate_missing` 하위 집단(있을 때) 각각에 집단별 최소
    표본을 적용합니다. 부족한 baseline 을 쓰면 감시가 조용히 무력화되므로
    fail-closed 로 기록을 거부합니다.
    """
    total = len(df_feat)
    if total < DEFAULT_MIN_SAMPLES:
        return f"전체 표본 부족 ({total} < {DEFAULT_MIN_SAMPLES})"
    if "lwlt_rate_missing" in df_feat.columns and "lwlt_rate_missing" in feature_columns:
        import pandas as pd

        missing_series = pd.to_numeric(df_feat["lwlt_rate_missing"], errors="coerce").fillna(0.0)
        for key, label in (("0.0", "with_lwlt"), ("1.0", "missing_lwlt")):
            target = 0.0 if key == "0.0" else 1.0
            count = int((missing_series == target).sum())
            if count < DEFAULT_MIN_SAMPLES:
                return (
                    f"{label} 집단 표본 부족 ({count} < {DEFAULT_MIN_SAMPLES}). "
                    "특징 목록에 lwlt_rate_missing 이 있어 집단별 기준을 적용합니다."
                )
    return None


def publish_baseline_atomically(
    staging_dir: Path | str, model_name: str, registry_dir: Path | str
) -> None:
    """스테이징 baseline 을 `ml_registry/{model_name}/baseline/` 에 원자 반영합니다.

    `ModelTrainer._update_baseline_atomically` 를 재사용하므로 학습 경로와
    같은 원자성 보장(임시 디렉터리와 백업을 거친 교체, 중간 실패 시 기존
    baseline 복원)을 얻습니다.
    """
    trainer = ModelTrainer(model_name=model_name, registry_dir=str(registry_dir))
    trainer._update_baseline_atomically(Path(staging_dir))


def main(argv: Sequence[str] | None = None) -> int:
    """진입점. 성공 시 0, 표본 부족·빈 구간 시 1, 사용법 오류 시 2를 돌려줍니다."""
    args = parse_args(argv)

    if args.write and not args.start_at:
        print(
            "거부: --start-at 없이 --write 를 사용할 수 없습니다. "
            "구간 인자를 생략하면 전체 이력이 되어 레짐 전환 이전 구간이 섞인 "
            "baseline 이 만들어질 수 있습니다.",
            file=sys.stderr,
        )
        return 2

    model_name = resolve_model_name(args.category, args.model_name)
    registry_dir = Path(args.registry_dir)
    target_baseline = registry_dir / model_name / "baseline"

    session = SessionLocal()
    try:
        df_raw = build_training_dataset(
            session,
            args.category,
            start_at=args.start_at,
            end_at=args.end_at,
            persist=False,
        )
    finally:
        session.close()

    if df_raw.empty:
        print(
            f"대상 구간: start_at={args.start_at} end_at={args.end_at} "
            f"(BidResult.rl_openg_dt 기준 [start_at, end_at)). 조회 0건으로 "
            "baseline 을 만들지 않습니다.",
        )
        return 1

    df_feat, feature_columns = build_feature_frame_for_baseline(df_raw, args.category)

    start_label = args.start_at if args.start_at else "(전체 이력)"
    end_label = args.end_at if args.end_at else "(최신까지)"
    print(f"대상 구간: start_at={start_label} end_at={end_label}")
    print(f"조회 행 수: 원시 {len(df_raw)}건 -> 특징 {len(df_feat)}건")
    print(f"특징 수: {len(feature_columns)}")
    print(f"저장될 경로: {target_baseline}/")

    if not args.write:
        print("모드: dry-run (파일을 쓰지 않았습니다. 실제 기록은 --write 필요).")
        return 0

    shortage = check_min_samples(df_feat, list(feature_columns))
    if shortage:
        print(f"거부: {shortage} 기록하지 않고 끝냅니다 (fail-closed).", file=sys.stderr)
        return 1

    staging = Path(tempfile.mkdtemp(prefix="drift_baseline_staging_"))
    try:
        save_baseline_distributions(
            df_feat=df_feat,
            feature_columns=list(feature_columns),
            target_dir=staging,
            model_name=model_name,
            model_version=args.baseline_version,
        )
        publish_baseline_atomically(staging, model_name, registry_dir)
    except Exception as exc:
        print(
            f"실패: baseline 기록 중 오류가 발생해 기존 baseline 을 유지합니다: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(f"기록 완료: {target_baseline}/ (baseline 식별자: {args.baseline_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
