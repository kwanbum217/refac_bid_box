"""KB 검색 적중률 측정.

정답을 아는 질의를 씁니다. 색인된 문서를 시드 고정으로 뽑고, 그 문서의
`공고명 + 수요기관` 을 그대로 질의해 **자기 자신이 상위 몇 번째에 오는지** 셉니다.
정답이 색인 안에 있으므로 상위권에 나오지 않으면 검색이 동작하지 않는 것입니다.

임베딩 교체(2026-08-06, MiniLM -> bge-m3)와 커버리지 확대의 효과를 같은 자로
재려고 스크립트로 고정했습니다. 후보 수가 늘면 순위가 밀리므로 규모를 바꿀
때마다 다시 재야 합니다.

사용법:
    uv run python scripts/measure_kb_retrieval.py
    uv run python scripts/measure_kb_retrieval.py --samples 200 --top-k 10
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

from src.app.core.config import settings
from src.rag.embeddings import get_collection
from src.rag.vector_store import DEFAULT_COLLECTION


def _extract(document: str, field: str) -> str:
    """문서 본문에서 `[필드] 값` 한 줄을 뽑습니다."""
    match = re.search(rf"^\[{re.escape(field)}\] (.+)$", document, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _build_query(document: str) -> str:
    """공고명과 수요기관을 붙여 질의를 만듭니다.

    낙찰 결과 문서에는 공고명이 없어 낙찰업체로 대체합니다. 어느 쪽이든
    사람이 실제로 칠 법한 표현이어야 측정이 의미를 갖습니다.
    """
    title = _extract(document, "공고명") or _extract(document, "낙찰업체")
    institution = _extract(document, "수요기관")
    return " ".join(part for part in (title, institution) if part)


def main() -> int:
    parser = argparse.ArgumentParser(description="KB 검색 적중률 측정")
    parser.add_argument("--samples", type=int, default=100, help="질의 개수")
    parser.add_argument("--top-k", type=int, default=5, help="적중으로 인정할 순위")
    parser.add_argument("--seed", type=int, default=42, help="표본 추출 시드")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
    collection = get_collection(client, args.collection)
    total_indexed = collection.count()
    if total_indexed == 0:
        print("색인이 비어 있습니다.")
        return 1

    all_ids = collection.get(include=[])["ids"]
    # 측정 재현용 표본 추출입니다. 암호 용도가 아니므로 시드 고정이 오히려 요건입니다.
    rng = random.Random(args.seed)  # noqa: S311
    sample_ids = rng.sample(all_ids, min(args.samples, len(all_ids)))
    sampled = collection.get(ids=sample_ids, include=["documents"])

    ranks: list[int | None] = []
    elapsed_total = 0.0
    for doc_id, document in zip(sampled["ids"], sampled["documents"], strict=False):
        query = _build_query(document or "")
        if not query:
            continue
        started = time.perf_counter()
        hits = collection.query(query_texts=[query], n_results=args.top_k)
        elapsed_total += time.perf_counter() - started
        returned = hits["ids"][0]
        ranks.append(returned.index(doc_id) + 1 if doc_id in returned else None)

    measured = len(ranks)
    if measured == 0:
        print("질의를 만들 수 있는 문서가 없습니다.")
        return 1

    top1 = sum(1 for rank in ranks if rank == 1)
    topk = sum(1 for rank in ranks if rank is not None)
    # MRR 은 적중률만으로는 안 보이는 순위 열화를 잡아냅니다. 커버리지를 늘리면
    # 적중률이 유지돼도 순위가 밀릴 수 있습니다.
    mrr = sum(1.0 / rank for rank in ranks if rank is not None) / measured

    print(f"컬렉션      : {args.collection} ({total_indexed:,}건 색인)")
    print(f"질의        : {measured}건 (시드 {args.seed})")
    print(f"top-1 적중률: {top1 / measured * 100:.1f}%")
    print(f"top-{args.top_k} 적중률: {topk / measured * 100:.1f}%")
    print(f"MRR         : {mrr:.4f}")
    print(f"질의 평균   : {elapsed_total / measured * 1000:.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
