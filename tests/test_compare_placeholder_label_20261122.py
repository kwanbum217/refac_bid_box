"""비교 분석 '기관별 기초금액 TOP 10' 자리표시 기관명 표시 회귀 테스트.

2026-11-22 사용자 결정(B안)으로 '각 수요기관'·'수요기관' 은 순위에서 빼지 않고
'여러 수요기관' 이라는 이름으로만 바꿔 표시합니다. 막대 값과 순위는 그대로이고,
툴팁과 차트 아래 설명 줄이 조달청 단가계약 공고임을 알려 줍니다.

브라우저 렌더링은 확인하지 않고 템플릿 문자열만 검사합니다.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src/app/templates/bids/compare.html"
TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")


def test_자리표시_기관명_상수와_표시_문구가_있다():
    """(a-1) 자리표시 집합·라벨·툴팁 문구가 템플릿 스크립트 상수로 있다."""
    assert (
        "const COMPARE_PLACEHOLDER_AGENCY_NAMES = new Set(['각 수요기관', '수요기관']);" in TEMPLATE
    )
    assert "const COMPARE_PLACEHOLDER_AGENCY_LABEL = '여러 수요기관';" in TEMPLATE
    assert (
        "const COMPARE_PLACEHOLDER_AGENCY_TOOLTIP = "
        "'여러 수요기관(조달청 단가계약): 여러 기관이 함께 쓰는 조달청 단가계약 공고';" in TEMPLATE
    )


def test_막대_라벨은_자리표시만_매핑하고_나머지는_기존_자르기를_유지한다():
    """(a-2) 자리표시는 '여러 수요기관', 다른 기관은 기존 8자 자르기를 쓴다."""
    assert "function isPlaceholderAgency(name)" in TEMPLATE
    assert "COMPARE_PLACEHOLDER_AGENCY_NAMES.has(String(name ?? '').trim())" in TEMPLATE
    assert "function agencyChartLabel(name)" in TEMPLATE
    assert "return COMPARE_PLACEHOLDER_AGENCY_LABEL;" in TEMPLATE
    assert "return text.length > 8 ? text.slice(0, 8) + '..' : text;" in TEMPLATE
    assert "labels: agencyTop10.map(d => agencyChartLabel(d.name))," in TEMPLATE


def test_막대_값과_순서는_바꾸지_않는다():
    """(a-3) 데이터 배열·정렬·값 계산은 그대로다."""
    assert "data: agencyTop10.map(d => d.total_base_amount ?? d.total_prce ?? 0)," in TEMPLATE
    assert "data.agency_announce_top10 || []" in TEMPLATE
    assert "agencyTop10.sort(" not in TEMPLATE
    assert "agencyTop10.reverse(" not in TEMPLATE
    assert "agencyTop10.slice(" not in TEMPLATE


def test_자리표시_막대_툴팁은_단가계약_설명을_보인다():
    """(a-4) 툴팁 제목 콜백이 자리표시일 때만 긴 설명 문구를 쓴다."""
    assert "title: ctx => isPlaceholderAgency(agencyTop10[ctx[0].dataIndex]?.name)" in TEMPLATE
    assert "? COMPARE_PLACEHOLDER_AGENCY_TOOLTIP" in TEMPLATE
    assert "label: ctx => ' ' + formatWon(ctx.raw)" in TEMPLATE


def test_자리표시가_없으면_설명_줄을_숨긴다():
    """(b) 설명 줄은 기본 숨김이고 자리표시가 목록에 있을 때만 보인다."""
    assert 'id="agencyPlaceholderNote"' in TEMPLATE
    assert (
        'class="hidden mt-3 text-[11px] font-medium text-slate-400">'
        "여러 수요기관은 조달청 단가계약 공고입니다</p>" in TEMPLATE
    )
    assert (
        "const hasPlaceholderAgency = agencyTop10.some(d => isPlaceholderAgency(d.name));"
        in TEMPLATE
    )
    assert (
        "document.getElementById('agencyPlaceholderNote')"
        ".classList.toggle('hidden', !hasPlaceholderAgency);" in TEMPLATE
    )


def test_csp_nonce_를_유지한다():
    """스크립트 인라인 정책을 깨지 않도록 nonce 속성을 유지한다."""
    assert 'nonce="{{ csp_nonce }}"' in TEMPLATE
