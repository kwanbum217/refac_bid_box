"""
src/app/services/document_extraction/credit_certificate.py

신용평가등급확인서 텍스트에서 등급·평가일을 찾는 순수 함수 파서입니다.

LLM·외부 API·DB 를 쓰지 않고 표기 규칙만으로 값을 뽑습니다. 국내 신용평가사
등급확인서의 '신용등급', '평가등급', '평가일', '평가일자', '발급일' 표기를
인식하며, 회사채·기업어음 등 특정 상품 등급이 일반 신용등급을 덮지 않도록
구분합니다. 후보가 여러 개면 confidence 를 낮추고, 확신할 수 없는 값은
만들지 않습니다. 등급 값은 등록된 코드(CREDIT_GRADE_CHOICES)만 돌려줍니다.

업로드 원문이 아니라 OCR 로 읽은 텍스트도 같은 규칙으로 파싱하며, 이때는
cap_confidence 로 신뢰도 상한을 적용합니다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from src.app.services.auth_forms import CREDIT_GRADE_CHOICES
from src.app.services.evaluation_rules import find_credit_grade

DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE = "credit_rating_certificate"
MAX_EVIDENCE_LENGTH = 120

Confidence = Literal["high", "medium", "low"]
ExtractionStatus = Literal["extracted", "unrecognized"]

_CONFIDENCE_ORDER: dict[str, int] = {"high": 2, "medium": 1, "low": 0}

_VALID_GRADE_CODES = frozenset(code for code, _ in CREDIT_GRADE_CHOICES)

# 등급확인서는 0 을 생략한 표기(AA, A, BBB, BB, B)를 섞어 씁니다. 등록 코드로 맞춥니다.
_GRADE_ALIASES = {
    "AA": "AA0",
    "A": "A0",
    "BBB": "BBB0",
    "BB": "BB0",
    "B": "B0",
}

# OCR 이 숫자 0 을 문자 O 로 읽은 경우를 되돌리는 대응표입니다.
_OCR_DIGIT_FIXES = {"O": "0"}

# 등급 끝자리 숫자 0 은 OCR 이 문자 O 로 자주 오독합니다(AA0 -> AAO). 후보 수집
# 단계에서 두 표기를 모두 받아 두고, 정규화 때 등록 코드로 되돌립니다.
_GRADE_ALTERNATION = (
    r"(?:AAA|AA\+|AA[0O]|AA-|AA|A\+|A[0O]|A-|A|BBB\+|BBB[0O]|BBB-|BBB|BB\+|BB[0O]|BB-|BB|"
    r"B\+|B[0O]|B-|B|CCC\+|CCC|CC|C|D)"
)
_GRADE_RE = re.compile(rf"(?<![A-Z0-9+\-]){_GRADE_ALTERNATION}(?![A-Z0-9+\-])")
_GRADE_LABEL_RE = re.compile(
    r"(신용평가등급|단기신용등급|기업어음등급|회사채등급|신용등급|평가등급)"
)
_GRADE_LABEL_WINDOW = 48

_DATE_LABEL_RE = re.compile(r"(평가일자|평가기준일|평가일|발급일자|발급일)")
_DATE_LABEL_WINDOW = 60
_DATE_PATTERN = r"((?:19|20)\d{2})[년.\-/](\d{1,2})[월.\-/](\d{1,2})일?"
_DATE_RE = re.compile(_DATE_PATTERN)

# OCR 이 평가일 라벨을 일부만 남기고(등급평, 평가, 평일) 날짜를 바로 뒤에 둔 경우를
# 잇기 위한 것입니다. 조각과 날짜 사이에 다른 글자가 끼면 잇지 않으므로, 라벨이
# 유실되고 유효기간 값만 남은 표본을 잘못 붙이지 않습니다.
_PARTIAL_DATE_LABEL_RE = re.compile(
    r"(?:등급평가일|등급평가|등급평|평가일|평일|평가)" + _DATE_PATTERN
)

# 일반 신용등급이 아니라 특정 상품(회사채·기업어음·단기) 등급임을 알리는 표지입니다.
_INSTRUMENT_MARKERS = ("기업어음", "단기", "회사채", "CP")

_DATE_LABEL_PRIORITY = {
    "평가일": 0,
    "평가일자": 0,
    "평가기준일": 1,
    "발급일": 2,
    "발급일자": 2,
}

# 등급 정의표(2쪽 나열표)와 무등급 안내는 등급 후보가 아니라 설명입니다. 이
# 표지가 나온 줄부터는 등급 후보로 잡지 않습니다.
_DEFINITION_MARKERS = ("등급의정의", "등급정의", "등급기호", "채무상환능력", "무등급")

# '...에 준하는 등급' 문장은 회사채 표지가 아니라 실제 등급을 서술합니다.
_BOILERPLATE_MARKER = "준하는"

# 2열 표에서 라벨과 값이 여러 줄 떨어진 경우를 잇기 위한 탐색 범위입니다.
_GRADE_LOOKAHEAD_LINES = 4
_DATE_LOOKAHEAD_LINES = 3

# 유효기간·유효기한 값은 평가일이 아니므로 후보에서 배제합니다.
_EFFECTIVE_LABEL_RE = re.compile(r"(유효기간|유효기한)")


@dataclass(frozen=True)
class FieldResult:
    """미리 채우기 화면에 돌려줄 값 하나와 근거 조각입니다."""

    value: str
    confidence: Confidence
    page: int
    text: str


@dataclass(frozen=True)
class CreditCertificateResult:
    """등급확인서 텍스트 한 건의 파싱 결과입니다."""

    status: ExtractionStatus
    document_type: str | None
    credit_grade: FieldResult | None
    credit_evaluated_on: FieldResult | None


@dataclass(frozen=True)
class _Candidate:
    value: str
    page: int
    order: int
    text: str
    preferred: bool


@dataclass(frozen=True)
class _DateCandidate:
    value: str
    page: int
    order: int
    text: str
    priority: int


def _canonical(text: str) -> str:
    """전각·자모 호환 문자를 정규화하고 공백을 한 칸으로 접습니다."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))


