"""bid_records 순위 규칙 적용 전후를 같은 검색어 묶음으로 비교하는 읽기 전용 측정.

운영 Meilisearch 의 bid_records 색인에 POST /indexes/bid_records/search 만 보냅니다.
설정 조회·변경, 문서 쓰기, task 생성은 하지 않습니다. 정렬 파라미터를 포함한 검색의
processingTimeMs 를 검색어·대상별로 회차마다 기록하고 중앙값·최댓값·추정 총건수·
상위 5건 원본 PK 를 JSON 으로 출력합니다.

app 컨테이너 안에서 표준입력으로 실행해도 동작하도록 __file__ 경로에 의존하지
않습니다. 인자 없이 실행하면 JSON 을 표준출력으로 내보내고, --output 을 주면 그
경로에 씁니다. master key 는 출력하지 않습니다.

실행 예:

    docker compose exec -T app python - < scripts/measure_meili_ranking.py > before.json
    docker compose exec -T app python - < scripts/measure_meili_ranking.py \\
        --output data/benchmarks/meili_ranking_after.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INDEX_UID = "bid_records"
DEFAULT_ROUNDS = 3
DEFAULT_LIMIT = 20

QUERY_BUNDLE = (
    "정보화",
    "청소",
    "유지보수 용역",
    "시스템 구축",
    "경비",
    "설계",
    "감리",
    "소프트웨어",
    "연구 용역",
    "홍보",
    "교육",
    "시설물 유지관리",
)


@dataclass(frozen=True)
class ProbeTarget:
    name: str
    filter: str
    sort: tuple[str, ...]


TARGETS = (
    ProbeTarget(
        name="result_servc",
        filter='dataset = "result" AND category = "Servc"',
        sort=("rl_openg_dt:desc", "source_id:desc"),
    ),
    ProbeTarget(
        name="announcement_servc",
        filter='dataset = "announcement" AND category = "Servc" AND is_cancelled != true',
        sort=("bid_ntce_dt:desc", "source_id:desc"),
    ),
)


def _ensure_project_root_on_path() -> None:
    """표준입력 실행에서 cwd 기준으로 src 패키지를 찾을 수 있게 합니다."""
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "src" / "app" / "services" / "search_index.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


def load_client() -> Any:
    """base_url 과 인증 헤더를 앱 클라이언트에서 그대로 재사용합니다."""
    _ensure_project_root_on_path()
    from src.app.services.search_index import MeiliSearchClient

    return MeiliSearchClient()


def _expected_ranking_rules() -> list[str] | None:
    """서버 설정이 아니라 코드가 선언한 순위 규칙을 결과에 함께 남깁니다."""
    _ensure_project_root_on_path()
    try:
        from src.app.services.search_index import RANKING_RULES
    except (ImportError, AttributeError):
        return None
    return list(RANKING_RULES)


def _top_ids(hits: Any) -> list[str | None]:
    if not isinstance(hits, list):
        return []
    return [
        str(hit["source_id"])
        if isinstance(hit, dict) and hit.get("source_id") is not None
        else None
        for hit in hits[:5]
    ]


def _samples_for(
    client: Any, query: str, target: ProbeTarget, rounds: int, limit: int
) -> tuple[list[dict[str, Any]], list[float]]:
    """검색어 하나·대상 하나를 rounds 회 실행한 회차 기록과 지연 표본을 돌려줍니다."""
    body = {
        "q": query,
        "filter": target.filter,
        "sort": list(target.sort),
        "offset": 0,
        "limit": limit,
        "attributesToRetrieve": ["source_id"],
    }
    samples: list[dict[str, Any]] = []
    for _ in range(rounds):
        payload = client._request("POST", f"/indexes/{INDEX_UID}/search", json=body)
        elapsed = payload.get("processingTimeMs")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
            elapsed = None
        samples.append(
            {
                "processingTimeMs": elapsed,
                "estimatedTotalHits": payload.get("estimatedTotalHits"),
                "top_ids": _top_ids(payload.get("hits")),
            }
        )
    measured = [
        float(sample["processingTimeMs"])
        for sample in samples
        if sample["processingTimeMs"] is not None
    ]
    return samples, measured


def build_report(
    client: Any,
    *,
    queries: tuple[str, ...] = QUERY_BUNDLE,
    targets: tuple[ProbeTarget, ...] = TARGETS,
    rounds: int = DEFAULT_ROUNDS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """모든 검색어·대상 조합을 측정해 리포트 사전을 만듭니다."""
    results: list[dict[str, Any]] = []
    for target in targets:
        for query in queries:
            samples, measured = _samples_for(client, query, target, rounds, limit)
            results.append(
                {
                    "query": query,
                    "target": target.name,
                    "filter": target.filter,
                    "sort": list(target.sort),
                    "rounds": samples,
                    "median_ms": statistics.median(measured) if measured else None,
                    "max_ms": max(measured) if measured else None,
                    "estimated_total_hits": samples[-1]["estimatedTotalHits"],
                    "top_ids": samples[-1]["top_ids"],
                }
            )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "index_uid": INDEX_UID,
        "expected_ranking_rules_from_code": _expected_ranking_rules(),
        "rounds": rounds,
        "limit": limit,
        "queries": list(queries),
        "targets": [
            {"name": target.name, "filter": target.filter, "sort": list(target.sort)}
            for target in targets
        ],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="bid_records 정렬 검색 지연을 회차별로 측정합니다(읽기 전용)."
    )
    parser.add_argument("--output", type=Path, default=None, help="결과 JSON 저장 경로")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="검색어당 반복 횟수")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="검색당 결과 수")
    args = parser.parse_args(argv)

    report = build_report(load_client(), rounds=args.rounds, limit=args.limit)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is None:
        sys.stdout.write(text + "\n")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + "\n", encoding="utf-8")
    sys.stderr.write(f"측정 결과를 {args.output} 에 저장했습니다.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
