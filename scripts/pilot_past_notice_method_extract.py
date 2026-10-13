"""과거(2015~2024) 용역 공고 첨부에서 적격심사 기준을 뽑을 수 있는지 실측합니다.

배경
----
`raw_data.sucsfbidMthdNm` 은 2015~2024년 전량이 `공고서참조` 자리표시자이고,
2025년 이후에만 실제 낙찰방법명이 채워집니다. `sucsfbidMthdCd` 는 전 기간에
있어 적격심사제 계열(`낙030001`)을 골라낼 수 있습니다. 이 스크립트는 그렇게
고른 표본의 **첨부 공고서(HWP·HWPX·HWPML)** 에서 적격심사 기준명, 통과점수 T,
가격 배점한도 B, 평점계수 k 를 실제로 추출할 수 있는지 표본으로 판정합니다.
전량 추출은 하지 않습니다.

표본 만들기(이 스크립트 밖에서 한 번)
------------------------------------
표본 선정은 DB 조회로만 하고 `scripts/db_readonly_query.py` 만 씁니다.
연도별 50건(합계 500건)을 시드 문자열 `h1pilot20261013` 의 MD5 순서로 뽑습니다.

    uv run python scripts/db_readonly_query.py --sql "\\
      SELECT bid_ntce_no, bid_ntce_ord, bid_ntce_nm, bid_ntce_dt, presmpt_prce, raw_data \\
      FROM ( SELECT bid_ntce_no, bid_ntce_ord, bid_ntce_nm, bid_ntce_dt, presmpt_prce, raw_data, \\
             ROW_NUMBER() OVER (PARTITION BY YEAR(bid_ntce_dt) \\
               ORDER BY MD5(CONCAT('h1pilot20261013', bid_ntce_no, bid_ntce_ord))) AS rn \\
             FROM bid_announcements \\
             WHERE category='Servc' AND bid_ntce_dt >= '2015-01-01' AND bid_ntce_dt < '2025-01-01' \\
               AND raw_data->>'$.sucsfbidMthdCd' = '낙030001' \\
               AND (COALESCE(raw_data->>'$.ntceSpecDocUrl1','') <> '' \\
                    OR COALESCE(raw_data->>'$.stdNtceDocUrl','') <> '') ) t \\
      WHERE rn <= 50 ORDER BY bid_ntce_dt, bid_ntce_no" \\
      --format json --limit 500 > .cache/past_notice_pilot/sample_raw.json

실행
----
    uv run python scripts/pilot_past_notice_method_extract.py \\
        --sample .cache/past_notice_pilot/sample_raw.json \\
        --out-dir .cache/past_notice_pilot

첨부는 나라장터 URL 에서 받습니다. 요청 간 최소 1초, 동시 요청 1개, 실패 시
재시도 1회입니다. 받은 파일은 `--documents-dir`(기본 `.cache/past_notice_pilot/
attachments`) 아래에만 두고 커밋하지 않습니다.

추출기는 새로 만들지 않습니다. `scripts/extract_score_params.py` 의
`extract_document_text`, `parse_pass_threshold`, `parse_price_formula`,
`parse_price_limit` 을 그대로 재사용합니다. 이 스크립트는 다운로드·선별·집계만
담당하며 `extract_score_params.py` 를 수정하지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_score_params import (  # noqa: E402
    DocumentText,
    extract_document_text,
    parse_pass_threshold,
    parse_price_formula,
    parse_price_limit,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_SLEEP_SECONDS = 1.0
MAX_ATTEMPTS = 2  # 최초 1회 + 재시도 1회
REQUEST_TIMEOUT_SECONDS = 180

# 공고서·적격심사 관련 파일만 받습니다. 과업지시서·시방서·도면·내역서는 제외합니다.
ATTACHMENT_KEYWORDS: tuple[str, ...] = (
    "적격심사",
    "평점",
    "세부기준",
    "공고문",
    "공고서",
    "입찰공고",
    "낙찰자",
    "평가기준",
    "별표",
)

# 기준명 추출에 쓰는 용역 계열 표기입니다. 구체 명칭을 앞에 두어, 같은 위치에서
# 먼저 매칭되게 합니다.
_CRITERIA_SERVICE_TERMS: tuple[str, ...] = (
    "시설분야용역",
    "시설분야",
    "보험용역",
    "여객육상운송용역",
    "화물육상운송용역",
    "해양환경관리용역",
    "소프트웨어용역",
    "학술연구용역",
    "폐기물처리용역",
    "수리점검용역",
    "임대차",
    "수요기관지정형",
    "기술용역",
    "일반용역",
    "청소용역",
    "경비용역",
    "시설물경비용역",
    "시설물관리용역",
    "단순노무용역",
)
_CRITERIA_RE = re.compile(
    r"(" + "|".join(re.escape(term) for term in _CRITERIA_SERVICE_TERMS) + r")\s*적격심사"
)
_GENERIC_CRITERIA_RE = re.compile(r"(적격심사\s*세부기준)")
_WHITESPACE_RE = re.compile(r"\s+")
_UNSAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z가-힣._-]+")

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

Fetcher = Callable[[str], bytes]


# ============================================================================
# 표본 행 파싱
# ============================================================================


def _load_raw_data(row: dict[str, object]) -> dict[str, object]:
    raw = row.get("raw_data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def all_attachments(raw: dict[str, object]) -> list[tuple[str, str]]:
    """공고 행의 첨부 (파일명, URL) 전체 목록을 만듭니다. URL 기준으로 중복을 제거합니다."""
    attachments: list[tuple[str, str]] = []
    seen: set[str] = set()
    std_url = str(raw.get("stdNtceDocUrl") or "")
    if std_url:
        name = str(raw.get("ntceSpecFileNm1") or "stdNtceDoc")
        attachments.append((name, std_url))
        seen.add(std_url)
    for index in range(1, 11):
        url = str(raw.get(f"ntceSpecDocUrl{index}") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append((str(raw.get(f"ntceSpecFileNm{index}") or f"spec{index}"), url))
    return attachments


def select_attachments(raw: dict[str, object]) -> list[tuple[str, str]]:
    """첨부 중 공고서·적격심사 관련 파일명만 남깁니다."""
    return [
        (name, url)
        for name, url in all_attachments(raw)
        if any(keyword in name for keyword in ATTACHMENT_KEYWORDS)
    ]


def detect_format(data: bytes) -> str:
    """첨부 바이트의 형식을 식별합니다."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:5] == b"<?xml":
        return "hwpml"
    if data[:8] == _OLE_MAGIC:
        return "hwp"
    if data[:4] == b"PK\x03\x04":
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "zip"
        if any(name.startswith("Contents/") for name in names):
            return "hwpx"
        if any(name.startswith("xl/") for name in names):
            return "xlsx"
        if any(name.startswith("word/") for name in names):
            return "docx"
        if any(name.startswith("ppt/") for name in names):
            return "pptx"
        return "zip"
    return "기타"


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub("", text)


