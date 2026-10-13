#!/usr/bin/env python3
"""
웹 공개 신용평가등급확인서 샘플로 등급확인서 PDF 추출을 실측하는 스크립트.

실물 확인서가 없으므로 신용평가사·조달 안내 페이지에 공개된 샘플·견본 확인서를
모아, 실제 추출 기능이 등급과 평가일을 맞게 읽는지 참고 실측합니다. 결과는
참고치이며 정식 Z4 적중률이 아닙니다.

기능 코드는 고치지 않고 그대로 호출합니다. 순서는 API 라우터의
`src/app/api/v1/documents.py` 의 `_extract` 와 같습니다. 먼저 텍스트 경로
(`extract_credit_certificate`)를 쓰고, 등급을 못 찾았을 때만 OCR 경로
(`ocr.extract_scanned_certificate`)로 한 번 더 읽습니다. 실측은 HTTP 를 거치지
않으므로 `DOCUMENT_OCR_ENABLED` 토글과 무관하게 OCR 경로를 직접 호출합니다.
토글이 켜진 운영 환경에서의 동작을 그대로 재현하기 위한 의도적 우회입니다.

입력 표본은 `.cache/credit_cert_samples/` 아래에만 둡니다(gitignore 대상이며
커밋하지 않습니다). 이 스크립트가 만드는 것도 같은 디렉터리 안입니다.

  - 텍스트 PDF: 웹에서 받은 그대로. 텍스트 경로를 시험합니다.
  - 스캔 PDF: 텍스트 PDF 를 pypdfium2 로 렌더링해 텍스트 레이어 없이 다시 감싼
    것으로 OCR 경로를 시험합니다. 실제 스캔이 아니라 합성 스캔입니다.
  - 이미지 표본: Pillow 로 PDF 로 감싸 스캔 표본으로 씁니다.
  - 스캔 PDF(원본): 일부 배포처는 확인서를 이미지 PDF 로 올립니다. 텍스트
    레이어가 없으면 그대로 스캔 표본으로 분류합니다.

정답(눈으로 확인한 등급·평가일)은 같은 디렉터리의 `answers.csv` 에 두고 대조해
적중을 계산합니다. 결과는 `result.csv` 에 씁니다.

사용:
  uv run python scripts/measure_credit_cert_samples.py
  uv run python scripts/measure_credit_cert_samples.py --score-only
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from src.app.core.config import settings
from src.app.services.document_extraction import (
    PdfValidationError,
    extract_credit_certificate,
    ocr,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES_DIR = PROJECT_ROOT / ".cache" / "credit_cert_samples"
RESULT_NAME = "result.csv"
ANSWERS_NAME = "answers.csv"
SCANS_DIR_NAME = "scans"

PDF_SUFFIXES = frozenset({".pdf"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"})
SCAN_RENDER_SCALE = 2.0
MAX_SAMPLE_PAGES = 10

KIND_TEXT = "text"
KIND_SCAN = "scan"
KIND_IMAGE = "image"

PATH_TEXT = "text"
PATH_OCR = "ocr"
PATH_NONE = "none"

STATUS_EXTRACTED = "extracted"
STATUS_UNRECOGNIZED = "unrecognized"
STATUS_REJECTED = "rejected"

EXPECT_EXTRACTED = "extracted"
EXPECT_UNRECOGNIZED = "unrecognized"
EXPECT_REJECTED = "rejected"

RESULT_FIELDS = [
    "sample_id",
    "source_file",
    "kind",
    "pages",
    "size_bytes",
    "text_status",
    "text_reject",
    "text_grade",
    "text_grade_conf",
    "text_date",
    "text_date_conf",
    "text_ms",
    "ocr_attempted",
    "ocr_status",
    "ocr_grade",
    "ocr_grade_conf",
    "ocr_date",
    "ocr_date_conf",
    "ocr_ms",
    "final_path",
    "final_status",
    "final_grade",
    "final_date",
]

ANSWER_FIELDS = ["sample_id", "expected_grade", "expected_date", "expect_status", "note"]


@dataclass(frozen=True)
class Case:
    """실측 대상 한 건입니다. path 는 읽을 PDF 파일입니다."""

    sample_id: str
    kind: str
    source_file: str
    path: Path


@dataclass
class Row:
    """실측 결과 한 줄입니다. CSV 컬럼과 1:1 로 맞춥니다."""

    sample_id: str
    source_file: str
    kind: str
    pages: int
    size_bytes: int
    text_status: str
    text_reject: str
    text_grade: str
    text_grade_conf: str
    text_date: str
    text_date_conf: str
    text_ms: str
    ocr_attempted: str
    ocr_status: str
    ocr_grade: str
    ocr_grade_conf: str
    ocr_date: str
    ocr_date_conf: str
    ocr_ms: str
    final_path: str
    final_status: str
    final_grade: str
    final_date: str


def _pdf_page_count(data: bytes) -> int:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


def _has_text_layer(data: bytes) -> bool:
    """앞쪽 쪽들에 텍스트가 하나라도 있으면 True 입니다."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return any((page.extract_text() or "").strip() for page in pdf.pages[:MAX_SAMPLE_PAGES])


