"""
tests/test_retrain_parquet_freshness.py

scripts/retrain_servc_from_parquet.py 의 parquet 신선도 가드 검증.
실제 모델 학습이나 feature store 원본 변경 없이 가드 구간만 검사합니다.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import pytest

from scripts.retrain_servc_from_parquet import (
    check_parquet_freshness,
    main,
    parse_args,
)


@pytest.fixture
def dummy_parquet_file(tmp_path: Path) -> Path:
    """임시 디렉터리에 소량 가짜 parquet 파일을 생성합니다."""
    file_path = tmp_path / "dummy_dataset.parquet"
    df = pd.DataFrame({"feat_1": [1.0, 2.0], "target": [100.0, 101.0]})
    df.to_parquet(file_path)
    return file_path


def test_fresh_parquet_passes(dummy_parquet_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """신선한 parquet 파일은 가드를 정상 통과합니다."""
    now = time.time()
    os.utime(dummy_parquet_file, (now, now))

    ok, msg = check_parquet_freshness(dummy_parquet_file, max_age_days=14, allow_stale=False)
    assert ok is True
    assert "신선한 parquet 파일입니다" in msg

    # main 호출 시 신선도 가드를 통과하여 다음 단계(min-rows 검사)에 도달함을 확인
    exit_code = main(["--parquet", str(dummy_parquet_file)])
    captured = capsys.readouterr().out
    assert "오래된 parquet 파일입니다" not in captured
    assert "행 수가 100,000 미만입니다" in captured
    assert exit_code == 1


def test_stale_parquet_blocked_before_training(
    dummy_parquet_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """오래된 parquet 파일은 학습 시작 전 종료 코드 1로 차단됩니다."""
    stale_time = time.time() - (30 * 86400)
    os.utime(dummy_parquet_file, (stale_time, stale_time))

    ok, msg = check_parquet_freshness(dummy_parquet_file, max_age_days=14, allow_stale=False)
    assert ok is False
    assert "오래된 parquet 파일입니다" in msg
    assert "build_training_dataset" in msg
    assert str(dummy_parquet_file) in msg

    # main 호출 시 min-rows 단계로 진입하지 않고 신선도 가드에서 즉시 종료 코드 1 반환
    exit_code = main(["--parquet", str(dummy_parquet_file)])
    captured = capsys.readouterr().out
    assert exit_code == 1
    assert "[오류] 오래된 parquet 파일입니다" in captured
    assert "build_training_dataset" in captured
    assert "행 수가 100,000 미만입니다" not in captured


def test_stale_parquet_proceeds_with_allow_stale(
    dummy_parquet_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--allow-stale-parquet 플래그 지정 시 경고 출력 후 계속 진행합니다."""
    stale_time = time.time() - (30 * 86400)
    os.utime(dummy_parquet_file, (stale_time, stale_time))

    ok, msg = check_parquet_freshness(dummy_parquet_file, max_age_days=14, allow_stale=True)
    assert ok is True
    assert "[경고]" in msg
    assert "오래된 parquet 파일입니다" in msg
    assert "--allow-stale-parquet" in msg

    # main 호출 시 경고 출력 후 다음 단계(min-rows 검사)로 진행함을 확인
    exit_code = main(["--parquet", str(dummy_parquet_file), "--allow-stale-parquet"])
    captured = capsys.readouterr().out
    assert "[경고] 오래된 parquet 파일입니다" in captured
    assert "행 수가 100,000 미만입니다" in captured
    assert exit_code == 1


def test_invalid_max_age_days_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """--max-parquet-age-days 에 0 이하 값을 넘기면 인자 오류로 거부됩니다."""
    for invalid_val in ["0", "-1", "-10"]:
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--max-parquet-age-days", invalid_val])
        assert exc_info.value.code == 2

        err = capsys.readouterr().err
        assert "--max-parquet-age-days 는 1 이상의 정수여야 합니다" in err
