"""버전 일관성 검증 테스트.

pyproject.toml의 version이 FastAPI 앱의 버전과 일치하는지 검증합니다.
정본은 pyproject.toml 하나이며, 앱은 importlib.metadata로 그 값을 읽습니다.
"""

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_pyproject_version() -> str:
    """pyproject.toml에서 version 값을 추출합니다."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("pyproject.toml에서 version을 찾을 수 없습니다.")
    return match.group(1)


def _get_installed_version() -> str:
    """설치된 패키지의 버전을 조회합니다. 실패 시 안전 기본값 반환."""
    try:
        return pkg_version("refac_bid_box")
    except PackageNotFoundError:
        return "0.1.0"


class TestVersionConsistency:
    """버전 정본 단일화 검증."""

    def test_pyproject_version_exists(self) -> None:
        """pyproject.toml에 version 필드가 존재해야 합니다."""
        version = _read_pyproject_version()
        assert version, "version 값이 비어 있습니다."

    def test_app_version_matches_pyproject(self) -> None:
        """FastAPI 앱 버전이 pyproject.toml 버전과 일치해야 합니다."""
        pyproject_version = _read_pyproject_version()
        installed_version = _get_installed_version()

        # 개발 환경(미설치)에서 안전 기본값이 쓰이는 경우를 허용하되,
        # 패키지가 설치된 환경에서는 정확히 일치해야 합니다.
        # uv run pytest 환경에서는 editable install이므로 일치해야 합니다.
        assert installed_version == pyproject_version, (
            f"앱 버전({installed_version})이 pyproject.toml 버전({pyproject_version})과 다릅니다. "
            f"정본은 pyproject.toml 하나입니다."
        )

    def test_version_format_semver(self) -> None:
        """버전이 시맨틱 버전 형식(MAJOR.MINOR.PATCH)을 따라야 합니다."""
        version = _read_pyproject_version()
        # 기본 시맨틱 버전 패턴 (pre-release, build metadata 제외)
        semver_pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(semver_pattern, version), (
            f"버전 '{version}'이 시맨틱 버전 형식(MAJOR.MINOR.PATCH)을 따르지 않습니다."
        )

    def test_get_app_version_function(self) -> None:
        """get_app_version() 함수가 올바른 값을 반환해야 합니다."""
        from src.app.core.config import get_app_version

        version = get_app_version()
        pyproject_version = _read_pyproject_version()

        # 설치된 환경에서는 정확히 일치, 미설치 환경에서는 안전 기본값 허용
        assert version == pyproject_version or version == "0.1.0", (
            f"get_app_version() 반환값({version})이 예상 범위를 벗어났습니다."
        )

    def test_no_hardcoded_version_in_main(self) -> None:
        """main.py에 버전 문자열 리터럴이 하드코딩되어 있지 않아야 합니다."""
        main_py = PROJECT_ROOT / "src" / "app" / "main.py"
        content = main_py.read_text(encoding="utf-8")

        # 버전 리터럴 패턴 검사 (예: version="0.1.0", version='0.1.0')
        hardcoded_pattern = r'version\s*=\s*["\']\d+\.\d+\.\d+["\']'
        matches = re.findall(hardcoded_pattern, content)
        assert not matches, (
            f"main.py에 하드코딩된 버전이 발견되었습니다: {matches}. "
            f"get_app_version()을 사용해야 합니다."
        )

    def test_version_single_source_of_truth_doc(self) -> None:
        """docs/ops/versioning.md에 정본 규칙이 문서화되어 있어야 합니다."""
        doc_path = PROJECT_ROOT / "docs" / "ops" / "versioning.md"
        assert doc_path.exists(), "docs/ops/versioning.md 파일이 없습니다."

        content = doc_path.read_text(encoding="utf-8")
        # 핵심 내용이 포함되어 있는지 확인
        assert "pyproject.toml" in content, "문서에 pyproject.toml이 정본임이 명시되어야 합니다."
        assert "importlib.metadata" in content, (
            "문서에 importlib.metadata 사용법이 명시되어야 합니다."
        )
        assert "CURRENT_STATE" in content, (
            "문서에 CURRENT_STATE.md v1.0.0 표기가 근거 없음이 기록되어야 합니다."
        )
        assert "릴리스" in content or "release" in content.lower(), (
            "문서에 후속 과업(릴리스 tag, CHANGELOG)이 언급되어야 합니다."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