def _render_scan_pdf(data: bytes) -> bytes:
    """PDF 를 쪽별 이미지로 렌더링하고 텍스트 레이어 없는 PDF 로 다시 감쌉니다."""
    images: list[Image.Image] = []
    with pdfium.PdfDocument(io.BytesIO(data)) as pdf:
        for page_index in range(min(len(pdf), MAX_SAMPLE_PAGES)):
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=SCAN_RENDER_SCALE)
                try:
                    images.append(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
            finally:
                page.close()
    if not images:
        raise ValueError("렌더링할 쪽이 없습니다")
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:], resolution=150.0)
    return buffer.getvalue()


def _image_to_pdf(path: Path) -> bytes:
    """이미지 표본을 텍스트 레이어 없는 PDF 로 감쌉니다."""
    buffer = io.BytesIO()
    with Image.open(path) as image:
        image.convert("RGB").save(buffer, format="PDF", resolution=150.0)
    return buffer.getvalue()


def _run_case(case: Case) -> Row:
    """표본 한 건을 텍스트 경로 -> OCR 경로 순으로 읽어 결과 줄을 만듭니다."""
    data = case.path.read_bytes()
    pages = 0
    try:
        pages = _pdf_page_count(data)
    except Exception:
        pages = 0

    text_status = STATUS_REJECTED
    text_reject = ""
    text_grade = text_grade_conf = text_date = text_date_conf = ""
    started = time.perf_counter()
    try:
        result = extract_credit_certificate(data)
    except PdfValidationError as exc:
        text_reject = type(exc).__name__
    except Exception as exc:
        text_reject = type(exc).__name__
    else:
        text_status = result.status
        if result.credit_grade is not None:
            text_grade = result.credit_grade.value
            text_grade_conf = result.credit_grade.confidence
        if result.credit_evaluated_on is not None:
            text_date = result.credit_evaluated_on.value
            text_date_conf = result.credit_evaluated_on.confidence
    text_ms = f"{(time.perf_counter() - started) * 1000.0:.2f}"

    ocr_attempted = False
    ocr_status = ocr_grade = ocr_grade_conf = ocr_date = ocr_date_conf = ""
    ocr_ms = ""
    # 라우터의 _extract 와 같습니다. 검증 실패(거부)면 그 자리에서 끝나고 OCR 을
    # 부르지 않으므로, 거부 표본에는 OCR 경로를 태우지 않습니다.
    scanner_result = None
    if text_status == STATUS_UNRECOGNIZED:
        ocr_attempted = True
        started = time.perf_counter()
        try:
            scanner_result = ocr.extract_scanned_certificate(data)
        except Exception as exc:
            ocr_status = f"error:{type(exc).__name__}"
        else:
            if scanner_result is None:
                ocr_status = "skipped"
            else:
                ocr_status = scanner_result.status
                if scanner_result.credit_grade is not None:
                    ocr_grade = scanner_result.credit_grade.value
                    ocr_grade_conf = scanner_result.credit_grade.confidence
                if scanner_result.credit_evaluated_on is not None:
                    ocr_date = scanner_result.credit_evaluated_on.value
                    ocr_date_conf = scanner_result.credit_evaluated_on.confidence
        ocr_ms = f"{(time.perf_counter() - started) * 1000.0:.2f}"

    if text_status == STATUS_EXTRACTED:
        final_path = PATH_TEXT
    elif scanner_result is not None:
        final_path = PATH_OCR
    else:
        final_path = PATH_NONE

    if text_status == STATUS_REJECTED:
        final_status = STATUS_REJECTED
        final_grade = final_date = ""
    elif final_path == PATH_TEXT:
        final_status = text_status
        final_grade, final_date = text_grade, text_date
    elif final_path == PATH_OCR:
        final_status = ocr_status
        final_grade, final_date = ocr_grade, ocr_date
    else:
        final_status = text_status
        final_grade, final_date = text_grade, text_date

    return Row(
        sample_id=case.sample_id,
        source_file=case.source_file,
        kind=case.kind,
        pages=pages,
        size_bytes=len(data),
        text_status=text_status,
        text_reject=text_reject,
        text_grade=text_grade,
        text_grade_conf=text_grade_conf,
        text_date=text_date,
        text_date_conf=text_date_conf,
        text_ms=text_ms,
        ocr_attempted="yes" if ocr_attempted else "no",
        ocr_status=ocr_status,
        ocr_grade=ocr_grade,
        ocr_grade_conf=ocr_grade_conf,
        ocr_date=ocr_date,
        ocr_date_conf=ocr_date_conf,
        ocr_ms=ocr_ms,
        final_path=final_path,
        final_status=final_status,
        final_grade=final_grade,
        final_date=final_date,
    )


