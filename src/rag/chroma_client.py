"""
src/rag/chroma_client.py

프로세스 단위 ChromaDB 클라이언트와 기본 컬렉션 접근자.

질의와 헬스체크는 요청마다 `chromadb.PersistentClient` 를 새로 열었습니다. 생성
자체가 시스템 초기화 경로를 타므로 질의 지연에 그대로 더해집니다(I-ai F-14).
여기서 한 번만 만들어 재사용하고, 경로나 클라이언트 팩토리가 바뀌면 버립니다.

컬렉션은 반드시 `embeddings.get_collection` 을 거쳐 엽니다. `client.get_collection`
을 그대로 부르면 ChromaDB 가 기본 임베딩 함수를 끼워 넣어 색인(bge-m3)과 질의
임베딩이 달라지고, 예외 없이 결과만 엉뚱해집니다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from src.app.core.config import settings
from src.rag.embeddings import get_collection

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "bidding_kb"

# 색인 전량 재구축은 컬렉션을 지웠다 다시 만들므로 보관하던 핸들이 낡습니다.
# 그때 ChromaDB 가 내는 오류 이름. 시험이 모듈을 대체할 수 있어 이름으로 봅니다.
_MISSING_COLLECTION_ERROR_NAMES = frozenset({"NotFoundError", "InvalidCollectionException"})

_client_lock = threading.Lock()
_collection_lock = threading.Lock()

_client: Any = None
_client_key: tuple[Any, ...] | None = None
_collection: Any = None
_collection_key: tuple[Any, ...] | None = None


def get_chroma_client() -> Any:
    """프로세스에서 하나만 쓰는 ChromaDB 클라이언트를 돌려줍니다."""
    global _client, _client_key, _collection, _collection_key

    import chromadb

    path = str(settings.CHROMA_DB_PATH)
    # 경로가 바뀌거나 시험이 chromadb 모듈·생성자를 갈아 끼우면 다른 클라이언트입니다.
    key = (path, chromadb, chromadb.PersistentClient)
    client = _client
    if client is not None and _client_key == key:
        return client

    with _client_lock:
        if _client is None or _client_key != key:
            logger.debug("ChromaDB 클라이언트 생성 (path=%s)", path)
            _client = chromadb.PersistentClient(path=path)
            _client_key = key
            _collection = None
            _collection_key = None
        return _client


def get_default_collection(
    opener: Callable[[Any, str], Any] | None = None,
) -> Any:
    """기본 컬렉션 핸들을 재사용합니다.

    `opener` 는 컬렉션을 여는 함수를 바꿔 끼우는 자리입니다. 질의 경로는 자기
    모듈의 `get_collection` 을 넘겨, 시험이 그 심을 대체하면 그대로 반영됩니다.
    """
    global _collection, _collection_key

    open_collection = opener or get_collection
    client = get_chroma_client()
    key = (_client_key, DEFAULT_COLLECTION, open_collection)
    collection = _collection
    if collection is not None and _collection_key == key:
        return collection

    with _collection_lock:
        if _collection is None or _collection_key != key:
            _collection = open_collection(client, DEFAULT_COLLECTION)
            _collection_key = key
        return _collection


def reset_chroma_client() -> None:
    """보관한 클라이언트와 컬렉션 핸들을 버립니다. 다음 호출이 새로 엽니다."""
    global _client, _client_key, _collection, _collection_key

    with _collection_lock:
        _collection = None
        _collection_key = None
    with _client_lock:
        _client = None
        _client_key = None


def is_missing_collection_error(exc: BaseException) -> bool:
    """컬렉션 부재 계열 오류인지 판별합니다.

    시험이 `chromadb` 모듈을 대체하므로 예외 클래스를 직접 import 하지 않고 이름으로
    봅니다. 이름이 맞지 않아도 메시지에 컬렉션 부재가 드러나면 같은 오류로 봅니다.
    """
    if any(cls.__name__ in _MISSING_COLLECTION_ERROR_NAMES for cls in type(exc).__mro__):
        return True
    message = str(exc).lower()
    return "collection" in message and ("not found" in message or "does not exist" in message)
