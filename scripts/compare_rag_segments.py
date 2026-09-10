"""콜드 SQL 두 측정 결과(JSON)를 비교해 잡음 대비 판정을 내리는 읽기 전용 실행기.

scripts/benchmark_rag_segments.py 가 남긴 structured_sql_traces 와
structured_sql_summary 를 읽어 세 등급으로 분류해 보고한다. 첫째 구조
차이(구간 소멸이나 생성, cursor_count 같은 정수 카운터 변화)는 확정으로
본다. 둘째 구성비 차이는 참고로 본다. 셋째 절대 시간 차이는 각 조건 안의
회차간 산포와 비교해, 차이가 산포 안에 들어가면 반드시 구별 불가로
판정한다. 우열을 단정하는 표현은 쓰지 않는다.

산포 판정은 표준 라이브러리만으로 하며 정규성 가정을 요구하는 검정을
쓰지 않는다. 각 조건의 최소값과 최대값 범위가 겹치는지, 그리고 평균 차이가
두 조건 산포의 합보다 큰지만 본다. 회차가 너무 적어 산포를 추정할 수
없으면 구별 불가가 아니라 판정 불가로 구분해 보고한다.

이 실행기는 JSON 두 개를 읽고 판정을 표준출력으로 내기만 한다. 파일을
쓰지 않고 DB 에 접속하지 않으며 컨테이너를 제어하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

__all__ = [
    "MIN_SAMPLES_DEFAULT",
    "SCOPES",
    "collect_metrics",
    "compare_payloads",
    "format_verdict",
    "load_result",
    "main",
    "select_traces",
]

MIN_SAMPLES_DEFAULT = 2

SCOPES = ("all", "cold", "warm")

_VERDICT_DECIDED = "확정"
_VERDICT_REFERENCE = "참고"


def _verdict_indistinguishable() -> str:
    return "구별 불가"


def _verdict_undecidable() -> str:
    return "판정 불가"


def load_result(path: str) -> dict[str, Any]:
    """결과 JSON 파일 하나를 읽어 딕셔너리로 돌려준다."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"결과 파일 {path} 의 최상위가 객체가 아닙니다.")
    return data


def select_traces(payload: dict[str, Any], scope: str = "cold") -> list[dict[str, Any]]:
    """산출물에서 지정 범위(cold/all/warm)의 트레이스별 정형 원값을 뽑는다."""
    if scope not in SCOPES:
        raise ValueError(f"알 수 없는 범위입니다: {scope}")
    traces = payload.get("structured_sql_traces")
    if isinstance(traces, list) and traces:
        picked: list[dict[str, Any]] = []
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            flag = trace.get("is_cold")
            if scope == "cold" and flag is not True:
                continue
            if scope == "warm" and flag is not False:
                continue
            picked.append(trace)
        return picked
    scoped_key = f"structured_sql_traces_{scope}"
    scoped = payload.get(scoped_key)
    if isinstance(scoped, list):
        return [trace for trace in scoped if isinstance(trace, dict)]
    return []


def collect_metrics(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """트레이스 목록에서 지표별 관측값 목록을 모은다."""
    segments: dict[str, list[float]] = {}
    cursor_ms: list[float] = []
    total_ms: list[float] = []
    residual_ms: list[float] = []
    cursor_count: list[int] = []
    for trace in traces:
        raw_segments = trace.get("segments")
        if isinstance(raw_segments, dict):
            for name, value in raw_segments.items():
                try:
                    segments.setdefault(str(name), []).append(float(value))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
        for key, bucket in (
            ("cursor_ms", cursor_ms),
            ("total_ms", total_ms),
            ("residual_ms", residual_ms),
        ):
            try:
                bucket.append(float(trace[key]))  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                continue
        try:
            cursor_count.append(int(trace["cursor_count"]))  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "n": len(traces),
        "segments": segments,
        "cursor_ms": cursor_ms,
        "total_ms": total_ms,
        "residual_ms": residual_ms,
        "cursor_count": cursor_count,
    }


