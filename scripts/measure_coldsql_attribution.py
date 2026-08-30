"""콜드 스타트 SQL 비용을 재현 가능하게 측정하는 하네스.

캐시를 비운 상태(cold)와 데운 상태(warm)를 동일 표본(fixture 문항)에서 측정하고,
MySQL performance_schema.events_statements_summary_by_digest 를 통해
쿼리별 소비(호출 수, 누적 시간, 최대 시간)를 귀속시켜 어느 쿼리가 비용을 쓰는지
산출물 JSON 및 콘솔 요약에 남깁니다.

주요 설계 원칙:
1. 쿼리별 귀속 정본: performance_schema.events_statements_summary_by_digest 사용
   (SUM_TIMER_WAIT, COUNT_STAR, MAX_TIMER_WAIT, DIGEST_TEXT).
   단위 변환: 피코초(ps) 기준 SUM_TIMER_WAIT -> 1e12로 나눠 초(sec),
   MAX_TIMER_WAIT -> 1e9로 나눠 밀리초(ms).
2. 캐시 비우기 안전장치: Redis FLUSHALL 은 공유 자원에 영향을 주므로
   반드시 --flush-cache 명시적 플래그가 주어졌을 때만 실행하며 기본값은 실행하지 않음(False).
3. Canonical 게이트 판정: measure_llm_quality.py 의 CANONICAL_FIXTURE_HASHES,
   compute_file_sha256, evaluate_canonical 함수를 재사용.
4. Fail-closed: performance_schema 가 비활성화되어 있거나 권한이 없으면
   조용히 빈 결과를 남기지 않고 PerformanceSchemaUnavailableError 로 명확히 실패.
5. 주입 가능한 인터페이스: DB 커넥션 및 Redis 클라이언트를 주입받을 수 있도록 설계하여
   테스트 시 실제 서비스 없이 Mock 객체로 모든 동작 검증 가능.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts._strict_json import dump_strict_json
except ModuleNotFoundError:  # pragma: no cover
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

try:
    from scripts.benchmark_provenance import get_git_status
except ModuleNotFoundError:  # pragma: no cover
    from benchmark_provenance import get_git_status  # type: ignore[no-redef]

from scripts.measure_llm_quality import (  # noqa: E402
    compute_file_sha256,
    evaluate_canonical,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_FIXTURE_PATH = "data/eval/llm_quality_fixture_v2.json"
DEFAULT_COLD_ITEM_IDS = ("q03", "q08", "q25", "q31")
QUERY_PATH = "/api/v1/chatbot/query"


class PerformanceSchemaUnavailableError(RuntimeError):
    """performance_schema 가 비활성화되어 있거나 digest 테이블 접근이 불가능할 때 발생합니다."""


class AttributionMeasurementError(RuntimeError):
    """측정 실행 중 비정상 상태나 오류가 발생했을 때 발생합니다."""


@dataclass(frozen=True)
class DigestStat:
    """performance_schema digest 단일 레코드 집계."""

    digest: str
    digest_text: str
    count_star: int
    sum_timer_wait_ps: int
    sum_timer_wait_sec: float
    min_timer_wait_ms: float
    avg_timer_wait_ms: float
    max_timer_wait_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttributionDiff:
    """동일 쿼리 digest 에 대한 cold vs warm 비용 차이."""

    digest: str
    digest_text: str
    cold_sum_sec: float
    warm_sum_sec: float
    delta_sum_sec: float
    cold_count: int
    warm_count: int
    delta_count: int
    cold_max_ms: float
    warm_max_ms: float
    delta_max_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def convert_timer_ps_to_sec(ps: int | float | None) -> float:
    """피코초(ps)를 초(sec)로 변환합니다 (1e12)."""
    if ps is None:
        return 0.0
    return float(ps) / 1e12


def convert_timer_ps_to_ms(ps: int | float | None) -> float:
    """피코초(ps)를 밀리초(ms)로 변환합니다 (1e9)."""
    if ps is None:
        return 0.0
    return float(ps) / 1e9


def check_performance_schema(db_executor: Callable[[str], list[dict[str, Any]]]) -> bool:
    """performance_schema 가 활성화되어 있고 digest 요약 테이블 조회가 가능한지 검사합니다.

    비활성화되어 있거나 조회 불가 시 PerformanceSchemaUnavailableError 를 발생시킵니다.
    """
    try:
        rows = db_executor("SELECT @@performance_schema AS ps_enabled")
        if rows:
            val = rows[0].get("ps_enabled")
            if val is not None and str(val).lower() in ("0", "off", "false"):
                raise PerformanceSchemaUnavailableError(
                    "performance_schema 가 비활성화되어 있습니다 (OFF)."
                )
    except PerformanceSchemaUnavailableError:
        raise
    except Exception as exc:
        raise PerformanceSchemaUnavailableError(
            f"performance_schema 활성 상태 확인 실패: {exc}"
        ) from exc

    try:
        db_executor(
            "SELECT DIGEST, DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT FROM performance_schema.events_statements_summary_by_digest LIMIT 1"
        )
    except Exception as exc:
        raise PerformanceSchemaUnavailableError(
            f"performance_schema.events_statements_summary_by_digest 테이블 조회 실패: {exc}"
        ) from exc

    return True


def reset_performance_schema_digest(db_executor: Callable[[str], list[dict[str, Any]]]) -> None:
    """performance_schema.events_statements_summary_by_digest 테이블을 비워 통계를 초기화합니다."""
    try:
        db_executor("TRUNCATE TABLE performance_schema.events_statements_summary_by_digest")
    except Exception as exc:
        raise PerformanceSchemaUnavailableError(
            f"performance_schema.events_statements_summary_by_digest 초기화 실패: {exc}"
        ) from exc


def fetch_digest_statistics(
    db_executor: Callable[[str], list[dict[str, Any]]],
    *,
    exclude_internal: bool = True,
) -> list[DigestStat]:
    """performance_schema.events_statements_summary_by_digest 에서 쿼리별 소비 통계를 수집합니다."""
    sql = (
        "SELECT DIGEST, DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT, "
        "MIN_TIMER_WAIT, AVG_TIMER_WAIT, MAX_TIMER_WAIT "
        "FROM performance_schema.events_statements_summary_by_digest "
        "WHERE DIGEST_TEXT IS NOT NULL "
        "ORDER BY SUM_TIMER_WAIT DESC"
    )
    try:
        rows = db_executor(sql)
    except Exception as exc:
        raise PerformanceSchemaUnavailableError(
            f"performance_schema.events_statements_summary_by_digest 데이터 수집 실패: {exc}"
        ) from exc

    results: list[DigestStat] = []
    for row in rows:
        digest = str(row.get("DIGEST") or row.get("digest") or "")
        digest_text = str(row.get("DIGEST_TEXT") or row.get("digest_text") or "")
        if not digest_text:
            continue

        if exclude_internal:
            lower_text = digest_text.lower()
            if (
                "performance_schema" in lower_text
                or "truncate table" in lower_text
                or "select @@" in lower_text
            ):
                continue

        count_star = int(row.get("COUNT_STAR") or row.get("count_star") or 0)
        sum_ps = int(row.get("SUM_TIMER_WAIT") or row.get("sum_timer_wait") or 0)
        min_ps = int(row.get("MIN_TIMER_WAIT") or row.get("min_timer_wait") or 0)
        avg_ps = int(row.get("AVG_TIMER_WAIT") or row.get("avg_timer_wait") or 0)
        max_ps = int(row.get("MAX_TIMER_WAIT") or row.get("max_timer_wait") or 0)

        stat = DigestStat(
            digest=digest,
            digest_text=digest_text,
            count_star=count_star,
            sum_timer_wait_ps=sum_ps,
            sum_timer_wait_sec=convert_timer_ps_to_sec(sum_ps),
            min_timer_wait_ms=convert_timer_ps_to_ms(min_ps),
            avg_timer_wait_ms=convert_timer_ps_to_ms(avg_ps),
            max_timer_wait_ms=convert_timer_ps_to_ms(max_ps),
        )
        results.append(stat)

    return results


def flush_redis_cache(redis_client: Any, flush_requested: bool = False) -> bool:
    """캐시 비우기 플래그가 명시적으로 켜진 경우에만 Redis FLUSHALL 을 실행합니다.

    flush_requested 가 False (기본값)이면 절대 Redis 를 비우지 않습니다.
    """
    if not flush_requested:
        return False

    if redis_client is None:
        raise AttributionMeasurementError(
            "Redis 클라이언트가 제공되지 않아 캐시를 비울 수 없습니다."
        )

    try:
        redis_client.flushall()
        return True
    except Exception as exc:
        raise AttributionMeasurementError(f"Redis FLUSHALL 실행 실패: {exc}") from exc


def calculate_attribution_diff(
    cold_stats: list[DigestStat | dict[str, Any]],
    warm_stats: list[DigestStat | dict[str, Any]],
) -> list[AttributionDiff]:
    """cold 와 warm 상태의 쿼리별 소비 차이를 계산하여 반환합니다."""
    cold_dict: dict[str, dict[str, Any]] = {}
    for item in cold_stats:
        d = item.to_dict() if isinstance(item, DigestStat) else dict(item)
        key = d.get("digest") or d.get("digest_text", "")
        cold_dict[key] = d

    warm_dict: dict[str, dict[str, Any]] = {}
    for item in warm_stats:
        d = item.to_dict() if isinstance(item, DigestStat) else dict(item)
        key = d.get("digest") or d.get("digest_text", "")
        warm_dict[key] = d

    all_keys = set(cold_dict.keys()) | set(warm_dict.keys())
    diff_list: list[AttributionDiff] = []

    for key in all_keys:
        c = cold_dict.get(key, {})
        w = warm_dict.get(key, {})

        digest = c.get("digest") or w.get("digest") or key
        digest_text = c.get("digest_text") or w.get("digest_text") or key

        c_sum = float(c.get("sum_timer_wait_sec") or 0.0)
        w_sum = float(w.get("sum_timer_wait_sec") or 0.0)
        delta_sum = round(c_sum - w_sum, 6)

        c_count = int(c.get("count_star") or 0)
        w_count = int(w.get("count_star") or 0)
        delta_count = c_count - w_count

        c_max = float(c.get("max_timer_wait_ms") or 0.0)
        w_max = float(w.get("max_timer_wait_ms") or 0.0)
        delta_max = round(c_max - w_max, 3)

        diff = AttributionDiff(
            digest=digest,
            digest_text=digest_text,
            cold_sum_sec=c_sum,
            warm_sum_sec=w_sum,
            delta_sum_sec=delta_sum,
            cold_count=c_count,
            warm_count=w_count,
            delta_count=delta_count,
            cold_max_ms=c_max,
            warm_max_ms=w_max,
            delta_max_ms=delta_max,
        )
        diff_list.append(diff)

    # 차이(cold 절감 가능성) 기준 내림차순 정렬
    diff_list.sort(key=lambda x: (x.delta_sum_sec, x.cold_sum_sec), reverse=True)
    return diff_list


def load_target_items(
    fixture_path: str | Path,
    item_ids: list[str] | None = None,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """fixture 파일에서 대상 질의 문항을 로드합니다."""
    path = Path(fixture_path)
    if not path.is_file():
        raise FileNotFoundError(f"Fixture 파일을 찾을 수 없습니다: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("items", [])
    total_items = len(items)

    if item_ids:
        target_ids = {i.strip() for i in item_ids if i.strip()}
        items = [item for item in items if str(item.get("id") or item.get("item_id")) in target_ids]

    if limit > 0:
        items = items[:limit]

    return items, total_items


def send_http_query(
    base_url: str,
    question: str,
    timeout_sec: float = 180.0,
) -> dict[str, Any]:
    """운영 RAG 질의 경로로 질문을 전송하고 응답을 수신합니다."""
    url = f"{base_url.rstrip('/')}{QUERY_PATH}"
    body = json.dumps({"query": question}).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": True, "elapsed_ms": elapsed_ms, "payload": payload}
    except (urlerror.URLError, TimeoutError, OSError, ValueError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc)}


def run_attribution_measurement(
    *,
    db_executor: Callable[[str], list[dict[str, Any]]],
    redis_client: Any = None,
    flush_cache_requested: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    item_ids: list[str] | None = None,
    limit: int = 0,
    repetitions: int = 1,
    timeout_sec: float = 180.0,
    query_sender: Callable[[str, str, float], dict[str, Any]] = send_http_query,
    allow_unknown_provenance: bool = False,
) -> dict[str, Any]:
    """콜드/웜 SQL 비용 귀속 측정을 실행하고 정합성 보고서를 생성합니다."""
    # 1. performance_schema 가용성 사전 검증 (fail-closed)
    check_performance_schema(db_executor)

    # 2. fixture 로드 및 대상 문항 선별
    target_items, total_fixture_items = load_target_items(
        fixture_path, item_ids=item_ids, limit=limit
    )
    if not target_items:
        raise AttributionMeasurementError("측정 대상 문항이 0건입니다.")

    git_sha, git_dirty = get_git_status()
    fixture_sha256 = compute_file_sha256(fixture_path)
    start_utc = datetime.now(UTC).isoformat()

    request_failures = 0
    cold_query_results: list[dict[str, Any]] = []
    warm_query_results: list[dict[str, Any]] = []

    # ==================== 1단계: Cold 상태 측정 ====================
    # 명시적 플래그가 주어졌을 때만 캐시를 비웁니다.
    cache_flushed = flush_redis_cache(redis_client, flush_requested=flush_cache_requested)

    # digest 테이블 초기화
    reset_performance_schema_digest(db_executor)

    for rep in range(repetitions):
        for item in target_items:
            q_id = str(item.get("id") or item.get("item_id") or "unknown")
            question = str(item.get("question") or item.get("query") or "")
            res = query_sender(base_url, question, timeout_sec)
            cold_query_results.append(
                {
                    "item_id": q_id,
                    "repetition": rep,
                    "ok": res.get("ok", False),
                    "elapsed_ms": res.get("elapsed_ms", 0.0),
                    "error": res.get("error"),
                }
            )
            if not res.get("ok"):
                request_failures += 1

    cold_stats = fetch_digest_statistics(db_executor)

    # ==================== 2단계: Warm 상태 측정 ====================
    # Warm 단계에서는 캐시를 비우지 않고 동일 문항을 재호출합니다.
    reset_performance_schema_digest(db_executor)

    for rep in range(repetitions):
        for item in target_items:
            q_id = str(item.get("id") or item.get("item_id") or "unknown")
            question = str(item.get("question") or item.get("query") or "")
            res = query_sender(base_url, question, timeout_sec)
            warm_query_results.append(
                {
                    "item_id": q_id,
                    "repetition": rep,
                    "ok": res.get("ok", False),
                    "elapsed_ms": res.get("elapsed_ms", 0.0),
                    "error": res.get("error"),
                }
            )
            if not res.get("ok"):
                request_failures += 1

    warm_stats = fetch_digest_statistics(db_executor)

    # ==================== 3단계: 쿼리별 차이 계산 ====================
    diff_table = calculate_attribution_diff(cold_stats, warm_stats)

    end_utc = datetime.now(UTC).isoformat()
    end_git_sha, end_git_dirty = get_git_status()

    # ==================== 4단계: Canonical 게이트 판정 ====================
    is_canonical, failed_gates = evaluate_canonical(
        fixture_sha256=fixture_sha256,
        limit=limit,
        item_count=len(target_items),
        total_fixture_items=total_fixture_items,
        repetitions=repetitions,
        request_failures=request_failures,
        start_sha=git_sha,
        start_dirty=git_dirty,
        end_sha=end_git_sha,
        end_dirty=end_git_dirty,
        allow_unknown_provenance=allow_unknown_provenance,
    )

    # Cold SQL 귀속 측정의 Canonical 적격성 조건:
    # flush_cache_requested 와 cache_flushed 가 모두 True 여야만 warm-first 가 cold 로 오표기되는 것을 방지합니다.
    if not (flush_cache_requested and cache_flushed):
        failed_gates.append("flush_cache_executed")
        is_canonical = False

    report: dict[str, Any] = {
        "metadata": {
            "harness": "measure_coldsql_attribution",
            "version": "1.0.0",
            "timestamp_start_utc": start_utc,
            "timestamp_end_utc": end_utc,
            "git_sha": git_sha,
            "git_dirty": git_dirty,
            "fixture_path": str(fixture_path),
            "fixture_sha256": fixture_sha256,
            "target_item_ids": [str(i.get("id") or i.get("item_id")) for i in target_items],
            "item_count": len(target_items),
            "total_fixture_items": total_fixture_items,
            "repetitions": repetitions,
            "flush_cache_requested": flush_cache_requested,
            "cache_flushed": cache_flushed,
            "base_url": base_url,
        },
        "canonical_evaluation": {
            "is_canonical": is_canonical,
            "failed_gates": failed_gates,
        },
        "cold_measurements": {
            "queries": cold_query_results,
            "digest_stats": [s.to_dict() for s in cold_stats],
        },
        "warm_measurements": {
            "queries": warm_query_results,
            "digest_stats": [s.to_dict() for s in warm_stats],
        },
        "attribution_diff_table": [d.to_dict() for d in diff_table],
        "summary": {
            "total_cold_sql_sec": round(sum(s.sum_timer_wait_sec for s in cold_stats), 6),
            "total_warm_sql_sec": round(sum(s.sum_timer_wait_sec for s in warm_stats), 6),
            "top_cost_query_digest": diff_table[0].digest if diff_table else None,
            "top_cost_query_text": diff_table[0].digest_text if diff_table else None,
            "top_cost_query_delta_sec": diff_table[0].delta_sum_sec if diff_table else 0.0,
            "request_failures": request_failures,
        },
    }

    return report


def default_sqlalchemy_executor(engine_or_url: Any = None) -> Callable[[str], list[dict[str, Any]]]:
    """SQLAlchemy 기반 기본 DB 실행 함수를 생성합니다."""
    from sqlalchemy import text

    if engine_or_url is None:
        from src.app.core.db import engine

        db_engine = engine
    elif isinstance(engine_or_url, str):
        from sqlalchemy import create_engine

        db_engine = create_engine(engine_or_url)
    else:
        db_engine = engine_or_url

    def _execute(sql: str) -> list[dict[str, Any]]:
        with db_engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                return [dict(row._mapping) for row in result]
            conn.commit()
            return []

    return _execute


def default_redis_client(redis_url: str | None = None) -> Any:
    """Redis 기본 클라이언트를 생성합니다."""
    import redis

    from src.app.core.config import settings

    url = redis_url or settings.REDIS_URL
    return redis.Redis.from_url(url, decode_responses=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="콜드 스타트 SQL 비용 쿼리별 귀속 측정 하네스")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"RAG 서비스 Base URL (기본값: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--fixture",
        default=DEFAULT_FIXTURE_PATH,
        help=f"문항 Fixture 경로 (기본값: {DEFAULT_FIXTURE_PATH})",
    )
    parser.add_argument(
        "--item-ids",
        default=",".join(DEFAULT_COLD_ITEM_IDS),
        help=f"측정할 문항 ID 쉼표 구분 목록 (기본값: {','.join(DEFAULT_COLD_ITEM_IDS)})",
    )
    parser.add_argument(
        "--flush-cache",
        action="store_true",
        default=False,
        help="Cold 측정 전 Redis FLUSHALL 실행 여부 (기본값: False, 명시적 지정 필요)",
    )
    parser.add_argument("--redis-url", default=None, help="Redis 접속 URL (미지정 시 설정값 사용)")
    parser.add_argument("--db-url", default=None, help="MySQL DB 접속 URL (미지정 시 설정값 사용)")
    parser.add_argument("--output", default=None, help="측정 산출물 JSON 저장 경로")
    parser.add_argument("--limit", type=int, default=0, help="대상 문항 수 제한 (0: 전체)")
    parser.add_argument("--repetitions", type=int, default=1, help="문항별 반복 회수 (기본값: 1)")
    parser.add_argument(
        "--timeout", type=float, default=180.0, help="HTTP 요청 타임아웃 초 (기본값: 180.0)"
    )
    parser.add_argument(
        "--allow-unknown-provenance",
        action="store_true",
        default=False,
        help="Git dirty 또는 미등록 fixture 환경에서도 실행 허용",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    item_ids = [i.strip() for i in args.item_ids.split(",") if i.strip()] if args.item_ids else None

    db_executor = default_sqlalchemy_executor(args.db_url)
    redis_client = default_redis_client(args.redis_url) if args.flush_cache else None

    try:
        report = run_attribution_measurement(
            db_executor=db_executor,
            redis_client=redis_client,
            flush_cache_requested=args.flush_cache,
            base_url=args.base_url,
            fixture_path=args.fixture,
            item_ids=item_ids,
            limit=args.limit,
            repetitions=args.repetitions,
            timeout_sec=args.timeout,
            allow_unknown_provenance=args.allow_unknown_provenance,
        )
    except PerformanceSchemaUnavailableError as exc:
        print(f"[ERROR] performance_schema 사용 불가: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[ERROR] 측정 실패: {exc}", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dump_strict_json(report, out_path)
        print(f"[INFO] 결과 저장 완료: {out_path}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
