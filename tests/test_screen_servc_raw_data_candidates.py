"""3단계 선별 판정 로직 검증.

판정이 잘못되면 쓸 수 없는 키를 4단계로 넘겨 재학습 비용을 헛되이 씁니다.
특히 **추론 시점 결측**은 학습 구간만 보면 안 잡히므로 따로 확인합니다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.screen_servc_raw_data_candidates import CANDIDATES, screen, verdict


def _row(**overrides) -> pd.Series:
    base = {"개찰 결측": 0.0, "미개찰 채움": 1.0, "고유값": 5, "연도 폭": 0.0}
    base.update(overrides)
    return pd.Series(base)


def test_학습_구간_결측이_임계값을_넘으면_제외한다():
    assert verdict(_row(개찰_결측=0.0)) == "통과"
    assert verdict(_row(**{"개찰 결측": 0.40})) == "제외: 학습 구간 결측"
    assert verdict(_row(**{"개찰 결측": 0.39})) == "통과"


def test_학습_구간이_멀쩡해도_추론_시점_결측이면_제외한다():
    """낙찰하한율 사례입니다. 개찰 완료 건만 보면 통과처럼 보입니다."""
    row = _row(**{"개찰 결측": 0.0, "미개찰 채움": 0.372})
    assert verdict(row) == "제외: 추론 시점 결측"


def test_연도별_채움률이_흔들리면_제외한다():
    assert verdict(_row(**{"연도 폭": 0.31})) == "제외: 연도 불안정"


def test_상수와_고유값_과다를_구분한다():
    assert verdict(_row(고유값=1)) == "제외: 상수"
    # 고유값이 많은 것은 탈락이 아니라 파생 설계 과제입니다.
    assert verdict(_row(고유값=301)) == "파생 필요: 고유값 과다"


def test_미개찰_표본이_없으면_판정을_보류한다():
    """없는 것을 있다고 단정하지 않습니다."""
    assert verdict(_row(**{"미개찰 채움": pd.NA})) == "보류: 미개찰 표본 없음"


def test_screen_은_후보_전량을_판정한다():
    aliases = [alias for alias, _ in CANDIDATES.values()]
    df = pd.DataFrame({"year": [2024, 2025], **{alias: ["a", "b"] for alias in aliases}})
    unopened = pd.Series(dict.fromkeys(aliases, 1.0))

    result = screen(df, unopened)

    assert len(result) == len(CANDIDATES)
    assert set(result["키"]) == set(CANDIDATES)
    assert result["판정"].eq("통과").all()


def test_이미_학습에_쓰는_키는_후보에_없다():
    """수집기가 정규 컬럼으로 옮겨 담는 키를 후보로 올렸던 실수를 막습니다."""
    from src.ml.features import CATEGORICAL_FEATURES

    aliases = {alias for alias, _ in CANDIDATES.values()}
    assert aliases.isdisjoint(CATEGORICAL_FEATURES)


@pytest.mark.parametrize("key", ["ntceKindNm", "bidMethdNm"])
def test_정규_컬럼_경유_키는_사용중으로_집계된다(key):
    from scripts.audit_servc_raw_data_keys import COLUMN_MAPPED

    assert key in COLUMN_MAPPED
