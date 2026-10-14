"""공고 첨부파일 카드의 순수 함수와 템플릿 렌더 회귀 테스트."""

from __future__ import annotations

import re

import pytest

from src.app.core.templating import templates
from src.app.services.announcement_attachments import describe_announcement_links


def _render(raw_data) -> str:
    links = describe_announcement_links(raw_data)
    return templates.env.get_template("bids/_attachments.html").render(announcement_links=links)


ANCHOR = re.compile(r"<a\b[^>]*>", re.IGNORECASE)


def test_files_follow_number_order_with_standard_and_detail():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/a.pdf",
        "ntceSpecFileNm1": "공고서.pdf",
        "ntceSpecDocUrl2": "https://www.g2b.go.kr/b.hwp",
        "ntceSpecFileNm2": "내역서.hwp",
        "ntceSpecDocUrl3": "https://www.g2b.go.kr/c.zip",
        "ntceSpecFileNm3": "도면.zip",
        "stdNtceDocUrl": "https://www.g2b.go.kr/std.pdf",
        "bidNtceDtlUrl": "https://www.g2b.go.kr/detail?bidNo=1",
    }

    links = describe_announcement_links(raw)

    assert [item["name"] for item in links["files"]] == ["공고서.pdf", "내역서.hwp", "도면.zip"]
    assert [item["url"] for item in links["files"]] == [
        "https://www.g2b.go.kr/a.pdf",
        "https://www.g2b.go.kr/b.hwp",
        "https://www.g2b.go.kr/c.zip",
    ]
    assert links["standard_notice_url"] == "https://www.g2b.go.kr/std.pdf"
    assert links["detail_url"] == "https://www.g2b.go.kr/detail?bidNo=1"


def test_empty_name_falls_back_to_attachment_number():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/a.pdf",
        "ntceSpecFileNm1": "   ",
        "ntceSpecDocUrl2": "https://www.g2b.go.kr/b.hwp",
    }

    links = describe_announcement_links(raw)

    assert [item["name"] for item in links["files"]] == ["첨부파일 1", "첨부파일 2"]


def test_duplicate_url_keeps_first_only():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/same.pdf",
        "ntceSpecFileNm1": "첫번째.pdf",
        "ntceSpecDocUrl2": "https://www.g2b.go.kr/same.pdf",
        "ntceSpecFileNm2": "두번째.pdf",
    }

    links = describe_announcement_links(raw)

    assert links["files"] == [{"name": "첫번째.pdf", "url": "https://www.g2b.go.kr/same.pdf"}]


def test_number_gaps_are_skipped():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/a.pdf",
        "ntceSpecFileNm1": "1번.pdf",
        "ntceSpecDocUrl3": "https://www.g2b.go.kr/c.pdf",
        "ntceSpecFileNm3": "3번.pdf",
    }

    links = describe_announcement_links(raw)

    assert [item["name"] for item in links["files"]] == ["1번.pdf", "3번.pdf"]


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://www.g2b.go.kr/x",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "https://evil.example.com/x",
        "https://www.g2b.go.kr.evil.com/x",
        "https://user@www.g2b.go.kr/x",
        "https://user:pass@www.g2b.go.kr/x",
        "https://www.g2b.go.kr/x y",
        "https://www.g2b.go.kr/x\n",
        "//www.g2b.go.kr/x",
        "",
        "   ",
    ],
)
def test_disallowed_urls_are_dropped(bad_url):
    raw = {
        "ntceSpecDocUrl1": bad_url,
        "ntceSpecFileNm1": "파일.pdf",
        "stdNtceDocUrl": bad_url,
        "bidNtceDtlUrl": bad_url,
    }

    links = describe_announcement_links(raw)

    assert links["files"] == []
    assert links["standard_notice_url"] is None
    assert links["detail_url"] is None


@pytest.mark.parametrize("raw_data", [None, "문자열", 123, ["목록"], {"ntceSpecDocUrl1": 42}])
def test_non_dict_or_non_string_input_is_safe(raw_data):
    assert describe_announcement_links(raw_data) == {
        "files": [],
        "standard_notice_url": None,
        "detail_url": None,
    }


def test_template_renders_new_tab_links_without_download():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/a.pdf",
        "ntceSpecFileNm1": "공고서.pdf",
        "stdNtceDocUrl": "https://www.g2b.go.kr/std.pdf",
        "bidNtceDtlUrl": "https://www.g2b.go.kr/detail",
    }

    html = _render(raw)
    anchors = ANCHOR.findall(html)

    assert 'href="https://www.g2b.go.kr/a.pdf"' in html
    assert "공고서.pdf" in html
    assert "표준공고문" in html
    assert "나라장터 공고 원문 보기" in html
    assert len(anchors) == 3
    for anchor in anchors:
        assert 'target="_blank"' in anchor
        assert 'rel="noopener noreferrer"' in anchor
        assert "download" not in anchor


def test_template_escapes_file_name():
    raw = {
        "ntceSpecDocUrl1": "https://www.g2b.go.kr/a.pdf",
        "ntceSpecFileNm1": "<script>alert(1)</script>",
    }

    html = _render(raw)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_template_hides_card_when_no_links():
    assert _render({}).strip() == ""
    assert _render({"stdNtceDocUrl": "http://www.g2b.go.kr/x"}).strip() == ""