def _compact(text: str) -> str:
    """표기 대조용으로 공백을 모두 제거한 문자열입니다."""
    return re.sub(r"\s+", "", text)


def _canonical_grade(raw: str) -> str | None:
    """표기 그대로의 등급을 등록 코드로 맞추고 별표 10 등급군으로 재검증합니다.

    끝자리 숫자 0 을 문자 O 로 읽은 OCR 표기(AA0 -> AAO)는 등록 코드로 되돌립니다.
    """
    token = _compact(raw).upper()
    token = _GRADE_ALIASES.get(token, token)
    if token not in _VALID_GRADE_CODES and token[-1:] in _OCR_DIGIT_FIXES:
        token = token[:-1] + _OCR_DIGIT_FIXES[token[-1]]
    if token not in _VALID_GRADE_CODES:
        return None
    if find_credit_grade(token) is None:
        return None
    return token


def _canonical_date(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _trim_evidence(line: str) -> str:
    return line.strip()[:MAX_EVIDENCE_LENGTH]


def _page_lines(page_text: str) -> list[str]:
    """쪽 텍스트를 줄 단위로 나누고 줄마다 정규화합니다."""
    return [_canonical(line) for line in page_text.splitlines()]


def _definition_start(compacts: list[str]) -> int:
    """등급 정의표가 시작하는 줄 위치입니다. 없으면 줄 수를 돌려줍니다."""
    for index, compact in enumerate(compacts):
        if any(marker in compact for marker in _DEFINITION_MARKERS):
            return index
    return len(compacts)


def _is_standalone_grade(compact: str) -> bool:
    """한 줄이 등급 기호 하나로만 이루어졌는지 봅니다. 2열 표의 값 줄을 잡습니다."""
    return _GRADE_RE.fullmatch(compact) is not None


def _is_preferred(label: str, prefix: str, line: str) -> bool:
    """일반 신용등급 후보인지 판단합니다.

    상품 표지가 라벨 자체에 있거나(회사채등급·기업어음등급·단기신용등급), 같은 줄의
    직전 라벨 끝부터 현재 라벨 시작까지 접두에 있으면(기업어음 신용등급) 상품 등급으로
    봅니다. '...에 준하는 등급' 문장은 실제 등급을 서술하므로 표지로 강등하지 않습니다.
    """
    if _BOILERPLATE_MARKER in line:
        return True
    if any(marker in label for marker in _INSTRUMENT_MARKERS):
        return False
    return not any(marker in prefix for marker in _INSTRUMENT_MARKERS)


def _lookahead_grade(compacts: list[str], index: int, cutoff: int) -> str | None:
    """라벨 줄 아래 몇 줄 안에서 2열 표의 등급 값을 찾습니다."""
    limit = min(index + 1 + _GRADE_LOOKAHEAD_LINES, cutoff, len(compacts))
    for candidate_index in range(index + 1, limit):
        compact = compacts[candidate_index]
        if not compact:
            continue
        if _GRADE_LABEL_RE.search(compact):
            return None
        match = _GRADE_RE.search(compact)
        if match is None:
            continue
        value = _canonical_grade(match.group(0))
        if value is not None:
            return value
    return None


def _pick_grade(candidates: list[_Candidate]) -> FieldResult | None:
    if not candidates:
        return None
    pool = [candidate for candidate in candidates if candidate.preferred]
    if not pool:
        return None
    counts = Counter(candidate.value for candidate in pool)

    def rank(value: str) -> tuple[int, int]:
        return counts[value], -min(
            candidate.order for candidate in pool if candidate.value == value
        )

    winner_value = max(counts, key=rank)
    winner = min(
        (candidate for candidate in pool if candidate.value == winner_value),
        key=lambda candidate: candidate.order,
    )
    if len(pool) == 1:
        confidence: Confidence = "high"
    elif len(counts) == 1:
        confidence = "medium"
    else:
        confidence = "low"
    return FieldResult(
        value=winner.value,
        confidence=confidence,
        page=winner.page,
        text=winner.text,
    )


def _pick_date(candidates: list[_DateCandidate]) -> FieldResult | None:
    if not candidates:
        return None
    best_priority = min(candidate.priority for candidate in candidates)
    pool = [candidate for candidate in candidates if candidate.priority == best_priority]
    winner = max(pool, key=lambda candidate: (candidate.value, -candidate.order))
    distinct_values = {candidate.value for candidate in candidates}
    if len(candidates) == 1:
        confidence: Confidence = "high"
    elif len(distinct_values) == 1:
        confidence = "medium"
    else:
        confidence = "low"
    return FieldResult(
        value=winner.value,
        confidence=confidence,
        page=winner.page,
        text=winner.text,
    )


def _collect_grade_candidates(pages: Sequence[str]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for page_index, page_text in enumerate(pages, start=1):
        evidence = _trim_evidence(_canonical(page_text))
        lines = _page_lines(page_text)
        compacts = [_compact(line) for line in lines]
        cutoff = _definition_start(compacts)
        for index in range(cutoff):
            compact = compacts[index]
            if not compact or not _is_standalone_grade(compact):
                continue
            value = _canonical_grade(compact)
            if value is not None:
                candidates.append(_Candidate(value, page_index, len(candidates), evidence, True))
        for index in range(cutoff):
            compact = compacts[index]
            if not compact:
                continue
            matches = list(_GRADE_LABEL_RE.finditer(compact))
            for match_index, match in enumerate(matches):
                segment_end = (
                    matches[match_index + 1].start()
                    if match_index + 1 < len(matches)
                    else len(compact)
                )
                segment = compact[match.end() : segment_end][:_GRADE_LABEL_WINDOW]
                grade_match = _GRADE_RE.search(segment)
                value = _canonical_grade(grade_match.group(0)) if grade_match else None
                if value is None:
                    value = _lookahead_grade(compacts, index, cutoff)
                if value is None:
                    continue
                label_start = matches[match_index - 1].end() if match_index else 0
                candidates.append(
                    _Candidate(
                        value=value,
                        page=page_index,
                        order=len(candidates),
                        text=evidence,
                        preferred=_is_preferred(
                            match.group(1), compact[label_start : match.start()], lines[index]
                        ),
                    )
                )
    return _dedupe(candidates)


def _date_in_region(region: str) -> str | None:
    """구간의 첫 날짜를 돌려줍니다. 유효기간·유효기한 값이면 버립니다."""
    date_match = _DATE_RE.search(region)
    if date_match is None:
        return None
    effective = _EFFECTIVE_LABEL_RE.search(region)
    if effective is not None and effective.start() < date_match.start():
        return None
    return _canonical_date(*date_match.groups())


def _lookahead_date(compacts: list[str], index: int) -> str | None:
    """라벨 줄 아래 몇 줄 안에서 값을 찾습니다. 유효기간 값을 만나면 버립니다."""
    passed_effective = False
    limit = min(index + 1 + _DATE_LOOKAHEAD_LINES, len(compacts))
    for candidate_index in range(index + 1, limit):
        compact = compacts[candidate_index]
        if not compact:
            continue
        if _DATE_LABEL_RE.search(compact):
            return None
        if _EFFECTIVE_LABEL_RE.search(compact):
            passed_effective = True
            if _DATE_RE.search(compact):
                return None
            continue
        if passed_effective:
            if _DATE_RE.search(compact):
                return None
            continue
        found = _date_in_region(compact)
        if found is not None:
            return found
    return None


def _dedupe_dates(candidates: list[_DateCandidate]) -> list[_DateCandidate]:
    seen: set[tuple[int, str, str]] = set()
    unique: list[_DateCandidate] = []
    for candidate in candidates:
        key = (candidate.page, candidate.text, candidate.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _collect_date_candidates(pages: Sequence[str]) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []
    for page_index, page_text in enumerate(pages, start=1):
        evidence = _trim_evidence(_canonical(page_text))
        compacts = [_compact(line) for line in _page_lines(page_text)]
        for index, compact in enumerate(compacts):
            if not compact:
                continue
            matches = list(_DATE_LABEL_RE.finditer(compact))
            for match_index, match in enumerate(matches):
                segment_end = (
                    matches[match_index + 1].start()
                    if match_index + 1 < len(matches)
                    else len(compact)
                )
                segment = compact[match.end() : segment_end][:_DATE_LABEL_WINDOW]
                value = _date_in_region(segment)
                if value is None:
                    value = _lookahead_date(compacts, index)
                if value is None:
                    continue
                candidates.append(
                    _DateCandidate(
                        value=value,
                        page=page_index,
                        order=len(candidates),
                        text=evidence,
                        priority=_DATE_LABEL_PRIORITY.get(match.group(1), 2),
                    )
                )
        # OCR 이 라벨을 여러 줄로 쪼갠 경우(예: '등급평 / 가 일')를 쪽 전체에서 다시 잇습니다.
        page_compact = _compact(_canonical(page_text))
        for match in _DATE_LABEL_RE.finditer(page_compact):
            value = _date_in_region(page_compact[match.end() :][:_DATE_LABEL_WINDOW])
            if value is None:
                continue
            candidates.append(
                _DateCandidate(
                    value=value,
                    page=page_index,
                    order=len(candidates),
                    text=evidence,
                    priority=_DATE_LABEL_PRIORITY.get(match.group(1), 2),
                )
            )
        # OCR 이 평가일 라벨을 일부만 남긴 경우(등급평, 평가, 평일)에도 바로 뒤 날짜를
        # 평가일 값으로 잇습니다.
        for match in _PARTIAL_DATE_LABEL_RE.finditer(page_compact):
            value = _canonical_date(*match.groups())
            if value is None:
                continue
            candidates.append(
                _DateCandidate(
                    value=value,
                    page=page_index,
                    order=len(candidates),
                    text=evidence,
                    priority=_DATE_LABEL_PRIORITY["평가일"],
                )
            )
    return _dedupe_dates(candidates)


def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
    seen: set[tuple[int, str, str]] = set()
    unique: list[_Candidate] = []
    for candidate in candidates:
        key = (candidate.page, candidate.text, candidate.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def parse_credit_certificate(pages: Sequence[str]) -> CreditCertificateResult:
    """쪽별 텍스트에서 신용등급과 평가일을 찾습니다.

    등급을 찾으면 status=extracted 이고 document_type 이 붙습니다. 등급을 찾지
    못하면(스캔본·다른 문서) status=unrecognized, document_type=null 이며,
    찾지 못한 필드는 null 입니다. 평가일만 찾은 경우에도 날짜는 돌려줍니다.
    """
    grade = _pick_grade(_collect_grade_candidates(pages))
    evaluated_on = _pick_date(_collect_date_candidates(pages))
    if grade is None:
        return CreditCertificateResult(
            status="unrecognized",
            document_type=None,
            credit_grade=None,
            credit_evaluated_on=evaluated_on,
        )
    return CreditCertificateResult(
        status="extracted",
        document_type=DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE,
        credit_grade=grade,
        credit_evaluated_on=evaluated_on,
    )


def _cap_field(field: FieldResult | None, ceiling: Confidence) -> FieldResult | None:
    if field is None or _CONFIDENCE_ORDER[field.confidence] <= _CONFIDENCE_ORDER[ceiling]:
        return field
    return replace(field, confidence=ceiling)


def cap_confidence(result: CreditCertificateResult, ceiling: Confidence) -> CreditCertificateResult:
    """결과의 신뢰도를 상한 이하로 낮춥니다. 값·근거는 그대로 둡니다.

    화면에서 원문 대조가 필요한 경로(예: OCR)는 표기 규칙이 직접 읽은 경우보다
    근거가 약하므로, 후보 판정이 'high' 를 줬더라도 상한을 넘지 못하게 합니다.
    """
    return CreditCertificateResult(
        status=result.status,
        document_type=result.document_type,
        credit_grade=_cap_field(result.credit_grade, ceiling),
        credit_evaluated_on=_cap_field(result.credit_evaluated_on, ceiling),
    )
