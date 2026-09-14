"""
tests/test_chroma_embedded_only_guard.py

ChromaDB 구조 가드 테스트.
chromadb 0.6.3 의 CVE allowlist 는 PersistentClient 전용(인프로세스 임베디드 모드)
사용을 전제로 합니다. HTTP 서버/클라이언트 분리 실행이나 trust_remote_code=True 가
코드베이스에 유입되면 CVE allowlist 전제가 깨지므로 이를 구조적으로 차단합니다.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()


def _collect_py_files() -> list[Path]:
    py_files = []
    for d in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
        if d.exists():
            py_files.extend(p for p in d.rglob("*.py") if p.resolve() != THIS_FILE)
    return sorted(py_files)


def _collect_docker_files() -> list[Path]:
    docker_files = []
    docker_files.extend(REPO_ROOT.glob("docker-compose*.yml"))
    docker_files.extend(REPO_ROOT.glob("Dockerfile*"))
    for sub in REPO_ROOT.iterdir():
        if sub.is_dir() and not sub.name.startswith("."):
            docker_files.extend(sub.glob("Dockerfile*"))
            docker_files.extend(sub.glob("docker-compose*.yml"))
    return sorted(set(docker_files))


def test_no_chroma_http_client_in_python_code():
    """(a) chromadb.HttpClient 또는 AsyncHttpClient 사용이 없음을 단언합니다."""
    pattern = re.compile(r"\b(?:chromadb\.)?(?:Async)?HttpClient\b")
    violations = []

    for file_path in _collect_py_files():
        text = file_path.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        if matches:
            rel = file_path.relative_to(REPO_ROOT)
            violations.append(f"{rel}: {set(matches)}")

    assert not violations, (
        f"chromadb CVE allowlist 전제가 깨집니다. "
        f"chromadb 0.6.3 은 인프로세스 PersistentClient 전용이어야 하며 "
        f"HttpClient 또는 AsyncHttpClient 사용이 금지됩니다: {violations}"
    )


def test_no_chroma_run_server_startup_in_python_code():
    """(b) 'chroma run' 서버 기동 문자열이 없음을 단언합니다."""
    target = "chroma run"
    violations = []

    for file_path in _collect_py_files():
        text = file_path.read_text(encoding="utf-8")
        if target in text:
            rel = file_path.relative_to(REPO_ROOT)
            violations.append(str(rel))

    assert not violations, (
        f"chromadb CVE allowlist 전제가 깨집니다. "
        f"ChromaDB 독자 서버 기동('chroma run')이 발견되었습니다: {violations}"
    )


def test_no_trust_remote_code_in_python_code():
    """(c) trust_remote_code=True 가 없음을 단언합니다."""
    pattern = re.compile(r"trust_remote_code\s*=\s*True")
    violations = []

    for file_path in _collect_py_files():
        text = file_path.read_text(encoding="utf-8")
        if pattern.search(text):
            rel = file_path.relative_to(REPO_ROOT)
            violations.append(str(rel))

    assert not violations, (
        f"chromadb CVE allowlist 전제가 깨집니다. "
        f"원격 코드 실행(trust_remote_code=True)이 허용된 코드가 발견되었습니다: {violations}"
    )


def test_no_chroma_server_image_in_docker_configurations():
    """docker-compose*.yml 과 Dockerfile* 에 chroma 서버 이미지(chromadb/chroma) 가 없음도 단언합니다."""
    target = "chromadb/chroma"
    violations = []

    for file_path in _collect_docker_files():
        text = file_path.read_text(encoding="utf-8")
        if target in text:
            rel = file_path.relative_to(REPO_ROOT)
            violations.append(str(rel))

    assert not violations, (
        f"chromadb CVE allowlist 전제가 깨집니다. "
        f"Chroma 서버 컨테이너 이미지({target})가 Docker 설정에 존재합니다: {violations}"
    )
