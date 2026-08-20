#!/usr/bin/env python
"""회차별 실행 기록과 채점 결과를 합쳐 스택별 대표값을 냅니다.

성공은 세 조건을 모두 만족한 회차입니다.

    종료 코드 0 (시한 내 종료)  AND  커밋 1건 이상  AND  채점 만점

코드가 옳아도 사전 등록한 시한 안에 커밋하지 못했으면 성공이 아닙니다.
워커는 산출물을 브랜치에 남겨야 다음 단계가 이어받을 수 있습니다.

    uv run python benchmarks/free_workers/aggregate.py \
        --runs <results.tsv> --scores <scores.txt> --out <결과.json>
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

DEFAULT_MAX_SCORE = 6


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="2차 경합 집계")
    ap.add_argument("--runs", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    scores: dict[str, int] = {}
    for line in Path(a.scores).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and "/" in parts[1]:
            got, _, full = parts[1].partition("/")
            scores[parts[0]] = (int(got), int(full))

    runs: list[dict] = []
    for line in Path(a.runs).read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        tag = cols[0]
        rc_elapsed = cols[1].split()
        rc = int(rc_elapsed[0]) if rc_elapsed and rc_elapsed[0].isdigit() else 124
        elapsed = int(rc_elapsed[1]) if len(rc_elapsed) > 1 and rc_elapsed[1].isdigit() else None
        commits = int(cols[2]) if cols[2].isdigit() else 0
        stack, _, rep = tag.rpartition("_r")
        got, full = scores.get(tag, (None, None))
        max_score = full if full is not None else DEFAULT_MAX_SCORE
        ok = rc == 0 and commits >= 1 and got == max_score
        runs.append(
            {
                "stack": stack,
                "rep": int(rep) if rep.isdigit() else None,
                "exit_code": rc,
                "elapsed_sec": elapsed,
                "commits": commits,
                "score": None if got is None else f"{got}/{max_score}",
                "success": ok,
                # 종료 코드 종류를 뭉뚱그리지 않습니다. 124 만 시한 초과이고
                # 나머지 비정상 종료(모델 없음, CLI 오류, 강제 종료)는 다릅니다.
                "failure": None
                if ok
                else (
                    "timeout"
                    if rc == 124
                    else f"process_error(rc={rc})"
                    if rc != 0
                    else "no_commit"
                    if commits < 1
                    else "score"
                ),
            }
        )

    by_stack: dict[str, list[dict]] = {}
    for r in runs:
        by_stack.setdefault(r["stack"], []).append(r)

    summary = []
    for stack, rs in sorted(by_stack.items()):
        ok = [r for r in rs if r["success"]]
        times = [r["elapsed_sec"] for r in ok if r["elapsed_sec"] is not None]
        all_times = [r["elapsed_sec"] for r in rs if r["elapsed_sec"] is not None]
        summary.append(
            {
                "stack": stack,
                "runs": len(rs),
                "success": len(ok),
                "success_rate": round(len(ok) / len(rs), 3) if rs else None,
                # 성공 회차만의 값입니다. 실패 회차의 벽시계가 빠져 있으므로
                # 반드시 성공률과 함께 읽어야 합니다. 이름에 success 를 넣습니다.
                "median_success_sec": round(statistics.median(times)) if times else None,
                "p95_success_sec": round(_percentile(times, 0.95)) if times else None,
                # 시한 초과를 절단 관측으로 포함해 전 회차를 함께 본 값입니다.
                "p95_all_sec": round(_percentile(all_times, 0.95)) if all_times else None,
                "failures": sorted({r["failure"] for r in rs if r["failure"]}),
            }
        )
    # 성공률 우선, 그다음 median. 표본이 작으므로 순위가 아니라 정렬일 뿐입니다.
    summary.sort(key=lambda s: (-(s["success_rate"] or 0), s["median_success_sec"] or 10**9))

    out = {
        "benchmark": "free_workers/builder_02",
        "date": "2026-08-20",
        "scorer_frozen_before_run": True,
        "timeout_sec": 720,
        "concurrency": 3,
        "order": "round-robin (rep 바깥, stack 안쪽)",
        "success_definition": "종료 코드 0 AND 커밋 1건 이상 AND 채점 만점",
        "limitations": [
            "반복 3회는 median 을 잡기에는 충분하나 p95 를 신뢰하기에는 부족하다.",
            "동시 3대 조건에서 측정했다. 같은 백엔드를 쓰는 스택끼리 경합이 있다.",
            "과제 1종(소형 builder)만 쟀다. 역할별 적합성은 이 값으로 말할 수 없다.",
        ],
        "stacks": summary,
        "runs": runs,
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for s in summary:
        print(
            f"{s['stack']:16} 성공 {s['success']}/{s['runs']}  "
            f"median(성공) {s['median_success_sec']}s  p95(성공) {s['p95_success_sec']}s  "
            f"p95(전체) {s['p95_all_sec']}s  {','.join(s['failures'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