def extract_criteria_name(texts: Sequence[str]) -> str:
    """문서 본문·파일명에서 적격심사 기준명을 찾습니다. 못 찾으면 빈 문자열입니다."""
    joined = _normalize(" ".join(texts))
    match = _CRITERIA_RE.search(joined)
    if match is not None:
        return f"{match.group(1)} 적격심사"
    generic = _GENERIC_CRITERIA_RE.search(joined)
    if generic is not None:
        return _normalize(generic.group(1))
    return ""


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# ============================================================================
# 첨부 처리
# ============================================================================


@dataclass
class DownloadedDocument:
    name: str
    data: bytes
    fmt: str
    text: DocumentText


@dataclass
class NoticeResult:
    year: int
    bid_ntce_no: str
    bid_ntce_nm: str
    estimated_price: int | None
    attachment_count: int
    selected_count: int
    downloaded_count: int
    readable_count: int
    formats: str
    criteria_name: str
    pass_threshold: str
    max_price_score: str
    multiplier: str
    outcome: str

    def as_row(self) -> dict[str, str]:
        return {
            "year": str(self.year),
            "bid_ntce_no": self.bid_ntce_no,
            "bid_ntce_nm": self.bid_ntce_nm,
            "estimated_price": "" if self.estimated_price is None else str(self.estimated_price),
            "attachment_count": str(self.attachment_count),
            "selected_count": str(self.selected_count),
            "downloaded_count": str(self.downloaded_count),
            "readable_count": str(self.readable_count),
            "formats": self.formats,
            "criteria_name": self.criteria_name,
            "pass_threshold": self.pass_threshold,
            "max_price_score": self.max_price_score,
            "multiplier": self.multiplier,
            "outcome": self.outcome,
        }


def _classify_outcome(
    selected_count: int,
    downloaded_count: int,
    readable_count: int,
    formats: str,
    has_t: bool,
    has_b: bool,
    has_k: bool,
) -> str:
    """결과를 재계산 가능한 단일 분류로 정합니다."""
    if selected_count == 0:
        return "첨부없음"
    if downloaded_count == 0:
        return "다운로드실패"
    if readable_count == 0:
        return "스캔PDF" if "pdf" in formats.split(";") else "판독불가형식"
    if has_t and has_b and has_k:
        return "전량추출"
    if has_t or has_b or has_k:
        return "부분추출"
    return "표해석실패"


