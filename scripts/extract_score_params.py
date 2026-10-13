"""
scripts/extract_score_params.py

공고에서 가격 배점한도 B, 평점계수 k, 적격 통과점수 T 를 추출하는 실측 기반 추출기.

B(가격 배점한도), k(평점계수), T(통과점수) 는 나라장터 OpenAPI 응답과 공고 본문에는
없다. 실측으로 확인된 획득 경로는 다음 둘뿐이다.

  1. T  : 공고문 또는 적격심사 세부기준 본문의 "종합평점이 N점" 문구.
  2. B,k: 공고에 첨부된 적격심사 세부기준 [별표] 의 "입찰가격 평점 계산식".
          계산식은 "평점 = 배점한도 - k x |(기준비율 - 입찰가격/예정가격)| x 100" 형태이며
          배점한도(=B)는 같은 별표의 입찰가격 배점한도 표에서 읽는다.

따라서 이 추출기는 공고에 위 문서가 첨부되어 있고, 첨부가 기계 판독 가능한 형식
(HWPX, HWPML, 바이너리 HWP)일 때만 값을 반환한다. 첨부가 없거나 스캔 PDF 이거나
표 구조가 해석되지 않으면 추측하지 않고 None 과 사유를 반환한다.

사용 예:
    python3 scripts/extract_score_params.py --bid-no R26BK01707844 \
        --category Servc --bgn 20260901 --end 20260915
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import html
import io
import json
import re
import sys
import xml.etree.ElementTree as ET  # nosec B405 - 정화한 조달청 OpenAPI 응답만 파싱합니다
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from src.app.services.api_collector import get_service_key as _shared_service_key
from src.app.services.api_collector import sanitize_xml_text

API_BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
CATEGORY_OPERATION: dict[str, str] = {
    "Thng": "getBidPblancListInfoThng",
    "Cnstwk": "getBidPblancListInfoCnstwk",
    "Servc": "getBidPblancListInfoServc",
    "Frgcpt": "getBidPblancListInfoFrgcpt",
}

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 적격심사 세부기준 [별표] 의 입찰가격 평점 계산식. 실측 서식 세 갈래를 모두 읽는다.
#
# 1) 배점한도 자리표시자 + 계수. HWPX·HWPML·바이너리 공통이며 평점(점) 접두와
#    TIMES 또는 곱셈 기호가 붙는다.
#    실측 예: "수식입니다.BIGCIRC `평점(점)`=`배점한도-`2` TIMES vert ( {90} over ..."
#             "ㅇ평점(점) = 배점한도\u00ad4\u00d7"
_PLACEHOLDER_PRICE_FORMULA_RE = re.compile(
    r"평점\s*(?:\(\s*점\s*\))?\s*=\s*배점한도\s*[-\u2013\u2212\u00ad]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:TIMES|[\u00d7xX*])"
)
# 2) 배점한도가 숫자로 풀린 서식. group(1) 은 배점한도(B), group(2) 는 계수(k)이며
#    계수가 1 이면 곱셈 항이 통째로 생략된다("평점=30 -|").
#    실측 예: "평점(점) = 60 - 2 \u00d7", "평점 = 90 - 20 \u00d7", "*평점=50-2\u00d7"
_NUMERIC_PRICE_FORMULA_RE = re.compile(
    r"평점\s*(?:\(\s*점\s*\))?\s*=\s*(\d+(?:\.\d+)?)\s*"
    r"(?:[-\u2013\u2212\u00ad]\s*(\d+(?:\.\d+)?)?\s*[\u00d7xX*])?"
)
# 3) 평점 접두가 없고 배점한도 자리표시자만 남은 서식. 시설분야용역 별표가 이렇게
#    렌더링되며 계수는 곱셈 기호 앞 숫자다. 실측 예: "배점한도-60\u00d7"
_BARE_LIMIT_PRICE_FORMULA_RE = re.compile(
    r"배점한도\s*[-\u2013\u2212\u00ad]\s*(\d+(?:\.\d+)?)\s*[\u00d7xX*]"
)
# 기준비율. HWP 수식 개체는 "{90} over {100}" 형태로 평문화된다.
_BASE_RATE_RE = re.compile(r"\{\s*(\d+(?:\.\d+)?)\s*\}\s*over\s*\{\s*(\d+(?:\.\d+)?)\s*\}")
# 기준비율의 바이너리 HWP 서식. 분수 성분이 조판 순서로 흩어져 "적용 88 입찰가격"
# 처럼 남는다. 실측 예: "입찰가격 평점산식 88 입찰가격 평점(점) = 60 - 2 \u00d7"
_BASE_RATE_TEXT_RE = re.compile(r"(?:적용|평점산식)\s*(\d+(?:\.\d+)?)\s*입찰가격")
# 계산식이 표 셀이 아니라 문단(수식 개체)으로만 남은 문서를 문단 단위로 찾는다.
# HWPX·HWPML 수식 개체와 바이너리 HWP 수식 개체가 모두 이 형태로 평문화된다.
_FORMULA_HINT_RE = re.compile(
    r"평점\s*(?:\(\s*점\s*\))?\s*=\s*(?:배점한도|\d+(?:\.\d+)?)"
    r"|배점한도\s*[-\u2013\u2212\u00ad]\s*\d+(?:\.\d+)?\s*[\u00d7xX*]"
)
# 통과점수 문구. 실측 예: "종합평점이 85점(다만, 소프트웨어용역의 ...은 88점)이상이면"
_PASS_THRESHOLD_RE = re.compile(r"종합평점[이가은는]?\s*(\d+(?:\.\d+)?)\s*점")
# 추정가격 구간 라벨의 금액 항. "5억원 이상", "10억 미만", "2억원 이상 5억원 미만" 처럼
# 금액마다 부등호가 붙는다. 부등호 없는 금액은 구간 경계로 확정할 수 없어 잡지 않는다.
_BAND_TERM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*억\s*원?\s*(이상|이하|초과|미만)")
_WHITESPACE_RE = re.compile(r"\s+")
# 바이너리 HWP 는 인라인 제어문자가 다른 문자권 문자로 오검출된다.
# 한글/Latin/CJK/일반 부호만 남겨 근거 문자열을 깨끗하게 유지한다.
_HWP_KEEP_RE = re.compile(
    r"[^\t\n\u0020-\u007E\u00A1-\u00FF\u2010-\u2027\u2026\u3000-\u303F"
    r"\u3131-\u318E\u4E00-\u9FFF\uAC00-\uD7A3\uFF01-\uFF60]"
)

# HWP 5.x 바이너리 본문 레코드 태그. BodyText/SectionN 스트림은 레코드 열이다.
# 레코드 헤더는 32비트로 TagID(10) | Level(10) | Size(12) 이며 Size 가 0xFFF 이면
# 다음 4바이트가 실제 크기다. 한컴 공개 문서 "HWP 5.0 문서 파일 형식" 기준.
_HWP_TAG_PARA_TEXT = 0x43
_HWP_TAG_CTRL_HEADER = 0x47
_HWP_TAG_LIST_HEADER = 0x48
_HWP_TAG_TABLE = 0x4D
_HWP_CTRL_ID_TABLE = b"tbl "
_HWP_EXTENDED_SIZE = 0xFFF


def _norm(text: str | None) -> str:
    return _WHITESPACE_RE.sub("", text or "")


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


# ============================================================================
# 첨부 문서 텍스트 추출
# ============================================================================


@dataclass(frozen=True)
class DocumentText:
    """첨부 문서 하나에서 뽑아낸 텍스트.

    rows 는 표 구조가 보존된 셀 목록이고, flat 은 표를 포함한 전체 평문이다.
    둘 다 비어 있으면 reason 에 사유가 담긴다.
    """

    rows: tuple[tuple[str, ...], ...] = ()
    flat: str = ""
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.rows or self.flat)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return _WHITESPACE_RE.sub(" ", html.unescape(text)).strip()


def _formula_text_rows(text: str) -> tuple[tuple[str, ...], ...]:
    """평문에서 입찰가격 평점 계산식 문단을 1열 행으로 승격한다.

    계산식이 표 셀이 아니라 수식 개체 문단으로만 남은 문서가 있다. 그 문단을
    행으로 올려 두면 `parse_price_formula` 가 표 행과 같은 방식으로 읽는다.
    문맥에 '입찰가격' 또는 '예정가격'이 있어야 입찰가격 계산식으로 인정한다.
    """
    rows: list[tuple[str, ...]] = []
    for match in _FORMULA_HINT_RE.finditer(text or ""):
        start = max(0, match.start() - 60)
        end = min(len(text), match.end() + 240)
        window = text[start:end]
        if "입찰가격" in window or "예정가격" in window:
            rows.append((window,))
    return tuple(rows)


def _hwpx_document(data: bytes) -> DocumentText:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return DocumentText(reason="HWPX 압축 해제 실패")

    rows: list[tuple[str, ...]] = []
    paragraphs: list[str] = []
    for name in archive.namelist():
        if not re.match(r"Contents/section\d+\.xml$", name):
            continue
        xml = archive.read(name).decode("utf-8", "replace")
        for para in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
            text = _strip_tags(para)
            if text:
                paragraphs.append(text)
        for tr in re.findall(r"<hp:tr\b.*?</hp:tr>", xml, re.S):
            cells: list[str] = []
            for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tr, re.S):
                cells.append(
                    " ".join(
                        _strip_tags(p) for p in re.findall(r"<hp:p\b.*?</hp:p>", tc, re.S)
                    ).strip()
                )
            if any(cells):
                rows.append(tuple(cells))
    if not paragraphs and not rows:
        return DocumentText(reason="HWPX 본문 텍스트 없음")
    flat = "\n".join(paragraphs)
    rows.extend(_formula_text_rows(flat))
    return DocumentText(rows=tuple(rows), flat=flat)


def _hwpml_document(data: bytes) -> DocumentText:
    text = _strip_tags(data.decode("utf-8", "replace"))
    if not text:
        return DocumentText(reason="HWPML 본문 텍스트 없음")
    return DocumentText(rows=_formula_text_rows(text), flat=text)


def _ole_streams(data: bytes) -> dict[str, bytes]:
    """CFB(OLE) 복합 파일에서 스트림 이름 -> 바이트 사전을 뽑는다."""
    import struct
    import zlib

    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("OLE 시그니처가 아닙니다.")

    sector_size = 1 << int.from_bytes(data[30:32], "little")
    mini_size = 1 << int.from_bytes(data[32:34], "little")
    num_fat = int.from_bytes(data[44:48], "little")
    dir_start = int.from_bytes(data[48:52], "little")
    mini_cutoff = int.from_bytes(data[56:60], "little")
    mini_fat_start = int.from_bytes(data[60:64], "little")
    num_mini_fat = int.from_bytes(data[64:68], "little")
    difat_start = int.from_bytes(data[68:72], "little")
    num_difat = int.from_bytes(data[72:76], "little")

    end_of_chain = 0xFFFFFFFE
    threshold = 0xFFFFFFFA

    def block(sector: int) -> bytes:
        start = (sector + 1) * sector_size
        return data[start : start + sector_size]

    difat = list(struct.unpack("<109I", data[76:512]))
    sector = difat_start
    for _ in range(num_difat):
        if sector >= threshold:
            break
        entries = struct.unpack(f"<{sector_size // 4}I", block(sector))
        difat.extend(entries[:-1])
        sector = entries[-1]

    fat: list[int] = []
    for fat_sector in difat[:num_fat]:
        if fat_sector >= threshold:
            continue
        fat.extend(struct.unpack(f"<{sector_size // 4}I", block(fat_sector)))

    def chain(start: int) -> list[int]:
        sectors: list[int] = []
        current = start
        while current < threshold and len(sectors) < 1_000_000:
            sectors.append(current)
            current = fat[current] if current < len(fat) else end_of_chain
        return sectors

    def read_big(start: int, size: int | None = None) -> bytes:
        raw = b"".join(block(s) for s in chain(start))
        return raw[:size] if size is not None else raw

    directory = read_big(dir_start)
    entries: list[tuple[str, int, int, int]] = []
    for offset in range(0, len(directory), 128):
        entry = directory[offset : offset + 128]
        if len(entry) < 128:
            break
        name_len = int.from_bytes(entry[64:66], "little")
        name = entry[: max(0, name_len - 2)].decode("utf-16le", "ignore")
        entries.append(
            (
                name,
                entry[66],
                int.from_bytes(entry[116:120], "little"),
                int.from_bytes(entry[120:128], "little"),
            )
        )

    roots = [e for e in entries if e[1] == 5]
    mini_stream = read_big(roots[0][2], roots[0][3]) if roots and roots[0][3] else b""

    mini_fat: list[int] = []
    sector = mini_fat_start
    for _ in range(num_mini_fat):
        if sector >= threshold:
            break
        mini_fat.extend(struct.unpack(f"<{sector_size // 4}I", block(sector)))
        sector = fat[sector] if sector < len(fat) else end_of_chain

    def read_mini(start: int, size: int) -> bytes:
        chunks: list[bytes] = []
        current = start
        while current < threshold and len(chunks) < 1_000_000:
            chunks.append(mini_stream[current * mini_size : (current + 1) * mini_size])
            current = mini_fat[current] if current < len(mini_fat) else end_of_chain
        return b"".join(chunks)[:size]

    def decompress(raw: bytes) -> bytes:
        try:
            return zlib.decompressobj(-15).decompress(raw)
        except zlib.error:
            return raw

    streams: dict[str, bytes] = {}
    for name, entry_type, start, size in entries:
        if entry_type != 2:
            continue
        streams[name] = read_mini(start, size) if size < mini_cutoff else read_big(start, size)

    header = streams.get("FileHeader", b"")
    compressed = bool(header[36] & 0x01) if len(header) > 36 else True
    if compressed:
        streams = {name: decompress(raw) for name, raw in streams.items()}
    return streams


def _hwp_records(data: bytes) -> list[tuple[int, int, bytes]]:
    """HWP 5.x 본문 스트림을 (tag, level, payload) 레코드 목록으로 푼다.

    손상되었거나 잘린 레코드를 만나면 그 지점에서 멈춘다. 예외를 내지 않는다.
    """
    records: list[tuple[int, int, bytes]] = []
    offset = 0
    end = len(data)
    while offset + 4 <= end:
        header = int.from_bytes(data[offset : offset + 4], "little")
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        offset += 4
        if size == _HWP_EXTENDED_SIZE:
            if offset + 4 > end:
                break
            size = int.from_bytes(data[offset : offset + 4], "little")
            offset += 4
        if offset + size > end:
            break
        records.append((tag, level, data[offset : offset + size]))
        offset += size
    return records


def _hwp_para_text(payload: bytes) -> str:
    """PARA_TEXT 레코드 payload 를 사람이 읽는 문자열로 만든다."""
    text = _HWP_KEEP_RE.sub("", payload.decode("utf-16le", "ignore"))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _hwp_cell_text(
    records: list[tuple[int, int, bytes]], start: int, cell_level: int
) -> tuple[str, int]:
    """LIST_HEADER 하나가 여는 셀의 문단 텍스트를 모은다.

    다음 셀(LIST_HEADER, 같은 레벨) 또는 상위 레벨 레코드를 만나면 멈춘다.
    중첩 표 셀의 문단(더 깊은 레벨)은 바깥 셀 텍스트에 포함된다.
    """
    parts: list[str] = []
    index = start
    while index < len(records):
        tag, level, payload = records[index]
        if level < cell_level:
            break
        if tag == _HWP_TAG_LIST_HEADER and level == cell_level:
            break
        if tag == _HWP_TAG_PARA_TEXT and level >= cell_level:
            text = _hwp_para_text(payload)
            if text:
                parts.append(text)
        index += 1
    return " ".join(parts), index


def _hwp_read_table(
    records: list[tuple[int, int, bytes]], start: int, level: int
) -> list[tuple[str, ...]]:
    """TABLE 레코드 하나를 행·열 격자로 복원한다.

    TABLE 레코드의 행 수·열 수와 셀 주소(col·row·colspan·rowspan)를 함께 써서
    격자를 만들고, 병합 셀은 덮는 칸을 같은 값으로 채운다. 비정상 값은 버린다.
    """
    header = records[start][2]
    declared_rows = int.from_bytes(header[4:6], "little") if len(header) >= 6 else 0
    declared_cols = int.from_bytes(header[6:8], "little") if len(header) >= 8 else 0

    cells: list[tuple[int, int, int, int, str]] = []
    index = start + 1
    while index < len(records):
        tag, cell_level, payload = records[index]
        if cell_level < level:
            break
        if tag == _HWP_TAG_LIST_HEADER and cell_level == level:
            if len(payload) < 16:
                index += 1
                continue
            col = int.from_bytes(payload[8:10], "little")
            row = int.from_bytes(payload[10:12], "little")
            col_span = int.from_bytes(payload[12:14], "little") or 1
            row_span = int.from_bytes(payload[14:16], "little") or 1
            if not (0 < col_span <= 64) or not (0 < row_span <= 64):
                col_span, row_span = 1, 1
            text, index = _hwp_cell_text(records, index + 1, cell_level)
            cells.append((row, col, row_span, col_span, text))
            continue
        index += 1

    if not cells:
        return []

    max_row = max(row + row_span for row, _, row_span, _, _ in cells)
    max_col = max(col + col_span for _, col, _, col_span, _ in cells)
    rows = max(declared_rows, max_row)
    cols = max(declared_cols, max_col)
    if not (0 < rows <= 100_000 and 0 < cols <= 10_000):
        rows, cols = max_row, max_col

    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for row, col, row_span, col_span, text in cells:
        for grid_row in range(row, min(row + row_span, rows)):
            for grid_col in range(col, min(col + col_span, cols)):
                if not grid[grid_row][grid_col]:
                    grid[grid_row][grid_col] = text
    return [tuple(grid_row) for grid_row in grid]


def _hwp_table_rows(records: list[tuple[int, int, bytes]]) -> list[tuple[str, ...]]:
    """레코드 목록에서 표를 찾아 행 목록으로 복원한다.

    표는 CTRL_HEADER(ctrl id 'tbl ') 바로 뒤의 TABLE 레코드로 시작한다.
    """
    rows: list[tuple[str, ...]] = []
    index = 0
    while index < len(records):
        tag, level, _payload = records[index]
        if (
            tag == _HWP_TAG_TABLE
            and index > 0
            and records[index - 1][0] == _HWP_TAG_CTRL_HEADER
            and bytes(records[index - 1][2][:4])[::-1] == _HWP_CTRL_ID_TABLE
        ):
            rows.extend(_hwp_read_table(records, index, level))
        index += 1
    return rows


def _binary_hwp_document(data: bytes) -> DocumentText:
    """바이너리 HWP 의 BodyText 스트림에서 본문 텍스트와 표 행을 뽑는다.

    HWP 5.0 은 본문을 UTF-16LE 로 저장한다. 문단 텍스트는 기존과 같이 평문으로
    잇고, 추가로 TABLE/LIST_HEADER 레코드에서 행·열 격자를 복원해 rows 에 넣는다.
    표 복원이 실패해도 평문 추출은 유지한다.
    """
    try:
        streams = _ole_streams(data)
    except Exception as exc:
        return DocumentText(reason=f"HWP 스트림 파싱 실패: {type(exc).__name__}")

    chunks: list[str] = []
    rows: list[tuple[str, ...]] = []
    for name in sorted(streams):
        if not (name.startswith("BodyText/") or re.fullmatch(r"(BodyText/)?Section\d+", name)):
            continue
        section = streams[name]
        chunks.append(_HWP_KEEP_RE.sub("", section.decode("utf-16le", "ignore")))
        # 표 복원이 실패해도 평문 추출은 유지한다.
        with contextlib.suppress(Exception):
            rows.extend(_hwp_table_rows(_hwp_records(section)))
    flat = _WHITESPACE_RE.sub(" ", "\n".join(chunks)).strip()
    if not flat and not rows:
        return DocumentText(reason="HWP 본문 텍스트 없음")
    rows.extend(_formula_text_rows(flat))
    return DocumentText(rows=tuple(rows), flat=flat)


def extract_document_text(data: bytes) -> DocumentText:
    """첨부 바이트에서 텍스트를 뽑는다. 지원하지 않는 형식은 사유를 담아 돌려준다."""
    if data[:5] == b"%PDF-":
        return DocumentText(reason="PDF 형식 - 텍스트 레이어 없음(스캔 이미지) 또는 파서 미지원")
    if data[:4] == b"PK\x03\x04":
        return _hwpx_document(data)
    if data[:5] == b"<?xml":
        return _hwpml_document(data)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _binary_hwp_document(data)
    return DocumentText(reason="지원하지 않는 첨부 형식")


# ============================================================================
# 순수 파서 (네트워크 없음)
# ============================================================================


@dataclass(frozen=True)
class BandValue:
    """추정가격 구간 라벨이 붙은 값."""

    label: str
    value: Decimal
    evidence: str


@dataclass(frozen=True)
class PriceFormula:
    """입찰가격 평점 계산식 한 줄."""

    label: str
    multiplier: Decimal
    base_rate: Decimal | None
    evidence: str


def parse_pass_threshold(text: str) -> tuple[Decimal | None, str | None]:
    """평문에서 적격 통과점수 T 를 찾는다.

    반환: (T, 근거 문자열). 찾지 못하면 (None, None).
    """
    for match in _PASS_THRESHOLD_RE.finditer(text or ""):
        value = _to_decimal(match.group(1))
        if value is None:
            continue
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 120)
        return value, _WHITESPACE_RE.sub(" ", text[start:end]).strip()
    return None, None


def _base_rate_of(cell: str) -> Decimal | None:
    """계산식 셀에서 기준비율을 뽑는다. 확정 불가면 None."""
    rate = _BASE_RATE_RE.search(cell)
    if rate is not None:
        numerator = _to_decimal(rate.group(1))
        denominator = _to_decimal(rate.group(2))
        if numerator is not None and denominator not in (None, Decimal("0")):
            return numerator / denominator
    text = _BASE_RATE_TEXT_RE.search(cell)
    if text is not None:
        numerator = _to_decimal(text.group(1))
        if numerator is not None:
            return numerator / Decimal("100")
    return None


def _price_formula_of(cell: str) -> tuple[Decimal, Decimal | None] | None:
    """계산식 셀 하나에서 (계수 k, 기준비율) 을 뽑는다. 계산식이 아니면 None."""
    placeholder = _PLACEHOLDER_PRICE_FORMULA_RE.search(cell)
    if placeholder is not None:
        multiplier = _to_decimal(placeholder.group(1))
        return (multiplier, _base_rate_of(cell)) if multiplier is not None else None
    numeric = _NUMERIC_PRICE_FORMULA_RE.search(cell)
    if numeric is not None:
        multiplier = _to_decimal(numeric.group(2)) if numeric.group(2) else Decimal("1")
        return (multiplier, _base_rate_of(cell)) if multiplier is not None else None
    bare = _BARE_LIMIT_PRICE_FORMULA_RE.search(cell)
    if bare is not None:
        multiplier = _to_decimal(bare.group(1))
        return (multiplier, _base_rate_of(cell)) if multiplier is not None else None
    return None


def parse_price_formula(rows: tuple[tuple[str, ...], ...] | list[list[str]]) -> list[PriceFormula]:
    """표 행 목록에서 입찰가격 평점 계산식들을 찾는다.

    계산식 셀 앞의 셀들을 구간 라벨로 삼는다. 예: ["추정가격", "고시금액", "이상", "<formula>"]

    계산식 셀 자체에 '입찰가격'이 없고 같은 행의 다른 셀에만 있는 문서가 많으므로,
    행 전체에 '입찰가격' 또는 '예정가격'이 있어야 입찰가격 계산식으로 인정한다.
    이 맥락 조건이 없으면 '실적계수' 같은 다른 심사분야 계산식을 잘못 집는다.
    """
    found: list[PriceFormula] = []
    for row in rows:
        row_text = " ".join(row)
        row_has_context = "입찰가격" in row_text or "예정가격" in row_text
        for index, cell in enumerate(row):
            # HWP 수식 개체는 조판에 따라 백틱이 끼어든다("`평점(점)`=`배점한도-`2`").
            normalized_cell = cell.replace("`", "")
            parts = _price_formula_of(normalized_cell)
            if parts is None:
                continue
            multiplier, base_rate = parts
            if not (
                row_has_context or "입찰가격" in normalized_cell or "예정가격" in normalized_cell
            ):
                continue
            label = " ".join(part for part in row[:index] if part).strip()
            found.append(
                PriceFormula(
                    label=label,
                    multiplier=multiplier,
                    base_rate=base_rate,
                    evidence=cell.strip(),
                )
            )
            break
    return found


def parse_price_limit(rows: tuple[tuple[str, ...], ...] | list[list[str]]) -> list[BandValue]:
    """표 행 목록에서 'Ⅱ.입찰가격' 행의 배점한도(=B)를 뽑는다.

    배점한도 값은 같은 표의 구간 라벨 행(모든 셀이 '추정가격'을 포함하고 '이상/미만'을
    가진 행)과 순서로 맞춘다. 라벨 행을 찾지 못하면 라벨 없는 후보로 돌려준다.
    """
    row_list = [list(r) for r in rows]
    limit_values: list[str] = []
    for row in row_list:
        joined = " ".join(row)
        if "입찰가격" not in joined:
            continue
        # 배점한도는 "70" 또는 "30점" 형태다. 수식 셀은 숫자 셀이 아니라 걸러진다.
        numbers = [
            cell.strip().removesuffix("점")
            for cell in row
            if re.fullmatch(r"\d{1,3}(?:\.\d+)?점?", cell.strip())
        ]
        if numbers:
            limit_values = numbers
            break
    if not limit_values:
        return []

    labels: list[str] = []
    for row in row_list:
        cells = [cell.strip() for cell in row if cell.strip()]
        if (
            len(cells) >= 2
            and all("추정가격" in cell for cell in cells)
            and any(("이상" in cell or "미만" in cell) for cell in cells)
        ):
            labels = cells
            break

    result: list[BandValue] = []
    for index, value in enumerate(limit_values):
        label = labels[index] if len(labels) == len(limit_values) else ""
        result.append(
            BandValue(label=label, value=Decimal(value), evidence=f"입찰가격 배점한도 {value}")
        )
    return result


def parse_band_terms(label: str) -> tuple[tuple[Decimal, str], ...]:
    """구간 라벨의 금액 항을 (금액, 부등호) 목록으로 해석한다.

    "추정가격 5억원 이상 10억원 미만" 은 (5억, 이상)·(10억, 미만) 두 항으로 읽는다.
    금액은 원 단위로 환산한다. 해석할 항이 없으면 빈 튜플이다(추정하지 않는다).
    """
    terms: list[tuple[Decimal, str]] = []
    for match in _BAND_TERM_RE.finditer(label or ""):
        amount = _to_decimal(match.group(1))
        if amount is None:
            continue
        terms.append((amount * Decimal(100_000_000), match.group(2)))
    return tuple(terms)


def band_matches(label: str, hint: str, estimated_price: int | None) -> bool:
    """구간 라벨이 공고의 낙찰방법 문구 또는 추정가격과 맞는지 판정한다.

    낙찰방법 문구에 라벨이 그대로 있으면 그것을 정본으로 삼는다. 그렇지 않으면
    라벨의 모든 금액 항(양 끝 구간 포함)을 추정가격이 만족해야 맞는 것으로 본다.
    """
    normalized_label = _norm(label)
    if normalized_label and normalized_label in _norm(hint):
        return True
    if estimated_price is None:
        return False
    terms = parse_band_terms(label)
    if not terms:
        return False
    price = Decimal(estimated_price)
    for amount, operator in terms:
        if operator == "이상" and price < amount:
            return False
        if operator == "이하" and price > amount:
            return False
        if operator == "초과" and price <= amount:
            return False
        if operator == "미만" and price >= amount:
            return False
    return True


def select_band(
    candidates: list[BandValue],
    hint: str,
    estimated_price: int | None,
) -> BandValue | None:
    """후보 중 공고에 해당하는 구간 값을 고른다. 확정 불가면 None.

    하나로 좁혀지지 않으면 선택하지 않는다. 후보가 하나뿐이더라도 그 라벨이 해석되는
    구간이고 추정가격이 그 구간 밖이면, 추정가격과 어긋나는 값을 고르지 않고 None 을
    돌려준다(추정 금지).
    """
    if not candidates:
        return None
    matched = [c for c in candidates if band_matches(c.label, hint, estimated_price)]
    if len(matched) == 1:
        return matched[0]
    if len(candidates) == 1 and not parse_band_terms(candidates[0].label):
        return candidates[0]
    return None


# ============================================================================
# 결과 스키마
# ============================================================================


@dataclass
class ScoreParams:
    """추출 결과. 못 얻은 필드는 None 이며 reasons 에 사유가 담긴다."""

    bid_no: str
    category: str
    bid_nm: str = ""
    method: str = ""
    criteria: str = ""
    estimated_price: int | None = None
    max_price_score: Decimal | None = None
    multiplier: Decimal | None = None
    pass_threshold: Decimal | None = None
    base_rate: Decimal | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str | None] = field(default_factory=dict)
    candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bid_no": self.bid_no,
            "category": self.category,
            "bid_nm": self.bid_nm,
            "method": self.method,
            "criteria": self.criteria,
            "estimated_price": self.estimated_price,
            "B_max_price_score": _decimal_out(self.max_price_score),
            "k_multiplier": _decimal_out(self.multiplier),
            "T_pass_threshold": _decimal_out(self.pass_threshold),
            "base_rate": _decimal_out(self.base_rate),
            "evidence": self.evidence,
            "reasons": self.reasons,
            "candidates": self.candidates,
            "documents": self.documents,
        }


def _decimal_out(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# ============================================================================
# 나라장터 OpenAPI 조회 및 첨부 수집
# ============================================================================


def get_service_key() -> str:
    """api_collector.py 와 동일한 서비스 키 조회를 그대로 쓴다."""
    return _shared_service_key()


async def fetch_announcement(
    bid_no: str,
    bgn_dt: str,
    end_dt: str,
    category: str = "Servc",
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str] | None:
    """공고 1건을 나라장터 OpenAPI 에서 찾는다. 조회 구간은 15일 이하여야 한다."""
    operation = CATEGORY_OPERATION.get(category)
    if operation is None:
        raise ValueError(f"지원하지 않는 카테고리입니다: {category}")
    params = {
        "serviceKey": get_service_key(),
        "pageNo": "1",
        "numOfRows": "999",
        "inqryDiv": "1",
        "inqryBgnDt": f"{bgn_dt}0000",
        "inqryEndDt": f"{end_dt}2359",
        "type": "xml",
    }
    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        response = await client.get(f"{API_BASE_URL}/{operation}", params=params, timeout=120)
        response.raise_for_status()
        # 조달청 OpenAPI 응답 전용. 외부 사용자 입력을 파싱하지 않는다.
        root = ET.fromstring(sanitize_xml_text(response.text))  # nosec B314 - 정화한 조달청 OpenAPI 응답만 파싱합니다  # noqa: S314
        for item in root.findall(".//item"):
            row = {child.tag: (child.text or "").strip() for child in item}
            if row.get("bidNtceNo") == bid_no:
                return row
        return None
    finally:
        if owns_client:
            await client.aclose()


def announcement_attachments(row: dict[str, str]) -> list[tuple[str, str]]:
    """공고 행에서 (파일명, URL) 첨부 목록을 만든다."""
    attachments: list[tuple[str, str]] = []
    std_url = row.get("stdNtceDocUrl")
    if std_url:
        attachments.append((row.get("ntceSpecFileNm1") or "stdNtceDoc", std_url))
    seen = {std_url}
    for index in range(1, 11):
        url = row.get(f"ntceSpecDocUrl{index}")
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append((row.get(f"ntceSpecFileNm{index}") or f"spec{index}", url))
    return attachments


async def download_document(url: str, *, client: httpx.AsyncClient | None = None) -> bytes:
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await client.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=180)
        response.raise_for_status()
        return response.content
    finally:
        if owns_client:
            await client.aclose()


# ============================================================================
# 오케스트레이션
# ============================================================================


def _estimated_price(row: dict[str, str]) -> int | None:
    raw = (row.get("presmptPrce") or "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _apply_documents(params: ScoreParams, documents: list[tuple[str, DocumentText]]) -> None:
    hint = params.method
    estimated = params.estimated_price

    limit_candidates: list[BandValue] = []
    formula_candidates: list[PriceFormula] = []
    for name, document in documents:
        if not document.ok:
            continue
        if document.rows:
            for limit in parse_price_limit(document.rows):
                limit_candidates.append(limit)
        for formula in parse_price_formula(document.rows):
            formula_candidates.append(formula)
        if params.pass_threshold is None:
            value, evidence = parse_pass_threshold(document.flat)
            if value is not None:
                params.pass_threshold = value
                params.evidence["T"] = f"{name}: {evidence}"
                params.reasons["T"] = None

    params.candidates["B"] = [
        {"label": c.label, "value": _decimal_out(c.value), "evidence": c.evidence}
        for c in limit_candidates
    ]
    params.candidates["k"] = [
        {
            "label": c.label,
            "value": _decimal_out(c.multiplier),
            "base_rate": _decimal_out(c.base_rate),
            "evidence": c.evidence,
        }
        for c in formula_candidates
    ]

    selected_limit = select_band(limit_candidates, hint, estimated)
    if selected_limit is not None:
        params.max_price_score = selected_limit.value
        params.evidence["B"] = selected_limit.evidence
        params.reasons["B"] = None

    selected_formula = select_band(
        [
            BandValue(label=c.label, value=c.multiplier, evidence=c.evidence)
            for c in formula_candidates
        ],
        hint,
        estimated,
    )
    if selected_formula is not None:
        params.multiplier = selected_formula.value
        params.evidence["k"] = selected_formula.evidence
        params.reasons["k"] = None
        base_rates = {c.base_rate for c in formula_candidates if c.base_rate is not None}
        if len(base_rates) == 1:
            params.base_rate = base_rates.pop()
            params.reasons["base_rate"] = None


def _finalize_reasons(params: ScoreParams, documents: list[tuple[str, DocumentText]]) -> None:
    if not documents:
        note = "공고에 첨부된 적격심사 세부기준/공고문이 없음"
        for key in ("B", "k", "T", "base_rate"):
            params.reasons.setdefault(key, note)
        return
    unreadable = [name for name, doc in documents if not doc.ok]
    for key in ("B", "k", "T", "base_rate"):
        if params.evidence.get(key):
            params.reasons.setdefault(key, None)
            continue
        if key in ("B", "k") and params.candidates.get(key):
            params.reasons.setdefault(key, "후보가 복수이고 공고 구간을 확정할 수 없음")
            continue
        if unreadable and not any(doc.ok for _, doc in documents):
            params.reasons.setdefault(
                key, f"첨부가 기계 판독 불가: {', '.join(sorted(set(unreadable)))}"
            )
            continue
        params.reasons.setdefault(key, "문서에서 해당 문구를 찾지 못함")


async def extract_score_params(
    bid_no: str,
    bgn_dt: str,
    end_dt: str,
    category: str = "Servc",
    *,
    client: httpx.AsyncClient | None = None,
) -> ScoreParams:
    """공고 식별자로 B, k, T 를 추출한다. 못 얻은 필드는 None 과 사유로 남는다."""
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        row = await fetch_announcement(bid_no, bgn_dt, end_dt, category, client=client)
        if row is None:
            raise LookupError(f"공고를 찾지 못했습니다: {bid_no} ({bgn_dt}~{end_dt}, {category})")

        params = ScoreParams(
            bid_no=bid_no,
            category=category,
            bid_nm=row.get("bidNtceNm", ""),
            method=row.get("sucsfbidMthdNm", ""),
            criteria=row.get("sucsfbidMthdAppStd", ""),
            estimated_price=_estimated_price(row),
        )

        documents: list[tuple[str, DocumentText]] = []
        for name, url in announcement_attachments(row):
            data = await download_document(url, client=client)
            params.documents.append(name)
            documents.append((name, extract_document_text(data)))

        _apply_documents(params, documents)
        _finalize_reasons(params, documents)
        return params
    finally:
        if owns_client:
            await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="공고에서 가격 배점한도 B, 평점계수 k, 통과점수 T 를 추출한다."
    )
    parser.add_argument("--bid-no", required=True, help="공고번호 (bidNtceNo)")
    parser.add_argument("--category", default="Servc", choices=sorted(CATEGORY_OPERATION))
    parser.add_argument("--bgn", required=True, help="조회 시작일 YYYYMMDD (15일 이하 구간)")
    parser.add_argument("--end", required=True, help="조회 종료일 YYYYMMDD")
    args = parser.parse_args(argv)

    try:
        params = asyncio.run(extract_score_params(args.bid_no, args.bgn, args.end, args.category))
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(params.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