def discover_cases(samples_dir: Path) -> tuple[list[Case], list[str]]:
    """디렉터리에서 실측 대상을 찾고 합성 스캔을 준비합니다. 건너뛴 사유도 돌려줍니다."""
    scans_dir = samples_dir / SCANS_DIR_NAME
    scans_dir.mkdir(parents=True, exist_ok=True)
    cases: list[Case] = []
    skipped: list[str] = []

    entries = sorted(path for path in samples_dir.iterdir() if path.is_file())
    for path in entries:
        suffix = path.suffix.lower()
        if suffix in PDF_SUFFIXES:
            data = path.read_bytes()
            try:
                pages = _pdf_page_count(data)
                has_text = _has_text_layer(data)
            except Exception as exc:
                cases.append(Case(path.stem, KIND_TEXT, path.name, path))
                skipped.append(
                    f"{path.name}: 열기 실패({type(exc).__name__}) - 텍스트 표본으로 판정"
                )
                continue
            if not has_text:
                cases.append(Case(path.stem, KIND_SCAN, path.name, path))
                continue
            cases.append(Case(path.stem, KIND_TEXT, path.name, path))
            if pages > MAX_SAMPLE_PAGES:
                skipped.append(f"{path.name}: {pages}쪽 - 쪽수 상한 초과로 스캔 합성 생략")
                continue
            scan_path = scans_dir / f"{path.stem}_scan.pdf"
            try:
                scan_path.write_bytes(_render_scan_pdf(data))
            except Exception as exc:
                skipped.append(f"{path.name}: 스캔 합성 실패({type(exc).__name__})")
                continue
            cases.append(
                Case(
                    f"{path.stem}__scan", KIND_SCAN, f"{SCANS_DIR_NAME}/{scan_path.name}", scan_path
                )
            )
        elif suffix in IMAGE_SUFFIXES:
            pdf_path = scans_dir / f"{path.stem}_image.pdf"
            try:
                pdf_path.write_bytes(_image_to_pdf(path))
            except Exception as exc:
                skipped.append(f"{path.name}: 이미지 변환 실패({type(exc).__name__})")
                continue
            cases.append(
                Case(
                    f"{path.stem}__image", KIND_IMAGE, f"{SCANS_DIR_NAME}/{pdf_path.name}", pdf_path
                )
            )
    return cases, skipped


