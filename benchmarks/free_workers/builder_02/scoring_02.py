"""builder_02(--json 출력 추가) 산출물을 구현 독립 시나리오 6문항으로 채점합니다.

구현 내부(함수명, 상태 파일 스키마, 출력 문구)를 보지 않습니다. --json 출력을
json.loads 로 파싱한 결과와 종료 코드만 검사하므로, 어떤 구현이든 Capsule 의
계약을 지켰다면 통과합니다.

이 파일은 모델 실행 전에 동결합니다. 결과를 보고 고치지 않습니다.
자체 시험은 --self-test 로 합니다.

    uv run python benchmarks/free_workers/builder_02/scoring_02.py --self-test
    uv run python .../scoring_02.py --candidate a=/경로/audit_model_inventory.py

종료 코드: 0 전 후보 만점, 1 만점 미달 후보 있음, 2 채점 불가
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

MAX_SCORE = 6

POOL = {
    "target": {
        "id": "prov/target",
        "provider": "opencode",
        "suitable_for": ["investigator"],
        "tier": "free",
        "notes": "",
        "auto_selectable": False,
    },
    "unassigned": {
        "id": "prov/unassigned",
        "provider": "opencode",
        "suitable_for": [],
        "tier": "free",
        "notes": "",
        "auto_selectable": False,
    },
}
PRESENT = {"prov/target"}
ABSENT: set[str] = set()


def _load(script: Path, tag: str):
    spec = importlib.util.spec_from_file_location(f"cand_{tag}", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.MODEL_POOL = POOL
    return mod


def _run(mod, state: Path, listing: set[str] | None, extra: list[str]):
    """listing 이 None 이면 조회가 실패하는 회차(unknown)입니다."""
    if listing is None:

        def boom(cmd):
            raise RuntimeError("조회 실패 시뮬레이션")

        mod._run_listing = boom
    else:
        mod._run_listing = lambda cmd: set(listing)
    for name in ("_codex_ids", "_kimi_aliases"):
        if hasattr(mod, name):
            setattr(mod, name, lambda: set(listing or ()))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--state", str(state), *extra])
    except SystemExit as exc:
        # --json 을 모르는 구현은 argparse 가 SystemExit(2) 를 냅니다.
        # 채점 실패이지 채점기 오류가 아니므로 점수 0 으로 이어갑니다.
        rc = int(exc.code) if isinstance(exc.code, int) else 2
    return rc, buf.getvalue()


def _as_json(out: str):
    """stdout 전체가 JSON 객체 하나여야 합니다. 섞여 있으면 None."""
    try:
        data = json.loads(out.strip())
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def score(tag: str, script: Path, tmp: Path) -> tuple[int, list[str]]:
    mod = _load(script, tag)
    pts, notes = 0, []
    st = tmp / f"{tag}_02.json"

    # J1 --json 은 파싱 가능한 JSON 객체 하나만 낸다
    st.unlink(missing_ok=True)
    rc, out = _run(mod, st, PRESENT, ["--json"])
    d = _as_json(out)
    if d is not None and rc == 0:
        pts += 1
    else:
        notes.append("J1 --json 출력이 JSON 객체 하나가 아님")

    # J2 최상위 스키마: extinct(int), pools(dict)
    if d is not None and isinstance(d.get("extinct"), int) and isinstance(d.get("pools"), dict):
        pts += 1
    else:
        notes.append("J2 extinct/pools 스키마 불일치")

    # J3 배정 대상 아닌 항목은 skipped, streak 0
    ent = (d or {}).get("pools", {}).get("unassigned")
    if isinstance(ent, dict) and ent.get("status") == "skipped" and ent.get("streak") == 0:
        pts += 1
    else:
        notes.append("J3 미배정 항목이 skipped/0 이 아님")

    # J4 absent 2회: extinct 0, rc 0, streak 2
    st.unlink(missing_ok=True)
    _run(mod, st, ABSENT, ["--json"])
    rc, out = _run(mod, st, ABSENT, ["--json"])
    d = _as_json(out)
    ent = (d or {}).get("pools", {}).get("target", {})
    if d is not None and rc == 0 and d.get("extinct") == 0 and ent.get("streak") == 2:
        pts += 1
    else:
        notes.append(f"J4 absent 2회 기대 불일치 (rc={rc})")

    # J5 absent 3회째: extinct >= 1, rc 1
    rc, out = _run(mod, st, ABSENT, ["--json"])
    d = _as_json(out)
    if d is not None and rc == 1 and (d.get("extinct") or 0) >= 1:
        pts += 1
    else:
        notes.append(f"J5 absent 3회째가 소멸 아님 (rc={rc})")

    # J6 unknown 은 streak 를 보존한다 (absent, unknown -> streak 그대로 1)
    st.unlink(missing_ok=True)
    _run(mod, st, ABSENT, ["--json"])
    rc, out = _run(mod, st, None, ["--json"])
    d = _as_json(out)
    ent = (d or {}).get("pools", {}).get("target", {})
    if d is not None and rc == 0 and ent.get("status") == "unknown" and ent.get("streak") == 1:
        pts += 1
    else:
        notes.append("J6 unknown 이 streak 를 보존하지 않음")

    return pts, notes


def _self_test(tmp: Path) -> int:
    """모델 실행 전 동결 시험.

    1) --json 이 없는 현재 저장소 구현은 반드시 0 점이어야 한다.
    2) 참조 구현(계약을 지킨 최소 패치)은 반드시 만점이어야 한다.

    둘 다 맞아야 채점기가 통과와 실패를 실제로 갈라낸다고 말할 수 있다.
    """
    repo = Path(__file__).resolve().parent.parent.parent.parent
    base = repo / "scripts" / "audit_model_inventory.py"
    pts_before, _ = score("selftest_before", base, tmp)

    ref = tmp / "reference_audit.py"
    ref.write_text(_reference_source(base), encoding="utf-8")
    pts_after, notes_after = score("selftest_after", ref, tmp)

    print(f"자체 시험  현재 구현 {pts_before}/{MAX_SCORE} (0 이어야 함)")
    print(f"자체 시험  참조 구현 {pts_after}/{MAX_SCORE} (만점이어야 함)  {'; '.join(notes_after)}")
    ok = pts_before == 0 and pts_after == MAX_SCORE
    print("동결 가능" if ok else "동결 불가: 채점기가 통과와 실패를 가르지 못합니다")
    return 0 if ok else 2


def _reference_source(base: Path) -> str:
    """현재 구현에 --json 을 덧붙인 참조 구현을 만듭니다. 채점기 검증 전용입니다."""
    src = base.read_text(encoding="utf-8")
    src = src.replace(
        'parser.add_argument("--quiet", action="store_true", help="소멸 항목만 출력")',
        'parser.add_argument("--quiet", action="store_true", help="소멸 항목만 출력")\n'
        '    parser.add_argument("--json", action="store_true", dest="as_json")',
        1,
    )
    hook = """
    if getattr(args, "as_json", False):
        pools = {}
        history = _load_history(state_path)
        for pool_name, info in sorted(MODEL_POOL.items()):
            if not info["suitable_for"]:
                pools[pool_name] = {"status": "skipped", "streak": 0}
                continue
            entry = history.get(pool_name) or {}
            status = entry.get("status", "unknown")
            streak = int(entry.get("counter") or 0) if status == "absent" else 0
            if status == "unknown":
                streak = int(entry.get("counter") or 0)
            pools[pool_name] = {"status": status, "streak": streak}
        extinct = sum(1 for v in pools.values() if v["streak"] >= 3)
        print(json.dumps({"extinct": extinct, "pools": pools}, ensure_ascii=False))
        return 1 if extinct else 0

    for line in lines:"""
    src = src.replace("\n    for line in lines:", hook, 1)
    return src


def _parse(argv: list[str]):
    ap = argparse.ArgumentParser(description="builder_02 산출물 채점기")
    ap.add_argument("--tmp", default=None)
    ap.add_argument("--candidate", action="append", default=[], metavar="이름=경로")
    ap.add_argument("--self-test", action="store_true", dest="self_test")
    a = ap.parse_args(argv)
    tmp = Path(a.tmp) if a.tmp else Path(tempfile.mkdtemp(prefix="bakeoff2_"))
    tmp.mkdir(parents=True, exist_ok=True)
    cands = []
    for spec in a.candidate:
        if "=" not in spec:
            ap.error(f"--candidate 는 이름=경로 형식입니다: {spec}")
        name, _, path = spec.partition("=")
        cands.append((name, Path(path)))
    return tmp, cands, a.self_test


def main(argv: list[str] | None = None) -> int:
    tmp, candidates, self_test = _parse(sys.argv[1:] if argv is None else argv)
    if self_test:
        return _self_test(tmp)
    if not candidates:
        print("채점할 후보가 없습니다. --candidate 이름=경로 를 지정하십시오.")
        return 2
    worst = 0
    for name, script in candidates:
        if not script.is_file():
            print(f"{name:24} 없음 {script}")
            worst = max(worst, 2)
            continue
        try:
            pts, notes = score(name, script, tmp)
        except Exception as exc:
            print(f"{name:24} 오류 {type(exc).__name__}: {exc}")
            worst = max(worst, 1)
            continue
        print(f"{name:24} {pts}/{MAX_SCORE}  {'; '.join(notes) if notes else '전항목 통과'}")
        if pts < MAX_SCORE:
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
