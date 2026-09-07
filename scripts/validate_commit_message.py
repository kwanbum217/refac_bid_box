#!/usr/bin/env python3
"""
scripts/validate_commit_message.py

커밋 메시지 제목 규약 검증 스크립트.
- 형식: <type>: <subject>
- type: feat, fix, docs, refactor, chore, test, ci, merge (영어 소문자)
- subject: 한국어 필수 (U+AC00~U+D7A3 한글 음절 최소 1자 포함)
- 이모지 사용 금지 (AGENTS.md 7장 1번 조항)
- 면제 대상:
  - 'Merge branch' 또는 'Merge remote-tracking' 으로 시작하는 git 자동 생성 병합 커밋
  - 'Revert "' 로 시작하는 되돌리기 커밋
  - 'fixup!' 또는 'squash!' 로 시작하는 커밋
- 제목 줄만 검사하며 본문/트레일러는 검사 대상에서 제외됩니다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ALLOWED_TYPES: set[str] = {
    "feat",
    "fix",
    "docs",
    "refactor",
    "chore",
    "test",
    "ci",
    "merge",
}

EXEMPT_PREFIXES: tuple[str, ...] = (
    "Merge branch",
    "Merge remote-tracking",
    'Revert "',
    "fixup!",
    "squash!",
)

EMOJI_PATTERN = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map symbols
    "\U0001f700-\U0001f77f"  # alchemical symbols
    "\U0001f780-\U0001f7ff"  # geometric shapes extended
    "\U0001f800-\U0001f8ff"  # supplemental arrows-c
    "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols and pictographs extended-a
    "\U00002600-\U000027bf"  # misc symbols & dingbats (✨, ⚡, ⚠️, ✅, ❌ 등)
    "\U00002b50-\U00002b55"  # stars, circles
    "\U0000231a-\U0000231b"  # watch, hourglass
    "\U000023e9-\U000023ec"  # fast forward, rewind
    "\U000023f0-\U000023f3"  # alarm clock, timer
    "\U000023f8-\U000023fa"  # pause, stop, record
    "\U000025aa-\U000025ab"  # small squares
    "\U000025fb-\U000025fe"  # medium boxes
    "\U00002934-\U00002935"  # curved arrows
    "\U0000fe0e-\U0000fe0f"  # variation selectors
    "]"
)

CORRECT_EXAMPLES: list[str] = [
    "feat: 사용자 인증 API 추가",
    "fix: 낙찰가 예측 모델 로딩 오류 수정",
    "docs: Git 브랜칭 전략 문서 업데이트",
    "refactor: 추론 파이프라인 구조 개선",
    "chore: 의존성 패키지 버전 업데이트",
    "test: 커밋 메시지 검사기 단위 테스트 추가",
    "ci: 워크플로우 테스트 파이프라인 설정",
    "merge: 작업 브랜치 병합",
]


def contains_emoji(text: str) -> bool:
    """텍스트 내 이모지 포함 여부를 확인합니다."""
    return bool(EMOJI_PATTERN.search(text))


def extract_subject(raw_message: str) -> str:
    """커밋 메시지 원문에서 첫 번째 비주석, 비공백 제목 줄을 추출합니다."""
    for line in raw_message.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped:
            return stripped
    return ""


def validate_commit_subject(subject: str) -> tuple[bool, str]:
    """커밋 메시지 제목 한 줄을 규약에 따라 검증합니다."""
    subject_cleaned = subject.strip()
    if not subject_cleaned:
        return False, "커밋 제목이 비어 있습니다."

    if subject_cleaned.startswith(EXEMPT_PREFIXES):
        return True, "검사 면제 대상 커밋"

    if contains_emoji(subject_cleaned):
        return False, "커밋 제목에 이모지가 포함되어 있습니다. (AGENTS.md 7장 1번 조항 위반)"

    if ":" not in subject:
        return False, "커밋 제목 형식은 '<type>: <subject>' 이어야 합니다. (콜론 누락)"

    prefix, _sep, rest = subject.partition(":")
    commit_type = prefix.strip()
    if not commit_type:
        return False, "커밋 타입이 누락되었습니다. 형식: '<type>: <subject>'"

    if not rest.startswith(" "):
        return False, "타입 콜론(:) 뒤에 공백이 필요합니다. 형식: '<type>: <subject>'"

    commit_subject = rest.strip()
    if not commit_subject:
        return False, "커밋 제목의 subject 내용이 비어 있습니다."

    if commit_type != commit_type.lower() or not commit_type.isalpha():
        return False, f"커밋 타입은 영어 소문자 알파벳이어야 합니다: '{commit_type}'"

    if commit_type not in ALLOWED_TYPES:
        return False, (
            f"허용되지 않은 커밋 타입입니다: '{commit_type}'. "
            f"허용 목록: {', '.join(sorted(ALLOWED_TYPES))}"
        )

    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in commit_subject)
    if not has_hangul:
        return False, (
            "커밋 제목의 subject에 한국어가 포함되어야 합니다. "
            "(한글 음절 U+AC00~U+D7A3 최소 1자 필요)"
        )

    return True, "정상"


def validate_commit_message(raw_message: str) -> tuple[bool, str]:
    """커밋 메시지 전체에서 제목 줄을 추출하여 검증합니다. 본문/트레일러는 무시합니다."""
    subject = extract_subject(raw_message)
    if not subject:
        return False, "커밋 메시지 제목이 비어 있습니다."
    return validate_commit_subject(subject)


def format_failure_message(subject: str, reason: str) -> str:
    """규약 위반 시 사유와 올바른 예시를 한국어로 정형화하여 반환합니다."""
    examples_str = "\n".join(f"  - {ex}" for ex in CORRECT_EXAMPLES)
    return (
        f"[오류] 커밋 메시지 규약 위반: {reason}\n"
        f"입력된 제목: {subject or '(비어 있음)'}\n\n"
        f"올바른 형식: <type>: <subject>\n"
        f"  - type: 영어 소문자 ({', '.join(sorted(ALLOWED_TYPES))})\n"
        f"  - subject: 한국어 필수 (한글 음절 U+AC00~U+D7A3 최소 1자 포함, 이모지 금지)\n\n"
        f"올바른 예시:\n{examples_str}\n"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="커밋 메시지 제목 한국어 규약 검증 스크립트",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="검증할 커밋 메시지 파일 경로 (Git commit-msg 훅 전달)",
    )
    parser.add_argument(
        "-m",
        "--message",
        default=None,
        help="직접 검증할 커밋 메시지 문자열",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """검사기 진입점 함수."""
    args = parse_args(argv)

    if args.message is not None:
        raw_text = args.message
    elif args.file is not None:
        file_path = Path(args.file)
        if not file_path.exists():
            sys.stderr.write(f"[오류] 커밋 메시지 파일을 찾을 수 없습니다: {file_path}\n")
            return 1
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = file_path.read_text(encoding="cp949")
            except Exception as exc:
                sys.stderr.write(f"[오류] 커밋 메시지 파일 인코딩 오류: {exc}\n")
                return 1
    else:
        sys.stderr.write("[오류] 검증할 커밋 메시지 파일 경로 또는 --message 옵션이 필요합니다.\n")
        return 1

    ok, reason = validate_commit_message(raw_text)
    if not ok:
        subject = extract_subject(raw_text)
        sys.stderr.write(format_failure_message(subject, reason))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
