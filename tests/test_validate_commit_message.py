from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_commit_message import (
    contains_emoji,
    extract_subject,
    validate_commit_message,
    validate_commit_subject,
)


@pytest.mark.parametrize(
    "subject",
    [
        "feat: 사용자 인증 API 추가",
        "fix: 낙찰가 예측 모델 로딩 오류 수정",
        "docs: Git 브랜칭 전략 문서 업데이트",
        "refactor: 추론 파이프라인 구조 개선",
        "chore: 의존성 패키지 버전 업데이트",
        "test: 커밋 메시지 검사기 단위 테스트 추가",
        "ci: 워크플로우 테스트 파이프라인 설정",
        "merge: 작업 브랜치 병합",
        "feat: FastAPI 엔드포인트 및 Pydantic v2 스키마 연동",
        "fix: MySQL 8 커넥션 타임아웃 30s 설정",
    ],
)
def test_validate_commit_subject_success(subject: str):
    ok, reason = validate_commit_subject(subject)
    assert ok is True
    assert reason == "정상"


@pytest.mark.parametrize(
    "exempt_msg",
    [
        "Merge branch 'feature/retraining' into main",
        "Merge branch 'hotfix/db' of github.com:kwanbum217/refac_bid_box",
        "Merge remote-tracking branch 'origin/main'",
        'Revert "feat: 사용자 인증 API 추가"',
        "fixup! feat: 사용자 인증 API 추가",
        "squash! feat: 사용자 인증 API 추가",
    ],
)
def test_validate_commit_subject_exemptions(exempt_msg: str):
    ok, reason = validate_commit_subject(exempt_msg)
    assert ok is True
    assert "면제" in reason


def test_validate_commit_message_with_multiline_body_and_trailers():
    raw_msg = """feat: 사용자 인증 API 추가

상세 설명:
- JWT 토큰 기반 사용자 인증 구현
- Refresh token rotation 지원

Co-Authored-By: Other Developer <dev@example.com>
Signed-off-by: Kwanbum <kwanbum@example.com>
"""
    ok, reason = validate_commit_message(raw_msg)
    assert ok is True
    assert reason == "정상"


def test_validate_commit_message_ignores_git_comments():
    raw_msg = """# Please enter the commit message for your changes.
# Lines starting with '#' will be ignored.
feat: 새 기능 추가

# An empty message aborts the commit.
"""
    ok, reason = validate_commit_message(raw_msg)
    assert ok is True
    assert reason == "정상"


@pytest.mark.parametrize(
    ("invalid_subject", "expected_reason_substr"),
    [
        ("feat: add retraining trainer with LightGBM", "한국어"),
        ("fix: verify block signals from rendered screen", "한국어"),
        ("docs: update README.md", "한국어"),
        ("사용자 인증 기능 추가", "콜론 누락"),
        (": 한글 제목", "타입이 누락"),
        ("custom: 사용자 인증 기능 추가", "허용되지 않은"),
        ("FEAT: 사용자 인증 API 추가", "소문자"),
        ("feat:사용자 인증 API 추가", "공백이 필요"),
        ("feat: 사용자 인증 API 추가 🚀", "이모지"),
        ("fix: ✨ 버그 수정", "이모지"),
        ("feat:   ", "내용이 비어"),
        ("", "비어 있습니다"),
    ],
)
def test_validate_commit_subject_rejections(invalid_subject: str, expected_reason_substr: str):
    ok, reason = validate_commit_subject(invalid_subject)
    assert ok is False
    assert expected_reason_substr in reason


def test_contains_emoji():
    assert contains_emoji("feat: 로켓 발사 🚀") is True
    assert contains_emoji("fix: 반짝이는 버그 ✨") is True
    assert contains_emoji("docs: 메모 📝") is True
    assert contains_emoji("ci: 체크 ✅") is True
    assert contains_emoji("feat: 순수 한글 및 English 123 (v1.0.0)") is False


def test_extract_subject():
    assert extract_subject("feat: 첫 줄\n\n둘째 줄") == "feat: 첫 줄"
    assert extract_subject("# 주석\n\nfeat: 실제 제목") == "feat: 실제 제목"
    assert extract_subject("# 전체 주석\n# 두번째 주석") == ""


def test_cli_message_flag_success():
    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_commit_message.py",
            "--message",
            "feat: 한국어 제목으로 정상 통과",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert res.stderr == ""


def test_cli_message_flag_failure():
    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_commit_message.py",
            "--message",
            "fix: verify block signals from rendered screen",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "규약 위반" in res.stderr
    assert "올바른 예시" in res.stderr


def test_cli_file_argument_success(tmp_path: Path):
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text("merge: 작업 브랜치 병합\n\n브랜치 병합 본문\n", encoding="utf-8")
    res = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/validate_commit_message.py", str(msg_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0


def test_cli_file_argument_failure(tmp_path: Path):
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text("chore: update dependencies\n", encoding="utf-8")
    res = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/validate_commit_message.py", str(msg_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "규약 위반" in res.stderr


def test_cli_missing_file():
    res = subprocess.run(
        [
            sys.executable,
            "scripts/validate_commit_message.py",
            "non_existent_file_path.txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "찾을 수 없습니다" in res.stderr


def test_cli_no_arguments():
    res = subprocess.run(
        [sys.executable, "scripts/validate_commit_message.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "필요합니다" in res.stderr