def _describe(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    return {
        "n": count,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / count,
        "spread": ordered[-1] - ordered[0] if count > 1 else 0.0,
    }


def _ranges_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
    return not (a_max < b_min or b_max < a_min)


def compare_payloads(
    before: dict[str, Any],
    after: dict[str, Any],
    scope: str = "cold",
    min_samples: int = MIN_SAMPLES_DEFAULT,
) -> dict[str, Any]:
    """두 결과 산출물을 비교해 등급별 판정을 담은 딕셔너리로 돌려준다."""
    traces_a = select_traces(before, scope)
    traces_b = select_traces(after, scope)
    metrics_a = collect_metrics(traces_a)
    metrics_b = collect_metrics(traces_b)
    n_a = int(metrics_a["n"])
    n_b = int(metrics_b["n"])

    structural: list[dict[str, Any]] = []
    composition: list[dict[str, Any]] = []
    time_verdicts: list[dict[str, Any]] = []

    if n_a == 0 or n_b == 0:
        reason = (
            f"정형 트레이스가 부족하다(적용 전 {n_a}건, 적용 후 {n_b}건). "
            "산포를 추정할 수 없어 판정을 내리지 않는다."
        )
        structural.append(
            {
                "kind": "자료 부족",
                "name": "-",
                "verdict": _verdict_undecidable(),
                "detail": reason,
            }
        )
        time_verdicts.append(
            {
                "kind": "자료 부족",
                "name": "-",
                "verdict": _verdict_undecidable(),
                "detail": reason,
            }
        )
        return {
            "scope": scope,
            "min_samples": min_samples,
            "n_before": n_a,
            "n_after": n_b,
            "structural": structural,
            "composition": composition,
            "time": time_verdicts,
            "overall": f"판정 불가 {n_a}건 대 {n_b}건, 표본이 부족해 판정을 내리지 않는다.",
        }

    names_a = set(metrics_a["segments"])
    names_b = set(metrics_b["segments"])
    for name in sorted(names_a - names_b):
        count = len(metrics_a["segments"][name])
        structural.append(
            {
                "kind": "구간 소멸",
                "name": name,
                "verdict": _VERDICT_DECIDED,
                "detail": (
                    f"적용 전 {count}회 관측된 구간이 적용 후에는 사라졌다 "
                    f"(적용 전 {n_a}건, 적용 후 {n_b}건)."
                ),
            }
        )
    for name in sorted(names_b - names_a):
        count = len(metrics_b["segments"][name])
        structural.append(
            {
                "kind": "구간 생성",
                "name": name,
                "verdict": _VERDICT_DECIDED,
                "detail": (
                    f"적용 전에는 없던 구간이 적용 후에 {count}회 관측됐다 "
                    f"(적용 전 {n_a}건, 적용 후 {n_b}건)."
                ),
            }
        )
    for name in sorted(names_a & names_b):
        structural.append(
            {
                "kind": "구간 유지",
                "name": name,
                "verdict": "차이 없음",
                "detail": (
                    f"양쪽에 존재한다 "
                    f"(적용 전 {len(metrics_a['segments'][name])}회, "
                    f"적용 후 {len(metrics_b['segments'][name])}회)."
                ),
            }
        )

    counts_a = sorted(metrics_a["cursor_count"])
    counts_b = sorted(metrics_b["cursor_count"])
    if not counts_a or not counts_b:
        structural.append(
            {
                "kind": "카운터 자료 부족",
                "name": "cursor_count",
                "verdict": _verdict_undecidable(),
                "detail": "cursor_count 관측값이 한쪽에 없어 카운터 판정을 내리지 않는다.",
            }
        )
    elif counts_a == counts_b and len(set(counts_a)) == 1 and len(set(counts_b)) == 1:
        structural.append(
            {
                "kind": "카운터 유지",
                "name": "cursor_count",
                "verdict": "차이 없음",
                "detail": f"양쪽이 모두 {counts_a[0]}로 같다.",
            }
        )
    elif counts_a[-1] < counts_b[0] or counts_b[-1] < counts_a[0]:
        structural.append(
            {
                "kind": "카운터 변화",
                "name": "cursor_count",
                "verdict": _VERDICT_DECIDED,
                "detail": (
                    f"관측 범위가 겹치지 않는다 "
                    f"(적용 전 {counts_a[0]}~{counts_a[-1]}, "
                    f"적용 후 {counts_b[0]}~{counts_b[-1]})."
                ),
            }
        )
    elif set(counts_a) != set(counts_b):
        structural.append(
            {
                "kind": "카운터 변화",
                "name": "cursor_count",
                "verdict": _VERDICT_REFERENCE,
                "detail": (
                    f"관측 범위가 겹쳐 확정하지는 않는다 "
                    f"(적용 전 {counts_a[0]}~{counts_a[-1]}, "
                    f"적용 후 {counts_b[0]}~{counts_b[-1]}). 참고로만 본다."
                ),
            }
        )
    else:
        structural.append(
            {
                "kind": "카운터 유지",
                "name": "cursor_count",
                "verdict": "차이 없음",
                "detail": f"관측값 집합이 같다({sorted(set(counts_a))}).",
            }
        )

    mean_cursor_a = (
        sum(metrics_a["cursor_ms"]) / len(metrics_a["cursor_ms"]) if metrics_a["cursor_ms"] else 0.0
    )
    mean_cursor_b = (
        sum(metrics_b["cursor_ms"]) / len(metrics_b["cursor_ms"]) if metrics_b["cursor_ms"] else 0.0
    )
    for name in sorted(names_a & names_b):
        values_a = metrics_a["segments"][name]
        values_b = metrics_b["segments"][name]
        mean_a = sum(values_a) / len(values_a)
        mean_b = sum(values_b) / len(values_b)
        share_a = mean_a / mean_cursor_a if mean_cursor_a else None
        share_b = mean_b / mean_cursor_b if mean_cursor_b else None
        composition.append(
            {
                "name": name,
                "verdict": _VERDICT_REFERENCE,
                "share_before": share_a,
                "share_after": share_b,
                "detail": (
                    f"cursor_ms 평균 대비 구성비 적용 전 {share_a:.3f}, "
                    f"적용 후 {share_b:.3f} (참고용)."
                    if share_a is not None and share_b is not None
                    else "cursor_ms 평균이 없어 구성비를 계산하지 못했다 (참고용)."
                ),
            }
        )

    shared_time_metrics: dict[str, tuple[list[float], list[float]]] = {}
    for name in sorted(names_a & names_b):
        shared_time_metrics[name] = (
            metrics_a["segments"][name],
            metrics_b["segments"][name],
        )
    for key in ("cursor_ms", "total_ms", "residual_ms"):
        if metrics_a[key] and metrics_b[key]:
            shared_time_metrics[key] = (metrics_a[key], metrics_b[key])

    for name, (values_a, values_b) in shared_time_metrics.items():
        stats_a = _describe([float(v) for v in values_a])
        stats_b = _describe([float(v) for v in values_b])
        assert stats_a is not None
        assert stats_b is not None
        if stats_a["n"] < min_samples or stats_b["n"] < min_samples:
            time_verdicts.append(
                {
                    "name": name,
                    "verdict": _verdict_undecidable(),
                    "n_before": stats_a["n"],
                    "n_after": stats_b["n"],
                    "detail": (
                        f"표본이 부족해 산포를 추정할 수 없다 "
                        f"(적용 전 {stats_a['n']}건, 적용 후 {stats_b['n']}건, "
                        f"필요 {min_samples}건). 판정을 내리지 않는다."
                    ),
                }
            )
            continue
        overlap = _ranges_overlap(stats_a["min"], stats_a["max"], stats_b["min"], stats_b["max"])
        mean_diff = abs(stats_a["mean"] - stats_b["mean"])
        spread_sum = stats_a["spread"] + stats_b["spread"]
        if overlap:
            time_verdicts.append(
                {
                    "name": name,
                    "verdict": _verdict_indistinguishable(),
                    "n_before": stats_a["n"],
                    "n_after": stats_b["n"],
                    "detail": (
                        f"두 조건의 범위가 겹친다 "
                        f"(적용 전 {stats_a['min']:.2f}~{stats_a['max']:.2f}ms, "
                        f"적용 후 {stats_b['min']:.2f}~{stats_b['max']:.2f}ms, "
                        f"평균차 {mean_diff:.2f}ms). "
                        f"차이가 산포 안에 들어가 우열을 판정하지 않는다."
                    ),
                }
            )
        elif mean_diff <= spread_sum:
            time_verdicts.append(
                {
                    "name": name,
                    "verdict": _verdict_indistinguishable(),
                    "n_before": stats_a["n"],
                    "n_after": stats_b["n"],
                    "detail": (
                        f"평균차 {mean_diff:.2f}ms 가 두 조건 산포의 합 "
                        f"{spread_sum:.2f}ms 안에 들어간다 "
                        f"(적용 전 {stats_a['min']:.2f}~{stats_a['max']:.2f}ms, "
                        f"적용 후 {stats_b['min']:.2f}~{stats_b['max']:.2f}ms). "
                        f"우열을 판정하지 않는다."
                    ),
                }
            )
        else:
            time_verdicts.append(
                {
                    "name": name,
                    "verdict": "산포 초과(참고)",
                    "n_before": stats_a["n"],
                    "n_after": stats_b["n"],
                    "detail": (
                        f"평균차 {mean_diff:.2f}ms 가 두 조건 산포의 합 "
                        f"{spread_sum:.2f}ms 를 넘고 범위도 겹치지 않는다 "
                        f"(적용 전 {stats_a['min']:.2f}~{stats_a['max']:.2f}ms, "
                        f"적용 후 {stats_b['min']:.2f}~{stats_b['max']:.2f}ms). "
                        f"표본이 적어 확정하지 않고 참고로만 둔다."
                    ),
                }
            )

    decided = sum(1 for item in structural if item["verdict"] == _VERDICT_DECIDED)
    undecidable = sum(1 for item in time_verdicts if item["verdict"] == _verdict_undecidable())
    indistinguishable = sum(
        1 for item in time_verdicts if item["verdict"] == _verdict_indistinguishable()
    )
    overall = (
        f"범위 {scope}, 적용 전 {n_a}건 대 적용 후 {n_b}건. "
        f"구조 확정 {decided}건, 시간 구별 불가 {indistinguishable}건, "
        f"표본 부족 {undecidable}건."
    )
    return {
        "scope": scope,
        "min_samples": min_samples,
        "n_before": n_a,
        "n_after": n_b,
        "structural": structural,
        "composition": composition,
        "time": time_verdicts,
        "overall": overall,
    }


def format_verdict(verdict: dict[str, Any]) -> str:
    """판정 딕셔너리를 사람이 읽을 수 있는 절차 보고 문장으로 펼친다."""
    lines = [
        f"비교 범위: {verdict.get('scope')} "
        f"(적용 전 {verdict.get('n_before')}건, 적용 후 {verdict.get('n_after')}건, "
        f"표본 하한 {verdict.get('min_samples')}건)",
        "",
        "[구조]",
    ]
    structural = verdict.get("structural", [])
    if not structural:
        lines.append("- 해당 없음")
    for item in structural:
        lines.append(
            f"- {item.get('kind')} {item.get('name')}: {item.get('verdict')}. {item.get('detail')}"
        )
    lines.append("")
    lines.append("[구성비, 참고용]")
    composition = verdict.get("composition", [])
    if not composition:
        lines.append("- 해당 없음")
    for item in composition:
        lines.append(f"- {item.get('name')}: {item.get('verdict')}. {item.get('detail')}")
    lines.append("")
    lines.append("[절대 시간, 산포 대비]")
    time_verdicts = verdict.get("time", [])
    if not time_verdicts:
        lines.append("- 해당 없음")
    for item in time_verdicts:
        lines.append(f"- {item.get('name')}: {item.get('verdict')}. {item.get('detail')}")
    lines.append("")
    lines.append(f"종합: {verdict.get('overall')}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="콜드 SQL 두 측정 결과의 잡음 대비 판정")
    parser.add_argument("before", help="적용 전 결과 JSON 경로")
    parser.add_argument("after", help="적용 후 결과 JSON 경로")
    parser.add_argument(
        "--scope",
        choices=SCOPES,
        default="cold",
        help="비교 범위 (기본값: cold)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=MIN_SAMPLES_DEFAULT,
        help="산포 추정에 필요한 조건별 최소 트레이스 수 (기본값: 2)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        before = load_result(args.before)
        after = load_result(args.after)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"결과 파일을 읽지 못했다: {exc}")
        return 2
    verdict = compare_payloads(before, after, scope=args.scope, min_samples=args.min_samples)
    print(format_verdict(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
