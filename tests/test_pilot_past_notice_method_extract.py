"""`scripts/pilot_past_notice_method_extract.py` 의 네트워크 없는 단위 시험.

작은 HWPX 바이트를 직접 만들어 다운로드·추출·집계 경로를 검증합니다. 실제
나라장터 요청은 하지 않습니다.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.extract_score_params import extract_document_text
from scripts.pilot_past_notice_method_extract import (
    DownloadedDocument,
    NoticeResult,
    RateLimitedFetcher,
    all_attachments,
    detect_format,
    extract_criteria_name,
    extract_notice,
    select_attachments,
    summarize,
    top_criteria,
    write_results_csv,
    write_summary_csv,
)


def _paragraph(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _table(rows: list[list[str]]) -> str:
    body = []
    for row in rows:
        body.append("<hp:tr>")
        for cell in row:
            body.append(f"<hp:tc>{_paragraph(cell)}</hp:tc>")
        body.append("</hp:tr>")
    return "<hp:tbl>" + "".join(body) + "</hp:tbl>"


def make_hwpx(paragraphs: list[str], rows: list[list[str]]) -> bytes:
    """`extract_document_text` 가 읽는 최소 HWPX 바이트를 만듭니다."""
    body = "".join(_paragraph(p) for p in paragraphs) + _table(rows)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hp="urn:hp">{body}</hs:sec>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section0.xml", xml)
    return buffer.getvalue()


QUALIFICATION_HWPX = make_hwpx(
    [
        "제10조(낙찰자 결정) 심사결과 종합평점이 85점 이상인 자를 낙찰자로 결정한다.",
        "기술용역 적격심사 세부기준을 적용한다.",
    ],
    [
        ["추정가격", "5억원 미만", "5억원 이상"],
        ["Ⅲ. 입찰가격", "70", "60"],
        ["평점(점)=배점한도-2 TIMES vert ( {90} over {100} - 입찰가격/예정가격 )"],
    ],
)


def sample_row(bid_no: str = "20190100011", **raw_overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "sucsfbidMthdCd": "낙030001",
        "sucsfbidMthdNm": "공고서참조",
        "stdNtceDocUrl": "https://example.test/a",
        "ntceSpecFileNm1": "공고문.hwp",
        "ntceSpecDocUrl1": "https://example.test/a",
        "ntceSpecFileNm2": "적격심사 세부기준.hwp",
        "ntceSpecDocUrl2": "https://example.test/b",
        "ntceSpecFileNm3": "과업지시서.hwp",
        "ntceSpecDocUrl3": "https://example.test/c",
    }
    raw.update(raw_overrides)
    return {
        "bid_ntce_no": bid_no,
        "bid_ntce_ord": "00",
        "bid_ntce_nm": "용역 공고",
        "bid_ntce_dt": "2019-01-01 10:00:00",
        "presmpt_prce": "100000000",
        "raw_data": json.dumps(raw, ensure_ascii=False),
    }


def test_detect_format_identifies_hwpx_and_pdf() -> None:
    assert detect_format(QUALIFICATION_HWPX) == "hwpx"
    assert detect_format(b"%PDF-1.4 scan") == "pdf"
    assert detect_format(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest") == "hwp"
    assert detect_format(b"????") == "기타"


def test_select_attachments_keeps_notice_and_criteria_only() -> None:
    raw = json.loads(str(sample_row()["raw_data"]))
    attachments = all_attachments(raw)
    assert len(attachments) == 3
    selected = [name for name, _ in select_attachments(raw)]
    assert selected == ["공고문.hwp", "적격심사 세부기준.hwp"]


def test_extract_criteria_name_specific_and_generic() -> None:
    assert extract_criteria_name(["기술용역 적격심사 기준"]) == "기술용역 적격심사"
    assert extract_criteria_name(["폐기물처리용역 적격심사 세부기준"]) == "폐기물처리용역 적격심사"
    assert extract_criteria_name(["적격심사 세부기준"]) == "적격심사세부기준"
    assert extract_criteria_name(["아무 내용 없음"]) == ""


def test_hwpx_document_is_readable_and_yields_params() -> None:
    document = extract_document_text(QUALIFICATION_HWPX)
    assert document.ok
    assert document.rows


def test_extract_notice_full_extraction() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return QUALIFICATION_HWPX

    result = extract_notice(sample_row(), fetcher, documents_dir=None)
    assert result.year == 2019
    assert result.attachment_count == 3
    assert result.selected_count == 2
    assert result.downloaded_count == 2
    assert result.readable_count == 2
    assert result.criteria_name == "기술용역 적격심사"
    assert result.pass_threshold == "85"  # noqa: S105
    assert set(result.max_price_score.split("|")) == {"60", "70"}
    assert result.multiplier == "2"
    assert result.outcome == "전량추출"
    assert calls == ["https://example.test/a", "https://example.test/b"]


def test_extract_notice_without_attachment() -> None:
    row = sample_row(
        bid_no="20150100000",
        stdNtceDocUrl="",
        ntceSpecFileNm1="",
        ntceSpecDocUrl1="",
        ntceSpecDocUrl2="",
        ntceSpecDocUrl3="",
    )
    result = extract_notice(row, lambda url: b"", documents_dir=None)
    assert result.selected_count == 0
    assert result.outcome == "첨부없음"


def test_extract_notice_download_failure_is_classified() -> None:
    def failing(url: str) -> bytes:
        raise RuntimeError("boom")

    result = extract_notice(sample_row(), failing, documents_dir=None)
    assert result.selected_count == 2
    assert result.downloaded_count == 0
    assert result.outcome == "다운로드실패"


def test_extract_notice_scan_pdf_is_classified() -> None:
    result = extract_notice(sample_row(), lambda url: b"%PDF-1.7 scan", documents_dir=None)
    assert result.readable_count == 0
    assert result.outcome == "스캔PDF"


def test_extract_notice_unreadable_format_is_classified() -> None:
    result = extract_notice(sample_row(), lambda url: b"RANDOMBYTES", documents_dir=None)
    assert result.readable_count == 0
    assert result.outcome == "판독불가형식"


def test_summarize_is_recomputable() -> None:
    good = extract_notice(sample_row(), lambda url: QUALIFICATION_HWPX, documents_dir=None)
    none = extract_notice(
        sample_row(
            bid_no="20150100000",
            stdNtceDocUrl="",
            ntceSpecDocUrl1="",
            ntceSpecDocUrl2="",
            ntceSpecDocUrl3="",
        ),
        lambda url: b"",
        documents_dir=None,
    )
    summary = summarize([good, none])
    assert len(summary) == 1
    assert summary[0]["sample"] == 2
    assert summary[0]["with_attachment"] == 1
    assert summary[0]["selected"] == 1
    assert summary[0]["readable"] == 1
    assert summary[0]["criteria_name"] == 1
    assert summary[0]["threshold"] == 1
    assert summary[0]["both_bk"] == 1


def test_top_criteria_counts() -> None:
    rows = [
        NoticeResult(
            2019, "a", "n", 1, 1, 1, 1, 1, "hwpx", "기술용역 적격심사", "85", "70", "2", "전량추출"
        ),
        NoticeResult(
            2019, "b", "n", 1, 1, 1, 1, 1, "hwpx", "기술용역 적격심사", "85", "70", "2", "전량추출"
        ),
        NoticeResult(2019, "c", "n", 1, 1, 1, 1, 1, "hwpx", "", "", "", "", "표해석실패"),
    ]
    assert top_criteria(rows) == [("기술용역 적격심사", 2)]


def test_csv_roundtrip(tmp_path: Path) -> None:
    result = extract_notice(sample_row(), lambda url: QUALIFICATION_HWPX, documents_dir=None)
    out = tmp_path / "results.csv"
    write_results_csv([result], out)
    text = out.read_text(encoding="utf-8")
    assert "bid_ntce_no" in text
    assert "20190100011" in text
    assert "전량추출" in text

    summary_path = tmp_path / "summary.csv"
    write_summary_csv(summarize([result]), summary_path)
    assert "both_bk" in summary_path.read_text(encoding="utf-8")


def test_extract_notice_uses_cached_document(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fetcher(url: str) -> bytes:
        calls["n"] += 1
        return QUALIFICATION_HWPX

    first = extract_notice(sample_row(), fetcher, documents_dir=tmp_path)
    assert calls["n"] == 2
    second = extract_notice(sample_row(), fetcher, documents_dir=tmp_path)
    assert calls["n"] == 2
    assert second.readable_count == first.readable_count == 2


def test_rate_limited_fetcher_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, fail: bool) -> None:
            self.content = b"payload"
            self._fail = fail

        def raise_for_status(self) -> None:
            if self._fail:
                raise RuntimeError("http 500")

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url: str, headers: dict[str, str] | None = None) -> Response:
            self.calls += 1
            return Response(fail=self.calls == 1)

        def close(self) -> None:
            return None

    fetcher = RateLimitedFetcher(sleep_seconds=0)
    client = Client()
    fetcher._client = client
    assert fetcher("https://example.test/x") == b"payload"
    assert client.calls == 2
    assert fetcher.request_count == 2
    assert fetcher.byte_count == len(b"payload")


def test_rate_limited_fetcher_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def get(self, url: str, headers: dict[str, str] | None = None):
            raise RuntimeError("always")

    fetcher = RateLimitedFetcher(sleep_seconds=0)
    fetcher._client = Client()
    with pytest.raises(RuntimeError):
        fetcher("https://example.test/x")


def test_downloaded_document_dataclass() -> None:
    document = DownloadedDocument(
        name="x.hwp", data=b"abc", fmt="hwp", text=extract_document_text(b"abc")
    )
    assert document.fmt == "hwp"
