"""KB 검색 품질 측정 지표의 재현 계약을 검증합니다."""

from scripts.measure_kb_retrieval import _build_query, _percentile_ms


def test_build_query_uses_announcement_title_and_institution():
    document = "[공고명] 청사 경비 용역\n[수요기관] 서울특별시"

    assert _build_query(document) == "청사 경비 용역 서울특별시"


def test_percentile_uses_nearest_rank():
    elapsed_ms = [40.0, 10.0, 30.0, 20.0]

    assert _percentile_ms(elapsed_ms, 0.50) == 20.0
    assert _percentile_ms(elapsed_ms, 0.95) == 40.0
    assert _percentile_ms([], 0.95) == 0.0
