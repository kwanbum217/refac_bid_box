"""
tests/test_backup_recovery_core_safety.py

scripts/backup_recovery_core.py 의 복원 안전성 회귀 테스트.

1) extract_tar_archive 가 형제 디렉터리 접두사(../<base>_evil)로 탈출하는 멤버와
   대상 밖을 가리키는 심볼릭·하드 링크 멤버를 거부하는지 확인합니다.
2) query_db_row_counts 가 특수문자 비밀번호를 가진 DB URL 을 손실 없이 조립하는지
   확인합니다.
실제 DB 접속이나 운영 데이터 변경은 일절 수행하지 않습니다.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from scripts.backup_recovery_core import extract_tar_archive, query_db_row_counts


def _add_file(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _add_symlink(tar: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    tar.addfile(info)


def _add_hardlink(tar: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE
    info.linkname = linkname
    tar.addfile(info)


def test_extract_rejects_sibling_directory_prefix_member(tmp_path: Path):
    """../<base>_evil 로 탈출하는 멤버는 startswith 접두사 일치로 통과하면 안 됩니다."""
    base = tmp_path / "target"
    base.mkdir()
    archive = tmp_path / "evil_member.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_file(tar, "../target_evil/pwned.txt", b"pwned")

    with pytest.raises(ValueError, match="안전하지 않은 아카이브 경로"):
        extract_tar_archive(archive, base)

    assert not (tmp_path / "target_evil" / "pwned.txt").exists()


def test_extract_rejects_symlink_pointing_outside(tmp_path: Path):
    """대상 밖(../../)을 가리키는 심볼릭 링크 멤버를 거부합니다."""
    base = tmp_path / "target"
    base.mkdir()
    archive = tmp_path / "evil_symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_symlink(tar, "escape", "../../outside_secret")

    with pytest.raises(ValueError, match="안전하지 않은 링크 대상"):
        extract_tar_archive(archive, base)


def test_extract_rejects_absolute_symlink_target(tmp_path: Path):
    """절대 경로를 가리키는 심볼릭 링크 멤버를 거부합니다."""
    base = tmp_path / "target"
    base.mkdir()
    archive = tmp_path / "abs_symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_symlink(tar, "etc_link", "/etc/passwd")

    with pytest.raises(ValueError, match="안전하지 않은 링크 대상"):
        extract_tar_archive(archive, base)


def test_extract_rejects_hardlink_pointing_outside(tmp_path: Path):
    """대상 밖을 가리키는 하드 링크 멤버를 거부합니다."""
    base = tmp_path / "target"
    base.mkdir()
    archive = tmp_path / "evil_hardlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_hardlink(tar, "hard.txt", "../outside_secret.txt")

    with pytest.raises(ValueError, match="안전하지 않은 링크 대상"):
        extract_tar_archive(archive, base)


def test_extract_allows_safe_member_and_inner_symlink(tmp_path: Path):
    """정상 멤버와 대상 안쪽을 가리키는 심볼릭 링크는 그대로 추출합니다."""
    base = tmp_path / "target"
    base.mkdir()
    archive = tmp_path / "safe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_file(tar, "sub/file.txt", b"hello")
        _add_symlink(tar, "inner_link", "sub/file.txt")

    extract_tar_archive(archive, base)

    assert (base / "sub" / "file.txt").read_bytes() == b"hello"


def test_query_db_row_counts_escapes_special_character_password(monkeypatch):
    """비밀번호의 @ : / # 이 있어도 URL 로 조립했다가 다시 파싱하면 원문과 같아야 합니다."""
    password = "p@ss:w/rd#1"  # noqa: S105 # 특수문자 URL 조립 검증용 더미 비밀번호
    captured: dict[str, object] = {}

    class _FakeEngine:
        def __init__(self, url: object) -> None:
            self.url = url

        def connect(self) -> None:
            raise RuntimeError("no database in test")

    def fake_create_engine(url: object, **kwargs: object) -> _FakeEngine:
        captured["url"] = url
        return _FakeEngine(url)

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)

    result = query_db_row_counts(
        {
            "host": "db.local",
            "port": 3306,
            "user": "admin",
            "password": password,
            "name": "procurement",
        }
    )

    url = captured["url"]
    assert url.username == "admin"
    assert url.host == "db.local"
    assert url.port == 3306
    assert url.database == "procurement"
    assert url.password == password
    rendered = url.render_as_string(hide_password=False)
    assert make_url(rendered).password == password
    assert make_url(rendered).host == "db.local"
    assert all(value is None for value in result.values())


def test_query_db_row_counts_url_is_accepted_by_create_engine(monkeypatch):
    """URL 객체가 create_engine 에 그대로 전달되어 파싱 오류 없이 받아들여지고, 비밀번호가 보존됩니다."""
    from sqlalchemy import create_engine as real_create_engine

    password = "p@ss:w/rd#1"  # noqa: S105 # 특수문자 URL 조립 검증용 더미 비밀번호
    captured: dict[str, object] = {}

    def spy_create_engine(url: object, **kwargs: object) -> object:
        captured["engine"] = real_create_engine(
            url, **kwargs
        )  # f-string URL 이면 여기서 파싱 오류가 난다
        raise RuntimeError("stop before connecting")

    monkeypatch.setattr("sqlalchemy.create_engine", spy_create_engine)

    result = query_db_row_counts(
        {
            "host": "db.local",
            "port": 3306,
            "user": "admin",
            "password": password,
            "name": "procurement",
        }
    )

    engine = captured["engine"]
    assert engine.url.password == password
    assert engine.url.host == "db.local"
    assert all(value is None for value in result.values())
