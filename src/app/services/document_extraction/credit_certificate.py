"""
src/app/services/document_extraction/credit_certificate.py

신용평가등급확인서 텍스트에서 등급·평가일을 찾는 순수 함수 파서입니다.

LLM·외부 API·DB 를 쓰지 않고 표기 규칙만으로 값을 뽑습니다. 국내 신용평가사
등급확인서의 '신용등급', '평가등급', '평가일', '평가일자', '발급일' 표기를
인식하며, 회사채·기업어음 등 특정 상품 등급이 일반 신용등급을 덮지 않도록
구분합니다. 후보가 여러 개면 confidence 를 낮추고, 확신할 수 없는 값은
만들지 않습니다. 등급 값은 등록된 코드(CREDIT_GRADE_CHOICES)만 돌려줍니다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from src.app.services.auth_forms import CREDIT_GRADE_CHOICES
from src.app.services.evaluation_rules import find_credit_grade

DOCUMENT_TYPE_CREDIT_RATING_CERTIFICATE = "credit_rating_certificate"
MAX_EVIDENCE_LENGTH = 120

Confidence = Literal["high", "medium", "low"]
ExtractionStatus = Literal["extracted", "unrecognized"]

_VALID_GRADE_CODES = frozenset(code for code, _ in CREDIT_GRADE_CHOICES)

# 등급확인서는 0 을 생략한 표기(AA, A, BBB, BB, B)를 섞어 씁니다. 등록 코드로 맞춥니다.
_GRADE_ALIASES = {
    "AA": "AA0",
    "A": "A0",
    "BBB": "BBB0",
    "BB": "BB0",
    "B": "B0",
}

_GRADE_ALTERNATION = (
    r"(?:AAA|AA\+|AA0|AA-|AA|A\+|A0|A-|A|BBB\+|BBB0|BBB-|BBB|BB\+|BB0|BB-|BB|"
    r"B\+|B0|B-|B|CCC\+|CCC|CC|C|D)"
)
_GRADE_RE = re.compile(rf"(?<![A-Z0-9+\-]){_GRADE_ALTERNATION}(?![A-Z0-9+\-])")
_GRADE_LABEL_RE = re.compile(
    r"(신용평가등급|단기신용등급|기업어음등급|회사채등급|신용등급|평가등급)"
)
_GRADE_LABEL_WINDOW = 48

_DATE_LABEL_RE = re.compile(r"(평가일자|평가기준일|평가일|발급일자|발급일)")
_DATE_LABEL_WINDOW = 60
_DATE_RE = re.compile(r"((?:19|20)\d{2})[년.\-/](\d{1,2})[월.\-/](\d{1,2})일?")

# 일반 신용등급이 아니라 특정 상품(회사채·기업어음·단기) 등급임을 알리는 표지입니다.
_INSTRUMENT_MARKERS = ("기업어음", "단기", "회사채", "CP")

_DATE_LABEL_PRIORITY = {
    "평가일": 0,
    "평가일자": 0,
    "평가기준일": 1,
    "발급일": 2,
    "발급일자": 2,
}


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
    """표기 그대로의 등급을 등록 코드로 맞추고 별표 10 등급군으로 재검증합니다."""
    token = _compact(raw).upper()
    token = _GRADE_ALIASES.get(token, token)
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


def _pick_first_nonempty(lines: list[str], index: int) -> str:
    for line in lines[index + 1 :]:
        if line.strip():
            return line
    return ""


def _pick_grade(candidates: list[_Candidate]) -> FieldResult | None:
    if not candidates:
        return None
    preferred = [candidate for candidate in candidates if candidate.preferred]
    pool = preferred or candidates
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
    if not winner.preferred and confidence == "high":
        confidence = "medium"
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
        lines = _canonical(page_text).splitlines()
        compacts = [_compact(line) for line in lines]
        for line_index, line in enumerate(lines):
            compact = compacts[line_index]
            if not compact:
                continue
            matches = list(_GRADE_LABEL_RE.finditer(compact))
            missing_on_line = False
            for index, match in enumerate(matches):
                segment_end = (
                    matches[index + 1].start() if index + 1 < len(matches) else len(compact)
                )
                segment = compact[match.end() : segment_end][:_GRADE_LABEL_WINDOW]
                grade_match = _GRADE_RE.search(segment)
                if grade_match is None:
                    missing_on_line = True
                    continue
                value = _canonical_grade(grade_match.group(0))
                if value is None:
                    continue
                context_start = matches[index - 1].end() if index > 0 else 0
                context = compact[context_start : match.start()]
                instrument = any(marker in context for marker in _INSTRUMENT_MARKERS)
                candidates.append(
                    _Candidate(
                        value=value,
                        page=page_index,
                        order=len(candidates),
                        text=_trim_evidence(line),
                        preferred=not instrument,
                    )
                )
            if missing_on_line and matches:
                next_compact = next(
                    (compact_line for compact_line in compacts[line_index + 1 :] if compact_line),
                    None,
                )
                if next_compact and not _GRADE_LABEL_RE.search(next_compact):
                    grade_match = _GRADE_RE.search(next_compact[:_GRADE_LABEL_WINDOW])
                    value = _canonical_grade(grade_match.group(0)) if grade_match else None
                    if value is not None:
                        context = compact[: matches[0].start()]
                        instrument = any(marker in context for marker in _INSTRUMENT_MARKERS)
                        candidates.append(
                            _Candidate(
                                value=value,
                                page=page_index,
                                order=len(candidates),
                                text=_trim_evidence(_pick_first_nonempty(lines, line_index)),
                                preferred=not instrument,
                            )
                        )
    return _dedupe(candidates)


def _collect_date_candidates(pages: Sequence[str]) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []
    for page_index, page_text in enumerate(pages, start=1):
        lines = _canonical(page_text).splitlines()
        compacts = [_compact(line) for line in lines]
        for line_index, line in enumerate(lines):
            compact = compacts[line_index]
            if not compact:
                continue
            matches = list(_DATE_LABEL_RE.finditer(compact))
            missing_on_line = False
            for index, match in enumerate(matches):
                segment_end = (
                    matches[index + 1].start() if index + 1 < len(matches) else len(compact)
                )
                segment = compact[match.end() : segment_end][:_DATE_LABEL_WINDOW]
                date_match = _DATE_RE.search(segment)
                if date_match is None:
                    missing_on_line = True
                    continue
                value = _canonical_date(*date_match.groups())
                if value is None:
                    continue
                candidates.append(
                    _DateCandidate(
                        value=value,
                        page=page_index,
                        order=len(candidates),
                        text=_trim_evidence(line),
                        priority=_DATE_LABEL_PRIORITY.get(match.group(1), 2),
                    )
                )
            if missing_on_line and matches:
                next_compact = next(
                    (compact_line for compact_line in compacts[line_index + 1 :] if compact_line),
                    None,
                )
                if next_compact and not _DATE_LABEL_RE.search(next_compact):
                    date_match = _DATE_RE.search(next_compact[:_DATE_LABEL_WINDOW])
                    value = _canonical_date(*date_match.groups()) if date_match else None
                    if value is not None:
                        candidates.append(
                            _DateCandidate(
                                value=value,
                                page=page_index,
                                order=len(candidates),
                                text=_trim_evidence(_pick_first_nonempty(lines, line_index)),
                                priority=_DATE_LABEL_PRIORITY.get(matches[0].group(1), 2),
                            )
                        )
    return candidates


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
