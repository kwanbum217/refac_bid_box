"""홈 컨텍스트 announcement_total 이 수집 행 수임을 스키마가 명시하는지 검증합니다."""

from __future__ import annotations

from src.app.schemas.bids import HomeContextResponse


def test_announcement_total_is_documented_as_collected_rows():
    field = HomeContextResponse.model_fields["announcement_total"]
    assert field.default == 0
    assert field.description is not None
    assert "수집 행 수" in field.description
    assert "서로 다른 공고 수가 아닙니다" in field.description


def test_openapi_exposes_announcement_total_description():
    schema = HomeContextResponse.model_json_schema()
    assert "수집 행 수" in schema["properties"]["announcement_total"]["description"]