def write_result_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(asdict(row)[key]) for key in RESULT_FIELDS})


def read_result_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_answers_csv(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["sample_id"]: dict(row) for row in csv.DictReader(handle)}


def _classify(grade: str, date: str, expected_grade: str, expected_date: str) -> tuple[str, str]:
    """등급·평가일 각각을 적중/미추출/오추출로 나눕니다."""
    if not expected_grade and not expected_date:
        return "-", "-"
    if grade == "":
        grade_verdict = "miss"
    elif grade == expected_grade:
        grade_verdict = "hit"
    else:
        grade_verdict = "wrong"
    if date == "":
        date_verdict = "miss"
    elif date == expected_date:
        date_verdict = "hit"
    else:
        date_verdict = "wrong"
    return grade_verdict, date_verdict


def _path_stats(
    rows: list[dict[str, str]],
    answers: dict[str, dict[str, str]],
    path: str,
    *,
    select,
) -> dict[str, int]:
    stats = {
        "attempted": 0,
        "extracted": 0,
        "grade_hit": 0,
        "grade_miss": 0,
        "grade_wrong": 0,
        "date_hit": 0,
        "date_miss": 0,
        "date_wrong": 0,
        "false_positive": 0,
        "rejected_ok": 0,
        "rejected_bad": 0,
        "cert_total": 0,
    }
    for row in rows:
        answer = answers.get(row["sample_id"])
        if answer is None or not select(row):
            continue
        stats["attempted"] += 1
        expect = answer.get("expect_status", "")
        if expect == EXPECT_REJECTED:
            stats[
                "rejected_ok" if row[f"{path}_status"] == STATUS_REJECTED else "rejected_bad"
            ] += 1
            continue
        status = row[f"{path}_status"]
        grade = row[f"{path}_grade"]
        date = row[f"{path}_date"]
        extracted = status == STATUS_EXTRACTED
        if extracted:
            stats["extracted"] += 1
        if expect == EXPECT_UNRECOGNIZED:
            if extracted:
                stats["false_positive"] += 1
            continue
        stats["cert_total"] += 1
        grade_verdict, date_verdict = _classify(
            grade, date, answer.get("expected_grade", ""), answer.get("expected_date", "")
        )
        if grade_verdict != "-":
            stats[f"grade_{grade_verdict}"] += 1
        if date_verdict != "-":
            stats[f"date_{date_verdict}"] += 1
    return stats