def _analyze_documents(
    filenames: Sequence[str], documents: Sequence[DownloadedDocument]
) -> tuple[str, str, str, str]:
    """(기준명, T, B, k) 를 뽑습니다. 값은 문자열이며 없으면 빈 문자열입니다."""
    texts = list(filenames)
    threshold_values: list[str] = []
    limit_values: list[Decimal] = []
    multiplier_values: list[Decimal] = []
    for document in documents:
        if not document.text.ok:
            continue
        texts.append(document.text.flat)
        for row in document.text.rows:
            texts.extend(row)
        if not threshold_values:
            value, _ = parse_pass_threshold(document.text.flat)
            if value is not None:
                threshold_values.append(_decimal_text(value))
        for limit in parse_price_limit(document.text.rows):
            limit_values.append(limit.value)
        for formula in parse_price_formula(document.text.rows):
            multiplier_values.append(formula.multiplier)

    criteria_name = extract_criteria_name(texts)
    threshold = threshold_values[0] if threshold_values else ""
    limit_text = "|".join(sorted({_decimal_text(v) for v in limit_values}))
    multiplier_text = "|".join(sorted({_decimal_text(v) for v in multiplier_values}))
    return criteria_name, threshold, limit_text, multiplier_text


def _safe_filename(bid_no: str, order: str, name: str) -> str:
    safe = _UNSAFE_FILENAME_RE.sub("_", name.strip()) or "attachment"
    return f"{bid_no}_{order}_{safe}"[:180]


def _fetch_attachment(fetcher: Fetcher, url: str, target: Path | None) -> bytes | None:
    """캐시가 있으면 읽고, 없으면 받아 캐시에 씁니다. 실패하면 None 을 돌려줍니다.

    None 은 그 첨부를 받지 못했음을 뜻하며, 결과 분류에서 다운로드 실패로 집계됩니다.
    """
    try:
        if target is not None and target.exists():
            return target.read_bytes()
        data = fetcher(url)
        if target is not None:
            target.write_bytes(data)
        return data
    except Exception:
        return None


def extract_notice(
    row: dict[str, object],
    fetcher: Fetcher,
    documents_dir: Path | None = None,
) -> NoticeResult:
    """공고 1건을 처리해 결과 레코드를 만듭니다. 예외를 밖으로 내보내지 않습니다."""
    raw = _load_raw_data(row)
    bid_no = str(row.get("bid_ntce_no") or "")
    order = str(row.get("bid_ntce_ord") or "")
    name = str(row.get("bid_ntce_nm") or "")
    dt_text = str(row.get("bid_ntce_dt") or "")
    year = int(dt_text[:4]) if dt_text[:4].isdigit() else 0
    try:
        estimated_price = int(str(row.get("presmpt_prce") or ""))
    except ValueError:
        estimated_price = None

    attachments = all_attachments(raw)
    selected = select_attachments(raw)

    documents: list[DownloadedDocument] = []
    formats: list[str] = []
    for name_attach, url in selected:
        target = None
        if documents_dir is not None:
            documents_dir.mkdir(parents=True, exist_ok=True)
            target = documents_dir / _safe_filename(bid_no, order, name_attach)
        data = _fetch_attachment(fetcher, url, target)
        if data is None:
            continue
        fmt = detect_format(data)
        formats.append(fmt)
        documents.append(
            DownloadedDocument(
                name=name_attach,
                data=data,
                fmt=fmt,
                text=extract_document_text(data),
            )
        )

    criteria_name, threshold, limit_text, multiplier_text = _analyze_documents(
        [name for name, _ in selected], documents
    )
    readable = sum(1 for document in documents if document.text.ok)
    formats_text = ";".join(sorted(set(formats)))
    outcome = _classify_outcome(
        selected_count=len(selected),
        downloaded_count=len(documents),
        readable_count=readable,
        formats=formats_text,
        has_t=bool(threshold),
        has_b=bool(limit_text),
        has_k=bool(multiplier_text),
    )
    return NoticeResult(
        year=year,
        bid_ntce_no=bid_no,
        bid_ntce_nm=name,
        estimated_price=estimated_price,
        attachment_count=len(attachments),
        selected_count=len(selected),
        downloaded_count=len(documents),
        readable_count=readable,
        formats=formats_text,
        criteria_name=criteria_name,
        pass_threshold=threshold,
        max_price_score=limit_text,
        multiplier=multiplier_text,
        outcome=outcome,
    )


# ============================================================================
# 네트워크
# ============================================================================


class RateLimitedFetcher:
    """나라장터 첨부를 1초 간격·동시 1개·재시도 1회로 받습니다."""

    def __init__(self, sleep_seconds: float = DEFAULT_SLEEP_SECONDS) -> None:
        self.sleep_seconds = sleep_seconds
        self.request_count = 0
        self.byte_count = 0
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS)
        return self._client

    def __call__(self, url: str) -> bytes:
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            if self.request_count > 0:
                time.sleep(self.sleep_seconds)
            self.request_count += 1
            try:
                response = self._ensure_client().get(
                    url, headers={"User-Agent": BROWSER_USER_AGENT}
                )
                response.raise_for_status()
                self.byte_count += len(response.content)
                return response.content
            except Exception as exc:  # 재시도 1회
                last_error = exc
        raise RuntimeError(f"첨부 다운로드 실패: {url} ({last_error})")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# ============================================================================
