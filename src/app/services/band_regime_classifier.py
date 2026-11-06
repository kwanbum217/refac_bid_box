"""
src/app/services/band_regime_classifier.py

낙찰방법명이 `2억미만 1억이상` 인 용역 공고의 첨부 원문에서 적용 기준 갈래를
판별하는 순수 함수.

설계 정본: `.orca/ref/band_2to1_attachment_classifier_design_20261106.md`
- 2.1절 정규식 표 R1~R13 을 그대로 옮기고, 제안 1 의 세부표 직접 표지를 R14 로
  더했습니다.
- 1단은 결정 문장(`낙찰자 결정`·`적격심사`·`적용`) 안의 문서명 패턴만 봅니다.
  `숙지`·`참고`·서류 목록 문장의 매치는 버립니다(2.2절 오탐 사례).
- 2단은 행안부 제2장의2 로 판정된 경우에만 세부표를 가릅니다. 낙찰하한율
  `87.745` 는 `MOIS_OTHER` 확정 신호이고, `별표 4` 직접 표지(R14)와
  `학술연구용역 평가기준`(R4)만 `MOIS_ACADEMIC` 을 확정합니다. 장 이름(R1·R3)만
  있으면 `UNSPECIFIED_SUBTABLE` 로 남깁니다. LOCAL 은 `87.745` 신호보다 먼저
  확정합니다(7.1절).
- 참고·숙지·참조 문장의 매치는 버리고(제안 2), 텍스트 추출 실패는
  `EXTRACT_FAIL` 로 `UNSPECIFIED` 와 분리합니다(제안 4).

이 모듈은 파일·네트워크·DB 에 접근하지 않습니다. 수집기·규칙 해석기와 연결하지
않으며, 판별 결과 저장은 `bid_announcement_regime` 테이블이 맡습니다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

MOIS_ACADEMIC = "MOIS_ACADEMIC"
MOIS_OTHER = "MOIS_OTHER"
PPS = "PPS"
LOCAL = "LOCAL"
MOIS4 = "MOIS4"
UNSPECIFIED = "UNSPECIFIED"
UNSPECIFIED_SUBTABLE = "UNSPECIFIED_SUBTABLE"
EXTRACT_FAIL = "EXTRACT_FAIL"
NO_ATTACH = "NO_ATTACH"

BAND_REGIME_CLASSIFIER_VERSION = "1.1.0"

_EVIDENCE_LIMIT = 80
_DECISION_WINDOW = 160
_NUMERIC_MOIS_OTHER = "87.745"


@dataclass(frozen=True)
class BandRegimeResult:
    """첨부 원문 판별 결과.

    `regime` 은 `MOIS_ACADEMIC`, `MOIS_OTHER`, `PPS`, `LOCAL`, `MOIS4`,
    `UNSPECIFIED`, `UNSPECIFIED_SUBTABLE`, `EXTRACT_FAIL`, `NO_ATTACH` 가운데
    하나입니다. `evidence` 는 근거 문장을 80자 이내로 자른 값이고,
    `matched_rules` 는 판정에 쓰인 규칙 ID 입니다.
    """

    regime: str
    evidence: str | None
    matched_rules: tuple[str, ...]


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    branch: str
    pattern: re.Pattern[str]


# 2.1절 표 R1~R13. R5 는 행안부 공통 신호라 MOIS_ACADEMIC 점수에 더하고,
# R13 은 띠 문구 자체라 갈래를 가르지 않습니다.
_REGION = (
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|"
    r"전북|전남|경북|경남|제주)"
)

_RULES: tuple[_Rule, ...] = (
    _Rule("R1", MOIS_ACADEMIC, re.compile(r"제\s*2\s*장\s*의\s*2")),
    _Rule("R2", MOIS_ACADEMIC, re.compile(r"별표\s*4\s*(?:의)?\s*[^.]{0,20}학술연구")),
    _Rule(
        "R3",
        MOIS_ACADEMIC,
        re.compile(r"학술(?:[·ㆍ.]?\s*연구)?\s*용역\s*적격심사\s*세부\s*기준"),
    ),
    _Rule("R4", MOIS_ACADEMIC, re.compile(r"학술연구용역\s*평가\s*기준")),
    _Rule("R5", MOIS_ACADEMIC, re.compile(r"지방자치단체\s*입찰시\s*낙찰자\s*결정\s*기준")),
    _Rule("R6", PPS, re.compile(r"조달청\s*일반용역\s*적격심사\s*세부기준")),
    _Rule("R7", PPS, re.compile(r"별표\s*1\s*[^.]{0,12}학술연구")),
    _Rule("R8", MOIS4, re.compile(r"제\s*4\s*장\s*물품")),
    _Rule("R9", MOIS4, re.compile(r"물품\s*적격심사\s*세부\s*기준")),
    _Rule(
        "R10",
        LOCAL,
        re.compile(
            rf"{_REGION}[가-힣]{{0,8}}\s*"
            r"(?:광역시|특별시|특별자치시|특별자치도|도|시|군|구)?\s*"
            r"일반\s*용역\s*등?\s*적격심사"
        ),
    ),
    _Rule("R11", LOCAL, re.compile(r"시\s*[·ㆍ.]\s*도\s*일반\s*용역\s*등?\s*적격심사")),
    _Rule(
        "R12",
        MOIS_OTHER,
        re.compile(
            r"기술\s*용역\s*적격심사|"
            r"추정가격\s*2\s*억\s*원?\s*미만인\s*일반\s*용역|"
            r"사업수행능력평가\s*\(?P\.?Q\)?[^.]{0,30}기술용역"
        ),
    ),
    _Rule(
        "R13",
        "BAND",
        re.compile(r"추정가격\s*2\s*억\s*원?\s*미만\s*1\s*억\s*원?\s*이상"),
    ),
    # 제안 1 의 세부표 직접 표지입니다. `[별표 4]`·`[별표4]`·`별표 4]` 처럼
    # 괄호 표기가 달라도 잡고, `별표 4의2`·`별표 42` 는 제외합니다. 가중치가
    # 0 이라 갈래 점수는 흔들지 않고 학술 세부표 확정 여부만 알립니다.
    _Rule("R14", MOIS_ACADEMIC, re.compile(r"별표\s*4(?!\s*의?\s*\d)")),
)

# 2.3절 패턴 가중치.
_WEIGHTS: dict[str, float] = {
    "R1": 2.0,
    "R2": 2.0,
    "R3": 2.0,
    "R4": 2.0,
    "R5": 0.2,
    "R6": 2.0,
    "R7": 2.0,
    "R8": 2.0,
    "R9": 1.5,
    "R10": 2.0,
    "R11": 1.5,
    "R12": 2.0,
    "R14": 0.0,
}

# 2.3절 동점 우선순위.
_TIE_ORDER: tuple[str, ...] = (MOIS4, PPS, LOCAL, MOIS_OTHER, MOIS_ACADEMIC)

# 2.3절 결정 창. 첨부 인용이 80자로 잘린 경우가 많아 `적격심사` 같은 결정
# 표지도 동사(`적용`·`따르` 등)와 함께 결정 문장 신호로 인정합니다.
_DECISION_CUE = re.compile(
    r"적용|따르|따라|의거|의하|의함|의하며|준용|평가합니다|평가하며|결정합니다|"
    r"낙찰자\s*(?:결정|선정)|계약상대자\s*결정|적격심사"
)
_DECISIVE = re.compile(r"낙찰자\s*(?:결정|선정)|계약상대자\s*결정|적격심사")
# 제안 2: 참고·숙지·참조가 같은 문장에 있는 매치는 버립니다. 기존 서류 목록
# 표지도 같은 문장 기준으로 좁혀 유지합니다.
_NOISE = re.compile(r"참고|숙지|참조|양식|목록|문의")
_SENTENCE_END = re.compile(r"[.!?。！？]")  # noqa: RUF001 - 전각 문장 부호도 경계로 봅니다.
_MOIS_ACADEMIC_SUBTABLE_RULES = frozenset({"R2", "R4", "R14"})


@dataclass(frozen=True)
class _Match:
    rule: _Rule
    text_index: int
    start: int
    end: int
    score: float


def _normalize(text: str) -> str:
    cleaned = text.replace("\u200b", "").replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _context(text: str, start: int, end: int) -> str:
    """매치 주변을 80자 이내로 자릅니다."""
    length = end - start
    if length >= _EVIDENCE_LIMIT:
        return text[start : start + _EVIDENCE_LIMIT].strip()
    padding = (_EVIDENCE_LIMIT - length) // 2
    left = max(0, start - padding)
    right = min(len(text), left + _EVIDENCE_LIMIT)
    left = max(0, right - _EVIDENCE_LIMIT)
    return text[left:right].strip()


def _sentence_at(text: str, start: int, end: int) -> str:
    """매치가 속한 문장을 돌려줍니다."""
    left = 0
    for boundary in _SENTENCE_END.finditer(text, 0, start):
        left = boundary.end()
    right_match = _SENTENCE_END.search(text, end)
    right = right_match.start() if right_match is not None else len(text)
    return text[left:right]


def _accepted_matches(texts: Sequence[str]) -> list[_Match]:
    matches: list[_Match] = []
    for text_index, text in enumerate(texts):
        for rule in _RULES:
            weight = _WEIGHTS.get(rule.rule_id)
            if weight is None:
                continue
            for found in rule.pattern.finditer(text):
                window = text[
                    max(0, found.start() - _DECISION_WINDOW) : min(
                        len(text), found.end() + _DECISION_WINDOW
                    )
                ]
                if _NOISE.search(_sentence_at(text, found.start(), found.end())):
                    continue
                if not _DECISION_CUE.search(window):
                    continue
                multiplier = 1.5 if _DECISIVE.search(window) else 1.0
                matches.append(
                    _Match(
                        rule=rule,
                        text_index=text_index,
                        start=found.start(),
                        end=found.end(),
                        score=weight * multiplier,
                    )
                )
    return matches


def _branch_scores(matches: Sequence[_Match]) -> dict[str, float]:
    scores = dict.fromkeys(_TIE_ORDER, 0.0)
    for match in matches:
        scores[match.rule.branch] += match.score
    # 2.2절 실측에서 R8·R9 매치는 1건이 전부 오탐이었습니다. 명시적인
    # 조달청·지자체 기준이 함께 확인되면 물품 장 인용은 적용 기준이 아닙니다.
    if scores[MOIS4] > 0 and (scores[PPS] > 0 or scores[LOCAL] > 0):
        scores[MOIS4] = 0.0
    return scores


def _best_match(matches: Sequence[_Match]) -> _Match | None:
    if not matches:
        return None
    return max(matches, key=lambda match: (match.score, -match.text_index, -match.start))


def _rule_ids(matches: Sequence[_Match]) -> tuple[str, ...]:
    return tuple(sorted({match.rule.rule_id for match in matches}, key=lambda item: int(item[1:])))


def _merge_rule_ids(*groups: Sequence[str]) -> tuple[str, ...]:
    merged = {rule_id for group in groups for rule_id in group}
    return tuple(sorted(merged, key=lambda item: int(item[1:])))


def _evidence_for_match(texts: Sequence[str], match: _Match | None) -> str | None:
    if match is None:
        return None
    return _context(texts[match.text_index], match.start, match.end)


def _raw_match(texts: Sequence[str], rule_id: str) -> tuple[int, int, int] | None:
    rule = next(item for item in _RULES if item.rule_id == rule_id)
    for text_index, text in enumerate(texts):
        found = rule.pattern.search(text)
        if found is not None:
            return text_index, found.start(), found.end()
    return None


def _needle_position(texts: Sequence[str], needle: str) -> tuple[int, int] | None:
    for text_index, text in enumerate(texts):
        start = text.find(needle)
        if start >= 0:
            return text_index, start
    return None


def _numeric_evidence(texts: Sequence[str], needle: str) -> str | None:
    position = _needle_position(texts, needle)
    if position is None:
        return None
    text_index, start = position
    return _context(texts[text_index], start, start + len(needle))


def _resolve_mois_branch(texts: Sequence[str], matches: Sequence[_Match]) -> BandRegimeResult:
    """행안부 갈래 안에서 세부표를 가릅니다.

    `87.745` 는 기술·일반용역 확정 신호입니다. 학술연구는 `별표 4` 직접
    표지(R14)나 `학술연구용역 평가기준`(R4)이 있을 때만 확정하고, 장 이름
    (R1·R3)만 있으면 `UNSPECIFIED_SUBTABLE` 로 남깁니다. `80.495` 는 확정
    신호로 쓰지 않습니다. 기술용역 문구(R12)는 학술연구 세부표가 명시되지 않은
    경우에만 세부표 신호로 씁니다.
    """
    chapter_matches = [match for match in matches if match.rule.branch == MOIS_ACADEMIC]
    chapter_rules = _rule_ids(chapter_matches)
    technical = _raw_match(texts, "R12")
    technical_rules: tuple[str, ...] = ("R12",) if technical is not None else ()

    if (evidence := _numeric_evidence(texts, _NUMERIC_MOIS_OTHER)) is not None:
        return BandRegimeResult(
            MOIS_OTHER, evidence, _merge_rule_ids(chapter_rules, technical_rules)
        )

    academic_subtable = _best_match(
        [match for match in matches if match.rule.rule_id in _MOIS_ACADEMIC_SUBTABLE_RULES]
    )
    if academic_subtable is not None:
        return BandRegimeResult(
            MOIS_ACADEMIC,
            _evidence_for_match(texts, academic_subtable),
            chapter_rules,
        )

    if technical is not None:
        text_index, start, end = technical
        return BandRegimeResult(
            MOIS_OTHER,
            _context(texts[text_index], start, end),
            _merge_rule_ids(chapter_rules, technical_rules),
        )

    return BandRegimeResult(UNSPECIFIED_SUBTABLE, None, chapter_rules)


def _result_for_branch(
    branch: str, texts: Sequence[str], matches: Sequence[_Match]
) -> BandRegimeResult:
    branch_matches = [match for match in matches if match.rule.branch == branch]
    return BandRegimeResult(
        branch,
        _evidence_for_match(texts, _best_match(branch_matches)),
        _rule_ids(branch_matches),
    )


def classify_band_regime(
    texts: Sequence[str], *, extraction_failed: bool = False
) -> BandRegimeResult:
    """첨부 원문 텍스트들에서 적용 기준 갈래를 판별합니다.

    첨부 레코드 자체가 없는 빈 시퀀스는 `NO_ATTACH` 입니다. 첨부는 있었지만
    텍스트가 모두 비었거나 호출부가 `extraction_failed` 로 알리면
    `EXTRACT_FAIL` 입니다. 어느 규칙도 결정 문장에서 잡히지 않으면
    `UNSPECIFIED` 이고, 행안부 장 이름만 있고 세부표가 없으면
    `UNSPECIFIED_SUBTABLE` 입니다.
    """
    if extraction_failed:
        return BandRegimeResult(EXTRACT_FAIL, None, ())
    normalized = [text for text in (_normalize(item) for item in texts) if text]
    if not normalized:
        if len(texts) > 0:
            return BandRegimeResult(EXTRACT_FAIL, None, ())
        return BandRegimeResult(NO_ATTACH, None, ())

    matches = _accepted_matches(normalized)
    scores = _branch_scores(matches)
    branch = max(
        _TIE_ORDER,
        key=lambda item: (round(scores[item], 6), -_TIE_ORDER.index(item)),
    )
    if scores[branch] <= 0:
        return BandRegimeResult(UNSPECIFIED, None, ())

    if branch in (MOIS_ACADEMIC, MOIS_OTHER):
        return _resolve_mois_branch(normalized, matches)
    return _result_for_branch(branch, normalized, matches)