def _fmt_rate(hit: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{hit}/{total} ({hit / total * 100:.1f}%)"


def print_score(rows: list[dict[str, str]], answers: dict[str, dict[str, str]]) -> None:
    """경로별 적중 표를 출력합니다. result.csv + answers.csv 로 재계산하는 정본입니다."""
    print("=" * 78)
    print("신용평가등급확인서 PDF 추출 실측 (웹 공개 샘플 참고치, 정식 Z4 아님)")
    print("=" * 78)
    if not answers:
        print("answers.csv 가 없어 적중을 계산하지 못했습니다. 정답 CSV 를 먼저 작성하십시오.")
        return

    cert_rows = [
        r for r in rows if answers.get(r["sample_id"], {}).get("expect_status") == EXPECT_EXTRACTED
    ]
    print(
        f"표본 {len(rows)}건 (확인서 {len(cert_rows)}건, "
        f"비확인서 {sum(1 for r in rows if answers.get(r['sample_id'], {}).get('expect_status') == EXPECT_UNRECOGNIZED)}건, "
        f"정상거부 {sum(1 for r in rows if answers.get(r['sample_id'], {}).get('expect_status') == EXPECT_REJECTED)}건)"
    )
    print()

    header = (
        f"{'경로':<6}{'대상':>5}{'확인서':>7}{'등급적중':>16}{'평가일적중':>16}"
        f"{'등급미추출':>10}{'등급오추출':>10}{'평가일미추출':>12}{'평가일오추출':>12}{'오탐':>6}"
    )
    print(header)
    print("-" * len(header))

    specs = [
        (PATH_TEXT, lambda r: r["text_status"] != STATUS_REJECTED),
        (PATH_OCR, lambda r: r["ocr_attempted"] == "yes"),
        ("final", lambda r: True),
    ]
    printed: dict[str, dict[str, int]] = {}
    for path, select in specs:
        path_key = "final" if path == "final" else path
        stats = _path_stats(rows, answers, path_key, select=select)
        printed[path_key] = stats
        print(
            f"{path:<6}{stats['attempted']:>5}{stats['cert_total']:>7}"
            f"{_fmt_rate(stats['grade_hit'], stats['cert_total']):>16}"
            f"{_fmt_rate(stats['date_hit'], stats['cert_total']):>16}"
            f"{stats['grade_miss']:>10}{stats['grade_wrong']:>10}"
            f"{stats['date_miss']:>12}{stats['date_wrong']:>12}"
            f"{stats['false_positive']:>6}"
        )
    print()
    print(
        "경로: text=텍스트 추출, ocr=OCR 추출, final=API 와 같은 순서의 최종 결과. "
        "확인서=정답이 있는 등급확인서 표본. 오탐=비확인서인데 등급을 만든 경우."
    )
    rejected_ok = printed["final"]["rejected_ok"]
    rejected_bad = printed["final"]["rejected_bad"]
    print(f"검증 거부(쪽수 초과 등, OCR 미실행): 일치 {rejected_ok}건 / 불일치 {rejected_bad}건")
    print()

    print("[종류별 final 결과]")
    kinds = sorted({r["kind"] for r in rows})
    for kind in kinds:
        subset = [r for r in rows if r["kind"] == kind]
        pull = sum(1 for r in subset if answers.get(r["sample_id"]) is not None)
        print(f"  - {kind:<6} 표본 {len(subset):>2}건 (정답 대조 {pull}건)")


def run(samples_dir: Path, result_path: Path) -> int:
    if not samples_dir.is_dir():
        print(f"[실패] 표본 디렉터리가 없습니다: {samples_dir}", file=sys.stderr)
        return 1

    ocr_available = True
    try:
        ocr.verify_model_files(settings.DOCUMENT_OCR_MODEL_DIR)
    except ocr.OcrUnavailableError as exc:
        ocr_available = False
        print(f"[경고] OCR 모델을 쓸 수 없어 OCR 경로가 건너뜁니다: {exc}", file=sys.stderr)

    cases, skipped = discover_cases(samples_dir)
    print(f"실측 대상 {len(cases)}건 (OCR 모델 사용 가능: {ocr_available})")
    for note in skipped:
        print(f"  건너뜀 - {note}")

    rows: list[Row] = []
    for index, case in enumerate(cases, start=1):
        row = _run_case(case)
        rows.append(row)
        print(
            f"  [{index:>2}/{len(cases)}] {row.sample_id:<38} kind={row.kind:<5} "
            f"final={row.final_path:<4} {row.final_status:<12} "
            f"grade={row.final_grade or '-':<5} date={row.final_date or '-'}"
        )

    write_result_csv(rows, result_path)
    print(f"결과 저장: {result_path}")
    print()
    print_score(read_result_csv(result_path), read_answers_csv(result_path.parent / ANSWERS_NAME))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="웹 공개 신용평가등급확인서 샘플 추출 실측")
    parser.add_argument(
        "--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR, help="표본 디렉터리"
    )
    parser.add_argument("--result", type=Path, default=None, help="결과 CSV 경로")
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="실측을 다시 돌리지 않고 result.csv + answers.csv 만으로 적중을 재계산합니다",
    )
    args = parser.parse_args(argv)

    result_path = args.result or (args.samples_dir / RESULT_NAME)
    if args.score_only:
        if not result_path.is_file():
            print(f"[실패] 결과 CSV 가 없습니다: {result_path}", file=sys.stderr)
            return 1
        print_score(
            read_result_csv(result_path), read_answers_csv(result_path.parent / ANSWERS_NAME)
        )
        return 0
    return run(args.samples_dir, result_path)


if __name__ == "__main__":
    raise SystemExit(main())
