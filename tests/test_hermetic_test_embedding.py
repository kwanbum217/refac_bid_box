"""테스트 임베딩 격리 회귀 테스트.

테스트가 chromadb 기본 임베딩(ONNX all-MiniLM-L6-v2)을 실제로 내려받아 쓰면
네트워크와 로컬 캐시(~/.cache/chroma)에 의존하게 됩니다. 그래서 캐시가 있는
로컬은 조용히 통과하고, 캐시가 없는 CI 에서만 모델 다운로드와 함께
tar.extractall DeprecationWarning 이 발생했습니다(2026-09-22 경고 예산 잡).

conftest 의 결정적 가짜 임베딩이 그 경로를 막고 있음을 여기서 고정합니다.
가짜 임베딩은 의미적 유사도가 없으므로 검색 순위나 거리 값을 단언하지 않습니다.
"""

from __future__ import annotations

import chromadb

from src.rag import embeddings


def _forbid_onnx(monkeypatch):
    """ONNX MiniLM 의 추론과 다운로드를 실패시킵니다.

    호출되면 AssertionError 로 테스트를 깨뜨려, 격리가 풀린 사실이 조용히
    지나가지 않게 합니다.
    """
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

    def forbidden(*_args, **_kwargs):
        raise AssertionError("테스트가 chromadb 기본 ONNX MiniLM 임베딩을 호출했습니다")

    monkeypatch.setattr(ONNXMiniLM_L6_V2, "__call__", forbidden)
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "_download_model_if_not_exists", forbidden)
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "_download", forbidden)


def test_adding_documents_never_invokes_onnx_mini_lm(monkeypatch, tmp_path):
    """get_collection 으로 연 컬렉션에 add/upsert/query 해도 ONNX 가 호출되지 않습니다.

    conftest 의 autouse fixture 가 chromadb 가 기본값으로 끼워 넣는 임베딩 함수를
    결정적 가짜로 바꾸므로, ONNX 를 실패하게 둔 채로도 색인과 질의가 끝나야 합니다.

    EphemeralClient 는 프로세스 전역 시스템을 공유해 다른 테스트의 설정과 충돌하므로
    tmp_path 의 PersistentClient 를 씁니다. 운영 색인 경로와 같은 클라이언트입니다.
    """
    _forbid_onnx(monkeypatch)
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "default")
    # 되돌리기 분기 자체는 그대로다. 가짜는 컬렉션에 붙는 기본값만 대체한다.
    assert embeddings.get_embedding_function() is None

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = embeddings.get_collection(client, "hermetic_embedding_test", create=True)

    collection.add(ids=["a", "b"], documents=["공고 문서", "낙찰 결과"])
    collection.upsert(ids=["c"], documents=["추가 문서"])
    result = collection.query(query_texts=["공고 문서"], n_results=1)

    assert collection.count() == 3
    assert result["ids"][0]


def test_deterministic_embedding_returns_same_vector_for_same_input(
    deterministic_embedding_function,
):
    """같은 문자열에는 항상 같은 벡터를 줍니다."""
    function = deterministic_embedding_function

    first = function(["같은 문서", "다른 문서"])
    second = function(["같은 문서", "다른 문서"])

    assert first == second
    assert first[0] == function(["같은 문서"])[0]
    assert first[0] != first[1]


def test_deterministic_embedding_has_fixed_dimension(deterministic_embedding_function):
    """입력 길이나 개수와 무관하게 벡터 차원이 고정입니다."""
    function = deterministic_embedding_function

    vectors = function(["가", "나" * 5000, ""])

    assert {len(vector) for vector in vectors} == {function.dimension}
    assert all(isinstance(value, float) for vector in vectors for value in vector)


def test_deterministic_embedding_matches_chromadb_protocol(deterministic_embedding_function):
    """chromadb 가 요구하는 EmbeddingFunction 시그니처를 만족합니다."""
    from chromadb.api.types import validate_embedding_function

    validate_embedding_function(deterministic_embedding_function)
