"""
src/rag/industry_terms.py

업종어(청소·경비 등) 사전과 공고명 키워드 SQL 조건을 담는 모듈.

업종어는 분야어(공사·물품·용역)와 다른 축입니다. 사용자가 "청소 용역" 처럼 업종을
지목해도 분야 사전만 보면 "용역" 만 남아 업종이 사라지므로, 라벨 -> 공고명 키워드
동의어 표를 여기에 둡니다. 이 표는 query_lexicon 의 분리 이전 상수 계약을 건드리지
않도록 새 모듈에 둡니다.

1단계에서는 조건 생성 함수만 두고 집계 계층(src/rag/structured_data.py)은 아직
호출하지 않습니다. 조건을 실제로 붙인 계층은 filters["industry_applied"] = True
로 표시해야 하며, 표시가 없으면 응답 단계가 "업종 조건은 적용하지 못했다"고
밝힙니다. 표시가 없는데 조건이 붙은 것처럼 답하면 용역 전체 수치가 업종 수치로
오해됩니다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, not_, or_

# 키워드 근거: .orca/stats_industry_report_20261122.md 4장(인천 용역 5년 표본).
# "미화" 35건은 "환경미화" 변형이고, "위생" 25건은 면허명 "위생관리용역업"과
# 같이 쓰입니다. "파견"·"직업소개" 는 4대 업종 명칭(파견근로자 파견업, 유료직업
# 소개업)에서 가져왔습니다.
INDUSTRY_TERM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "청소": ("청소", "미화", "환경미화"),
    "경비": ("경비", "보안경비"),
    "시설관리": ("시설관리",),
    "파견": ("파견",),
    "직업소개": ("직업소개",),
    "위생": ("위생", "위생관리"),
}
# 공고명에 업종 키워드가 들어 있어도 업종 용역이 아닌 잡음입니다. 같은 표본에서
# "청소차" 6건, "청소기"·"청소용품" 0건이었고, "경비실" 은 시설 관리 공고에
# 붙습니다. 잡음 낱말은 공고명 조건에서 NOT 으로 걷어냅니다.
INDUSTRY_TITLE_NOISE_TERMS: dict[str, tuple[str, ...]] = {
    "청소": ("청소기", "청소용품", "청소차"),
    "경비": ("경비실",),
}
# 질문 인식에서 기관명 일부를 업종어로 오인하지 않도록 뒤에 붙는 이름 꼬리를
# 봅니다. "시설관리공단"·"시설관리공사" 는 업종 지목이 아니라 기관명입니다.
# ("인천공항시설관리" 처럼 앞에 이름이 붙은 형태는 어절 시작 규칙이 걷어냅니다.)
INDUSTRY_QUESTION_NOISE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "시설관리": ("공단", "재단", "공사"),
}


def title_keyword_condition(column: Any, filters: dict[str, Any] | None) -> Any:
    """공고명에 업종 키워드가 든 행만 남기는 조건을 만듭니다.

    filters["title_keywords"] 의 낱말은 OR 로 묶고, 같은 라벨의 잡음 낱말
    ("청소차", "경비실")은 NOT 으로 걷어냅니다. 키워드가 없으면 None 을 돌려주어
    호출한 쪽이 조건을 붙이지 않게 합니다(업종어 없는 질의는 용역 전체 유지).

    LIKE 와일드카드(%·_)는 autoescape 로 이스케이프합니다. 질문에서 온 낱말이
    검색 패턴이 되어 범위를 넓히지 못하게 하기 위함입니다.
    """
    current = filters or {}
    keywords = [str(keyword) for keyword in current.get("title_keywords") or [] if str(keyword)]
    if column is None or not keywords:
        return None
    label = str(current.get("industry_label") or "")
    noise_terms = INDUSTRY_TITLE_NOISE_TERMS.get(label, ())
    condition = or_(*[column.contains(keyword, autoescape=True) for keyword in keywords])
    if noise_terms:
        condition = and_(
            condition,
            not_(or_(*[column.contains(term, autoescape=True) for term in noise_terms])),
        )
    return condition