# 집계 및 산출물
# ============================================================================


def summarize(results: Sequence[NoticeResult]) -> list[dict[str, object]]:
    """연도별 집계를 만듭니다. 보고서 표는 이 결과로 재계산됩니다."""
    by_year: dict[int, list[NoticeResult]] = {}
    for result in results:
        by_year.setdefault(result.year, []).append(result)

    summary: list[dict[str, object]] = []
    for year in sorted(by_year):
        rows = by_year[year]
        summary.append(
            {
                "year": year,
                "sample": len(rows),
                "with_attachment": sum(1 for r in rows if r.attachment_count > 0),
                "selected": sum(1 for r in rows if r.selected_count > 0),
                "downloaded": sum(1 for r in rows if r.downloaded_count > 0),
                "readable": sum(1 for r in rows if r.readable_count > 0),
                "criteria_name": sum(1 for r in rows if r.criteria_name),
                "threshold": sum(1 for r in rows if r.pass_threshold),
                "max_price_score": sum(1 for r in rows if r.max_price_score),
                "multiplier": sum(1 for r in rows if r.multiplier),
                "both_bk": sum(1 for r in rows if r.max_price_score and r.multiplier),
            }
        )
    return summary


RESULT_FIELDS = (
    "year",
    "bid_ntce_no",
    "bid_ntce_nm",
    "estimated_price",
    "attachment_count",
    "selected_count",
    "downloaded_count",
    "readable_count",
    "formats",
    "criteria_name",
    "pass_threshold",
    "max_price_score",
    "multiplier",
    "outcome",
)

SUMMARY_FIELDS = (
    "year",
    "sample",
    "with_attachment",
    "selected",
    "downloaded",
    "readable",
    "criteria_name",
    "threshold",
    "max_price_score",
    "multiplier",
    "both_bk",
)


def write_results_csv(results: Sequence[NoticeResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.as_row())


def write_summary_csv(summary: Sequence[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in summary:
            writer.writerow(row)


def top_criteria(results: Sequence[NoticeResult], limit: int = 20) -> list[tuple[str, int]]:
    counter = Counter(result.criteria_name for result in results if result.criteria_name)
    return counter.most_common(limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="과거 용역 공고 첨부에서 적격심사 기준 추출 가능성을 표본 실측합니다."
    )
    parser.add_argument("--sample", required=True, help="표본 JSON 경로")
    parser.add_argument("--out-dir", default=".cache/past_notice_pilot", help="산출물 디렉터리")
    parser.add_argument(
        "--documents-dir",
        default=None,
        help="받은 첨부를 둘 디렉터리(기본: <out-dir>/attachments)",
    )
    parser.add_argument(
        "--sleep", type=float, default=DEFAULT_SLEEP_SECONDS, help="요청 간 간격(초)"
    )
    parser.add_argument("--max-notices", type=int, default=0, help="처리 건수 상한(0=전량)")
    parser.add_argument("--offline", action="store_true", help="캐시만 쓰고 네트워크를 쓰지 않음")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    documents_dir = Path(args.documents_dir) if args.documents_dir else out_dir / "attachments"

    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    if args.max_notices > 0:
        sample = sample[: args.max_notices]

    fetcher = RateLimitedFetcher(sleep_seconds=args.sleep)
    if args.offline:

        def fetcher(url: str) -> bytes:  # type: ignore[misc]
            raise RuntimeError("offline")

    results: list[NoticeResult] = []
    started = time.monotonic()
    try:
        for index, row in enumerate(sample, start=1):
            results.append(extract_notice(row, fetcher, documents_dir))
            if index % 25 == 0:
                print(f"[extract] {index}/{len(sample)}", flush=True)
    finally:
        fetcher.close()

    summary = summarize(results)
    write_results_csv(results, out_dir / "sample_extract_results.csv")
    write_summary_csv(summary, out_dir / "year_summary.csv")

    total_bytes = (
        sum(len((documents_dir / p.name).read_bytes()) for p in documents_dir.glob("*"))
        if documents_dir.exists()
        else 0
    )
    payload = {
        "sample_size": len(results),
        "requests": fetcher.request_count,
        "network_bytes": fetcher.byte_count,
        "documents_dir_bytes": total_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "summary": summary,
        "top_criteria": top_criteria(results),
        "outcomes": dict(Counter(result.outcome for result in results)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
