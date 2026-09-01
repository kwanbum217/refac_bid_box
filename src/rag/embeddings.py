"""
src/rag/embeddings.py

ChromaDB 임베딩 함수의 단일 진입점.

**색인과 질의는 반드시 같은 함수를 써야 합니다.** 컬렉션을 만들 때와 조회할 때
서로 다른 임베딩을 쓰면 예외 하나 없이 검색 결과만 엉망이 됩니다. 그래서
`kb_builder` 와 `vector_store` 가 모두 이 모듈의 `get_embedding_function()` 만
호출하도록 통일했습니다.

기본값을 bge-m3 로 바꾼 근거 (2026-08-06 실측, 동일 문서 1만 건·동일 질의 100건)

| 지표 | ONNXMiniLM_L6_V2 | bge-m3 |
| --- | --- | --- |
| top-5 적중률 | 4.0% | 100.0% |
| 정답 순위 중앙값 | 9 | 1 |
| 문서 간 유사도 0.9 이상 | 60.5% | 0.1% |
| 1만 건 적재 | 345.5초 | 213.6초 |

기존 기본 모델(all-MiniLM-L6-v2)은 영어 전용이라 한국어에서 의미를 구분하지
못합니다. 같은 모델에 무관한 주제를 넣어보면 영어는 0.13~0.31 로 떨어지는데
한국어는 0.81~0.83 으로 붙습니다. 벡터가 의미가 아니라 "한국어 텍스트"라는
공통 신호에 지배됩니다.

bge-m3 는 Ollama 가 Metal GPU 로 돌려서 파라미터가 25배 큰데도 더 빠릅니다.
새 파이썬 의존성은 없습니다(httpx 는 이미 사용 중).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64
EMBED_TIMEOUT_SECONDS = 300.0


class OllamaEmbeddingFunction:
    """Ollama `/api/embed` 어댑터.

    ChromaDB 0.6.x 의 EmbeddingFunction 규약은 `__call__(self, input)` 과
    `name()` 입니다. 인자 이름이 `input` 이어야 하므로 셰도잉을 감수합니다.
    """

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.url = f"{base_url.rstrip('/')}/api/embed"
        self._client: Any = None
        self._client_lock = threading.Lock()

    def name(self) -> str:
        # 컬렉션 메타데이터에 남아 나중에 무엇으로 색인했는지 알 수 있습니다.
        return f"ollama-{self.model}"

    def _get_client(self) -> Any:
        """연결을 재사용하는 httpx 클라이언트를 돌려줍니다.

        호출마다 클라이언트를 새로 만들면 질의마다 TCP 연결을 다시 엽니다.
        2026-09-01 컨테이너 실측에서 새 클라이언트 45~52ms 대 재사용 39~41ms 로
        약 12% 차이가 났습니다. 반환 벡터는 완전히 동일합니다.

        ChromaDB 가 임베딩 함수를 여러 스레드에서 부를 수 있으므로 생성만
        잠급니다. httpx.Client 자체는 스레드 안전합니다.
        """
        client = self._client
        if client is not None:
            return client
        with self._client_lock:
            if self._client is None:
                import httpx

                self._client = httpx.Client(timeout=EMBED_TIMEOUT_SECONDS)
            return self._client

    def __call__(self, input: list[str]) -> list[list[float]]:
        client = self._get_client()
        vectors: list[list[float]] = []
        for start in range(0, len(input), EMBED_BATCH_SIZE):
            batch = input[start : start + EMBED_BATCH_SIZE]
            response = client.post(self.url, json={"model": self.model, "input": batch})
            response.raise_for_status()
            vectors.extend(response.json()["embeddings"])
        return vectors

    def close(self) -> None:
        """보유한 클라이언트를 닫습니다. 재호출하면 새로 만듭니다."""
        with self._client_lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()


def get_embedding_function() -> Any:
    """설정에 따른 임베딩 함수를 돌려줍니다.

    `EMBEDDING_PROVIDER=default` 면 ChromaDB 기본값(영어 전용 MiniLM)을 씁니다.
    한국어 검색 품질이 떨어지므로 되돌리기 용도로만 두었습니다.
    """
    provider = (settings.EMBEDDING_PROVIDER or "ollama").strip().lower()
    if provider == "default":
        return None
    if provider != "ollama":
        logger.warning("알 수 없는 EMBEDDING_PROVIDER=%s, ollama 로 처리합니다", provider)
    return OllamaEmbeddingFunction(settings.EMBEDDING_MODEL, settings.OLLAMA_BASE_URL)


def get_collection(client: Any, name: str, *, create: bool = False) -> Any:
    """임베딩 함수를 붙여 컬렉션을 엽니다.

    `client.get_collection(name)` 을 그냥 부르면 ChromaDB 가 기본 임베딩 함수를
    끼워 넣습니다. 색인은 bge-m3 로 해 놓고 질의만 MiniLM 으로 하게 되며,
    실패가 아니라 **엉뚱한 결과**로 나타나 알아차리기 어렵습니다.
    """
    embedding_function = get_embedding_function()
    kwargs = {"name": name}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    if create:
        return client.get_or_create_collection(**kwargs)
    return client.get_collection(**kwargs)
