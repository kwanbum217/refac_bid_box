"""audit_model_inventory 구현을 구현 독립 행동 시나리오 8문항으로 채점합니다.

구현 내부(함수명, 상태 파일 스키마)에 의존하지 않고 main() 의 종료 코드와
stdout 만 봅니다. 어느 구현이든 같은 계약을 지켰다면 통과해야 합니다.

경합에서는 후보를 여러 개 넘겨 나란히 채점하고, 인자 없이 부르면 이 저장소의
구현을 자체 시험합니다.

    uv run python benchmarks/free_workers/scoring.py
    uv run python benchmarks/free_workers/scoring.py --candidate a=/경로/a.py --candidate b=/경로/b.py

종료 코드: 0 전 후보 8/8, 1 만점 미달 후보 있음, 2 후보를 채점할 수 없음
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import re
import sys
import tempfile
from pathlib import Path


def load(script: Path):
    spec = importlib.util.spec_from_file_location(f"cand_{script.parent.parent.name}", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(mod, state: Path, listing: set[str]):
    """opencode models 조회를 가짜로 바꾸고 1회 실행. (종료코드, stdout) 반환."""
    mod._run_listing = lambda cmd: set(listing)
    if hasattr(mod, "_codex_ids"):
        mod._codex_ids = lambda: set(listing)
    if hasattr(mod, "_kimi_aliases"):
        mod._kimi_aliases = lambda: set(listing)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(["--state", str(state)])
    return rc, buf.getvalue()


def fail_listing(mod, state: Path):
    """조회가 예외를 던지는 회차 = 확인불가(unknown)."""

    def boom(cmd):
        raise RuntimeError("조회 실패 시뮬레이션")

    mod._run_listing = boom
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(["--state", str(state)])
    return rc, buf.getvalue()


def verdict_extinct(out: str) -> bool:
    """항목별 판정 줄에서만 소멸을 찾습니다.

    안내문("3회 연속 이탈이 확인될 때만 소멸 판정합니다")은 판정이 아닙니다.
    판정 줄은 들여쓴 항목 줄이거나 집계 줄("소멸 N건")입니다.
    """
    for line in out.splitlines():
        if line.startswith("  ") and line.strip().startswith("소멸"):
            return True
        if re.match(r"^소멸 \d+건", line.strip()):
            return True
    return False


POOL = {
    "target": {
        "id": "prov/target",
        "provider": "opencode",
        "suitable_for": ["investigator"],
        "tier": "free",
        "notes": "",
        "auto_selectable": False,
    }
}
PRESENT = {"prov/target"}
ABSENT: set[str] = set()


def score(name: str, script: Path, tmp: Path) -> tuple[int, list[str]]:
    mod = load(script)
    mod.MODEL_POOL = POOL
    pts, notes = 0, []
    st = tmp / f"{name}.json"

    # S1 단발 이탈은 소멸이 아니다
    st.unlink(missing_ok=True)
    rc, out = run(mod, st, ABSENT)
    if rc == 0 and not verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S1 단발이탈이 소멸(rc={rc})")

    # S2 2회 연속도 소멸이 아니다
    rc, out = run(mod, st, ABSENT)
    if rc == 0 and not verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S2 2회연속이 소멸(rc={rc})")

    # S3 3회째에 소멸
    rc, out = run(mod, st, ABSENT)
    if rc == 1 and verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S3 3회연속이 소멸 아님(rc={rc})")

    # S4 present 가 오면 초기화되고, 이후 2회 이탈로는 소멸이 아니다
    st.unlink(missing_ok=True)
    run(mod, st, ABSENT)
    run(mod, st, ABSENT)  # 2회 누적
    run(mod, st, PRESENT)  # 초기화
    run(mod, st, ABSENT)
    rc, out = run(mod, st, ABSENT)  # 초기화 후 2회
    if rc == 0 and not verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S4 present 초기화 안 됨(rc={rc})")

    # S5 unknown 은 카운터를 올리지 않는다 (absent,unknown,absent -> 소멸 아님)
    st.unlink(missing_ok=True)
    run(mod, st, ABSENT)
    fail_listing(mod, st)
    rc, out = run(mod, st, ABSENT)
    if rc == 0 and not verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S5 unknown 이 카운터를 올림(rc={rc})")

    # S6 unknown 은 카운터를 초기화하지도 않는다
    #    absent,absent,unknown,absent -> 3연속이므로 소멸이어야 한다
    st.unlink(missing_ok=True)
    run(mod, st, ABSENT)
    run(mod, st, ABSENT)
    fail_listing(mod, st)
    rc, out = run(mod, st, ABSENT)
    if rc == 1 and verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S6 unknown 이 카운터를 초기화(rc={rc})")

    # S7 손상된 상태 파일에서 죽지 않는다
    st.write_text("{ 깨진 JSON", encoding="utf-8")
    try:
        rc, out = run(mod, st, PRESENT)
        if rc != 2:
            pts += 1
        else:
            notes.append("S7 손상 상태파일에서 rc=2")
    except Exception as exc:
        notes.append(f"S7 예외: {type(exc).__name__}")

    # S8 확인불가는 절대 소멸로 승격되지 않는다 (3회 연속 unknown)
    st.unlink(missing_ok=True)
    for _ in range(3):
        rc, out = fail_listing(mod, st)
    if rc == 0 and not verdict_extinct(out):
        pts += 1
    else:
        notes.append(f"S8 unknown 3회가 소멸(rc={rc})")

    return pts, notes


def _parse_args(argv: list[str]) -> tuple[Path, list[tuple[str, Path]]]:
    ap = argparse.ArgumentParser(
        description="무료 워커 스택 산출물을 구현 독립 행동 시나리오 8문항으로 채점합니다."
    )
    ap.add_argument(
        "--tmp",
        default=None,
        help="상태 파일용 임시 디렉터리 (기본: 시스템 임시 디렉터리 아래 새로 만듭니다)",
    )
    ap.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="이름=경로",
        help=(
            "채점 대상 audit_model_inventory.py 경로. 반복 지정합니다. "
            "미지정 시 이 저장소의 구현을 자체 시험합니다."
        ),
    )
    args = ap.parse_args(argv)

    cands: list[tuple[str, Path]] = []
    for spec in args.candidate:
        if "=" not in spec:
            ap.error(f"--candidate 는 이름=경로 형식입니다: {spec}")
        name, _, path = spec.partition("=")
        cands.append((name, Path(path)))

    if not cands:
        repo = Path(__file__).resolve().parent.parent.parent
        cands = [("self", repo / "scripts" / "audit_model_inventory.py")]

    tmp = Path(args.tmp) if args.tmp else Path(tempfile.mkdtemp(prefix="free_worker_scoring_"))
    return tmp, cands


def main(argv: list[str] | None = None) -> int:
    tmp, candidates = _parse_args(sys.argv[1:] if argv is None else argv)
    tmp.mkdir(parents=True, exist_ok=True)

    worst = 0
    for name, script in candidates:
        if not script.is_file():
            print(f"{name:20} 없음 {script}")
            worst = max(worst, 2)
            continue
        try:
            pts, notes = score(name, script, tmp)
        except Exception as exc:
            print(f"{name:20} 오류 {type(exc).__name__}: {exc}")
            worst = max(worst, 2)
            continue
        print(f"{name:20} {pts}/8  {'; '.join(notes) if notes else '전항목 통과'}")
        if pts < 8:
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
