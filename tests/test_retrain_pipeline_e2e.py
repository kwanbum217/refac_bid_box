"""
tests/test_retrain_pipeline_e2e.py

재학습 파이프라인 배선 검증.

E2E 실기동에서 드러난 결함을 고정합니다. 모델 성능이 아니라 **배선**을 봅니다.
모델·특징·승격 임계값 선택은 담당자 영역이므로 여기서 값을 단정하지 않습니다.

고정하는 것:
1. 데이터셋 빌더가 실제 스키마 컬럼을 쓴다 (이전에는 존재하지 않는 이름을 참조)
2. 차수 자리수 차이를 흡수한다 (`00` vs `000`, 정규화 없으면 조인 0건)
3. 평가가 정답을 정답과 비교하지 않는다 (이전에는 rmse 0 / r2 1 고정)
4. champion 을 학습 전에 읽는다 (학습 후면 자기 자신과 비교)
5. 재학습 이력이 retrain_logs 에 남는다
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.predictions import RetrainLog
from src.ml.dataset import (
    MAX_PRESMPT_PRCE,
    MAX_WINNING_RATE,
    MIN_PRESMPT_PRCE,
    MIN_WINNING_RATE,
    TRAINING_COLUMNS,
    build_training_dataset,
)
from src.ml.trainer import TRAINING_FEATURES, ModelTrainer
from src.ml.validate_model import compare_champion_vs_challenger, evaluate_model_performance


def _seed(db, *, count: int = 60, category: str = "Servc", with_announcement: bool = True):
    """낙찰 결과와 공고를 짝지어 넣습니다. 차수 자리수를 일부러 다르게 둡니다."""
    base = datetime(2024, 1, 1, 9, 0, 0)
    for index in range(count):
        notice_no = f"S{index:06d}"
        db.add(
            BidResult(
                bid_ntce_no=notice_no,
                # 낙찰 테이블은 2자리입니다.
                bid_ntce_ord="00",
                category=category,
                bid_ntce_nm=f"용역 {index}",
                bidwinnr_nm=f"업체{index % 7}",
                dminstt_nm=f"기관{index % 5}",
                sucsf_bid_amt=100_000_000 + index * 1_000,
                sucsf_bid_rate=85.0 + (index % 10),
                rl_openg_dt=base + timedelta(days=index),
                collected_at=base,
            )
        )
        if with_announcement:
            db.add(
                BidAnnouncement(
                    bid_ntce_no=notice_no,
                    # 공고 테이블은 3자리입니다.
                    bid_ntce_ord="000",
                    category=category,
                    bid_ntce_nm=f"용역 {index}",
                    ntce_instt_nm=f"발주기관{index % 3}",
                    dminstt_nm=f"기관{index % 5}",
                    presmpt_prce=110_000_000 + index * 1_000,
                    base_amount=105_000_000 + index * 1_000,
                    bid_ntce_dt=base + timedelta(days=index - 14),
                    bid_clse_dt=base + timedelta(days=index - 1),
                    collected_at=base,
                )
            )
    db.commit()


# --------------------------------------------------------------------------- #
# 데이터셋 빌더
# --------------------------------------------------------------------------- #


def test_builder_uses_real_schema_columns(isolated_db, tmp_path):
    """이전 구현은 bid_notice_no 등 존재하지 않는 컬럼을 참조해 즉시 실패했습니다."""
    _seed(isolated_db)
    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert not df.empty
    assert list(df.columns) == list(TRAINING_COLUMNS)


def test_builder_normalizes_notice_order_width(isolated_db, tmp_path):
    """차수 자리수를 맞추지 않으면 조인 결과가 0건이 됩니다."""
    _seed(isolated_db, count=10)
    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert len(df) == 10
    # 공고 쪽 컬럼이 실제로 붙었는지 확인합니다.
    assert df["presmpt_prce"].notna().all()
    assert df["ntce_instt_nm"].notna().all()


def test_builder_without_announcement_keeps_result_rows(isolated_db, tmp_path):
    """공고 수집률이 낮은 용역/건설에서 표본을 확보하는 경로입니다."""
    _seed(isolated_db, count=10, with_announcement=False)

    joined = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert joined.empty

    standalone = build_training_dataset(
        isolated_db,
        category_code="Servc",
        output_dir=str(tmp_path),
        require_announcement=False,
    )
    assert len(standalone) == 10


def test_builder_filters_out_of_range_rates(isolated_db, tmp_path):
    _seed(isolated_db, count=5)
    isolated_db.add(
        BidResult(
            bid_ntce_no="OUTLIER",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=1,
            sucsf_bid_rate=MAX_WINNING_RATE + 50,
            rl_openg_dt=datetime(2024, 6, 1),
            collected_at=datetime(2024, 6, 1),
        )
    )
    isolated_db.commit()

    df = build_training_dataset(
        isolated_db,
        category_code="Servc",
        output_dir=str(tmp_path),
        require_announcement=False,
    )
    assert df["winning_rate"].between(MIN_WINNING_RATE, MAX_WINNING_RATE).all()


def test_builder_returns_empty_frame_when_no_data(isolated_db, tmp_path):
    """예전 구현은 데이터가 없으면 더미 1행을 만들어 학습이 성공한 것처럼 보였습니다."""
    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert df.empty


def test_builder_filters_presmpt_prce_outliers(isolated_db, tmp_path):
    """추정가격 이상값이 비율 특징의 평균을 통째로 망가뜨립니다 (실측 0.99%)."""
    _seed(isolated_db, count=5)
    for suffix, price in (("LOW", MIN_PRESMPT_PRCE - 1), ("HIGH", MAX_PRESMPT_PRCE + 1)):
        isolated_db.add(
            BidResult(
                bid_ntce_no=f"OUT{suffix}",
                bid_ntce_ord="00",
                category="Servc",
                sucsf_bid_amt=100,
                sucsf_bid_rate=90.0,
                rl_openg_dt=datetime(2024, 6, 1),
                collected_at=datetime(2024, 6, 1),
            )
        )
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=f"OUT{suffix}",
                bid_ntce_ord="000",
                category="Servc",
                presmpt_prce=price,
                bid_ntce_dt=datetime(2024, 5, 1),
                collected_at=datetime(2024, 6, 1),
            )
        )
    isolated_db.commit()

    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert len(df) == 5
    assert df["presmpt_prce"].between(MIN_PRESMPT_PRCE, MAX_PRESMPT_PRCE).all()


def test_builder_extracts_institution_fields_from_raw_data(isolated_db, tmp_path):
    """낙찰하한율 등 제도 필드는 정식 컬럼이 아니라 raw_data JSON 안에만 있습니다."""
    base = datetime(2024, 1, 1, 9, 0, 0)
    isolated_db.add(
        BidResult(
            bid_ntce_no="INST01",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=100_000_000,
            sucsf_bid_rate=88.5,
            rl_openg_dt=base,
            collected_at=base,
        )
    )
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="INST01",
            bid_ntce_ord="000",
            category="Servc",
            presmpt_prce=110_000_000,
            bid_ntce_dt=base - timedelta(days=14),
            collected_at=base,
            raw_data={
                "sucsfbidLwltRate": "87.745",
                "srvceDivNm": "기술용역",
                "pubPrcrmntLrgClsfcNm": "기술용역",
                "prearngPrceDcsnMthdNm": "복수예가",
                "totPrdprcNum": "15",
                "drwtPrdprcNum": "4",
            },
        )
    )
    isolated_db.commit()

    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert len(df) == 1
    row = df.iloc[0]
    assert float(row["lwlt_rate"]) == pytest.approx(87.745)
    assert row["srvce_div_nm"] == "기술용역"
    assert row["prearng_mthd"] == "복수예가"
    assert float(row["tot_prdprc_num"]) == 15
    assert float(row["drwt_prdprc_num"]) == 4


def test_builder_treats_zero_lower_limit_as_missing(isolated_db, tmp_path):
    """하한율 0 은 값이 아니라 미기재입니다. 0 으로 두면 특징이 잘못 학습됩니다."""
    base = datetime(2024, 1, 1, 9, 0, 0)
    isolated_db.add(
        BidResult(
            bid_ntce_no="ZERO01",
            bid_ntce_ord="00",
            category="Servc",
            sucsf_bid_amt=100_000_000,
            sucsf_bid_rate=88.5,
            rl_openg_dt=base,
            collected_at=base,
        )
    )
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="ZERO01",
            bid_ntce_ord="000",
            category="Servc",
            presmpt_prce=110_000_000,
            bid_ntce_dt=base - timedelta(days=14),
            collected_at=base,
            raw_data={"sucsfbidLwltRate": "0"},
        )
    )
    isolated_db.commit()

    df = build_training_dataset(isolated_db, category_code="Servc", output_dir=str(tmp_path))
    assert df["lwlt_rate"].isna().all()


# --------------------------------------------------------------------------- #
# 학습기 평가
# --------------------------------------------------------------------------- #


def _frame(rows: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "presmpt_prce": [100_000_000 + i * 1_000 for i in range(rows)],
            "base_amount": [95_000_000 + i * 1_000 for i in range(rows)],
            "category": ["Servc"] * rows,
            "winning_rate": [85.0 + (i % 10) for i in range(rows)],
        }
    )


def test_trainer_reports_holdout_metrics(tmp_path):
    """정답을 정답과 비교하면 rmse 0 / r2 1 이 나와 승격 판단이 무의미해집니다."""
    metadata = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(_frame())

    assert metadata["metrics"]["rmse"] > 0.0
    assert metadata["metrics"]["r2"] < 1.0
    assert metadata["train_samples"] + metadata["validation_samples"] == 100
    assert metadata["validation_samples"] > 0


def test_trainer_records_feature_contract(tmp_path):
    metadata = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(_frame())
    assert metadata["features"] == list(TRAINING_FEATURES)


def test_servc_uses_validated_features_and_hyperparams():
    from src.ml.trainer import hyperparams_for_category, training_features_for_category

    assert training_features_for_category("Thng") == list(TRAINING_FEATURES)
    assert training_features_for_category("Servc") == [*TRAINING_FEATURES, "inst_ewm_rate"]
    assert hyperparams_for_category("Thng") == {}
    assert hyperparams_for_category("Servc")["lightgbm"]["num_leaves"] == 255


def test_category_model_namespaces_do_not_collide():
    """공사 재학습이 물품 네임스페이스로 떨어지면 물품 champion 을 덮어씁니다."""
    import pytest

    from src.ml.trainer import (
        DEFAULT_MODEL_NAME,
        ModelTrainer,
        model_name_for_category,
    )

    names = {code: model_name_for_category(code) for code in ("Thng", "Servc", "Cnstwk")}
    assert len(set(names.values())) == 3, f"네임스페이스가 겹칩니다: {names}"
    assert names["Cnstwk"] != DEFAULT_MODEL_NAME
    assert ModelTrainer.for_category("Cnstwk").model_name == names["Cnstwk"]

    # 카테고리가 None 이거나 빈값이면 명시적으로 거부되어야 합니다.
    with pytest.raises(ValueError):
        model_name_for_category(None)
    with pytest.raises(ValueError):
        model_name_for_category("  ")

    # 미등록 카테고리는 조용히 물품으로 떨어지지 않고 실패해야 합니다.
    with pytest.raises(ValueError, match="Frgcpt"):
        model_name_for_category("Frgcpt")


def test_trainer_writes_versioned_artifacts(tmp_path):
    trainer = ModelTrainer(registry_dir=str(tmp_path))
    metadata = trainer.train_and_register(_frame())
    version_dir = tmp_path / trainer.model_name / metadata["version"]
    assert (version_dir / "model.bin").exists()
    assert (version_dir / "metadata.json").exists()


def test_trainer_handles_tiny_dataset(tmp_path):
    """홀드아웃이 비는 크기에서도 죽지 않아야 정기 실행이 멈추지 않습니다."""
    metadata = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(_frame(rows=2))
    assert metadata["validation_samples"] > 0


# --------------------------------------------------------------------------- #
# 승격 판정과 이력
# --------------------------------------------------------------------------- #


def test_evaluation_penalizes_wrong_predictions():
    perfect = evaluate_model_performance(
        pd.Series([90.0, 91.0, 92.0]).values, pd.Series([90.0, 91.0, 92.0]).values
    )
    wrong = evaluate_model_performance(
        pd.Series([90.0, 91.0, 92.0]).values, pd.Series([80.0, 81.0, 82.0]).values
    )
    assert perfect["rmse"] == 0.0
    assert wrong["rmse"] > perfect["rmse"]


def test_gate_rejects_worse_challenger():
    verdict = compare_champion_vs_challenger(
        {"rmse": 1.0, "mape": 1.0, "r2": 0.9},
        {"rmse": 2.0, "mape": 2.0, "r2": 0.5},
    )
    assert verdict["recommendation"] == "REJECT_CHALLENGER"


@pytest.mark.asyncio
async def test_pipeline_skips_and_logs_when_no_data(isolated_db, monkeypatch, tmp_path):
    """데이터가 없을 때 학습을 성공으로 보고하면 안 됩니다."""
    from src.tasks import retrain_task

    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: isolated_db)
    isolated_db.close = lambda: None

    outcome = await retrain_task.run_retrain_pipeline_task(
        {}, category_code="Servc", output_dir=str(tmp_path)
    )

    assert outcome["status"] == "skipped"
    log = isolated_db.query(RetrainLog).one()
    assert log.status == "skipped"


@pytest.mark.asyncio
async def test_pipeline_records_history(isolated_db, monkeypatch, tmp_path):
    from src.ml.trainer import ModelTrainer as _Trainer
    from src.tasks import retrain_task

    _seed(isolated_db, count=80, with_announcement=False)
    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(retrain_task, "trainer", _Trainer(registry_dir=str(tmp_path)))
    isolated_db.close = lambda: None

    outcome = await retrain_task.run_retrain_pipeline_task(
        {},
        trigger_source="unit",
        category_code="Servc",
        require_announcement=False,
        output_dir=str(tmp_path),
    )

    assert outcome["status"] == "success"
    assert outcome["samples"] == 80

    log = isolated_db.query(RetrainLog).one()
    assert log.trigger_source == "unit"
    assert log.challenger_version == outcome["version"]
    assert log.metrics_summary["challenger_metrics"]["rmse"] > 0.0


@pytest.mark.asyncio
async def test_pipeline_does_not_write_default_feature_store(isolated_db, monkeypatch, tmp_path):
    """테스트가 운영 feature store 의 parquet 을 픽스처로 덮어쓴 적이 있습니다.

    2026-08-03 에 실제로 발생했습니다. 91만행짜리 dataset_Servc.parquet 이
    테스트 픽스처 80행으로 교체되어 실험이 조용히 잘못된 데이터로 돌았습니다.
    """
    from src.ml import dataset as dataset_module
    from src.tasks import retrain_task

    captured: list[str] = []
    original = dataset_module.build_training_dataset

    def _spy(db_session, *args, **kwargs):
        captured.append(kwargs.get("output_dir", dataset_module.DEFAULT_OUTPUT_DIR))
        return original(db_session, *args, **kwargs)

    monkeypatch.setattr(retrain_task, "build_training_dataset", _spy)
    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: isolated_db)
    isolated_db.close = lambda: None

    await retrain_task.run_retrain_pipeline_task(
        {}, category_code="Servc", output_dir=str(tmp_path)
    )

    assert captured == [str(tmp_path)]
    assert dataset_module.DEFAULT_OUTPUT_DIR not in captured


@pytest.mark.asyncio
async def test_champion_is_read_before_training(isolated_db, monkeypatch, tmp_path):
    """챌린저가 자기 자신과 비교되면 안 됩니다.

    2026-08-06 이후 champion 은 서빙 슬롯에서 읽습니다. 학습이 서빙 슬롯을
    건드리지 않으므로 자기 자신과 비교되는 사고는 구조적으로 막히지만,
    비교 대상이 서빙본이라는 계약 자체를 여기서 고정합니다.
    """
    import json

    from src.ml.trainer import ModelTrainer as _Trainer
    from src.tasks import retrain_task

    serving = tmp_path / "serving" / "servc_institution_v1"
    serving.mkdir(parents=True)
    (serving / "metadata.json").write_text(
        json.dumps(
            {"version": "v_serving", "source_metrics": {"rmse": 2.7, "mape": 1.5, "r2": 0.68}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.ml.promotion.SERVING_ROOT", tmp_path / "serving")

    _seed(isolated_db, count=80, with_announcement=False)
    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(retrain_task, "trainer", _Trainer(registry_dir=str(tmp_path)))
    isolated_db.close = lambda: None

    first = await retrain_task.run_retrain_pipeline_task(
        {}, category_code="Servc", require_announcement=False, output_dir=str(tmp_path)
    )
    second = await retrain_task.run_retrain_pipeline_task(
        {}, category_code="Servc", require_announcement=False, output_dir=str(tmp_path)
    )

    for result in (first, second):
        assert result["champion_version"] == "v_serving"
        assert result["champion_version"] != result["version"]


def test_versions_do_not_collide_within_a_second(tmp_path):
    """초 단위 버전명은 같은 초에 두 번 학습하면 이전 아티팩트를 덮어씁니다."""
    trainer = ModelTrainer(registry_dir=str(tmp_path))
    versions = {trainer.train_and_register(_frame(rows=20))["version"] for _ in range(5)}
    assert len(versions) == 5
