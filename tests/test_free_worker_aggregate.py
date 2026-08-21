#!/usr/bin/env python3
"""benchmarks/free_workers/aggregate.py 회귀 테스트"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# 저장소 루트를 파일 위치에서 유도합니다. 절대 경로를 박으면 격리 워크트리에서
# 검증해도 주 저장소의 옛 코드가 실행되어 통과가 무의미해집니다.
REPO_ROOT = Path(__file__).resolve().parents[1]


def run_aggregate(runs_content: str, scores_content: str) -> tuple[int, dict | None, str]:
    """aggregate.py를 실행하고 (exit_code, parsed_json, stderr)를 반환"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        runs_file = tmpdir / "results.tsv"
        scores_file = tmpdir / "scores.txt"
        out_file = tmpdir / "out.json"

        runs_file.write_text(runs_content, encoding="utf-8")
        scores_file.write_text(scores_content, encoding="utf-8")

        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "benchmarks/free_workers/aggregate.py",
                "--runs",
                str(runs_file),
                "--scores",
                str(scores_file),
                "--out",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

        parsed = None
        if out_file.exists():
            parsed = json.loads(out_file.read_text(encoding="utf-8"))

        return result.returncode, parsed, result.stderr


def test_contamination_detection():
    """exit_code==124 이면서 commits>=1 인 회차가 있으면 스택이 오염으로 판정된다"""
    runs = """oc_nemo3ultra_r1\t124 720\t0
oc_nemo3ultra_r2\t124 720\t2
oc_nemo3ultra_r3\t0 594\t2"""
    scores = """oc_nemo3ultra_r1 6/6
oc_nemo3ultra_r2 6/6
oc_nemo3ultra_r3 6/6"""

    code, out, _ = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None

    # 스택 레벨
    stack = next(s for s in out["stacks"] if s["stack"] == "oc_nemo3ultra")
    assert stack["contaminated"] is True
    assert stack["trustworthy"] is False

    # run 레벨: r2만 contaminated=True
    run_r2 = next(r for r in out["runs"] if r["rep"] == 2)
    assert run_r2["contaminated"] is True
    assert run_r2["contamination_reason"] is not None

    run_r1 = next(r for r in out["runs"] if r["rep"] == 1)
    assert run_r1["contaminated"] is False  # commits=0 이므로

    run_r3 = next(r for r in out["runs"] if r["rep"] == 3)
    assert run_r3["contaminated"] is False  # exit_code=0 이므로

    # limitations 맨 앞에 오염 문장
    assert "오염 확인" in out["limitations"][0]
    assert "oc_nemo3ultra" in out["limitations"][0]


def test_p95_all_sec_excludes_normal_failure():
    """정상 종료했으나 실패한 회차(no_commit, score)는 p95_all_sec에서 제외된다"""
    # mimo_r1: exit_code=0, elapsed=67, commits=0 -> no_commit 실패
    # mimo_r2: exit_code=0, elapsed=512, commits=1, score=6/6 -> 성공
    # mimo_r3: exit_code=0, elapsed=399, commits=1, score=6/6 -> 성공
    # p95_all_sec은 성공 회차(512, 399)만으로 계산해야 함 -> 506
    # 예전 버그: all_times에 67이 들어가서 p95_all_sec=501 < p95_success_sec=506
    runs = """mimo_r1\t0 67\t0
mimo_r2\t0 512\t1
mimo_r3\t0 399\t1"""
    scores = """mimo_r1 0/6
mimo_r2 6/6
mimo_r3 6/6"""

    code, out, _ = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None

    stack = next(s for s in out["stacks"] if s["stack"] == "mimo")
    # p95_all_sec >= p95_success_sec 이어야 함 (낙관적 편향 제거)
    assert stack["p95_all_sec"] >= stack["p95_success_sec"]
    # 성공 회차 elapsed: 512, 399 -> median=456, p95=506
    assert stack["p95_success_sec"] == 506
    assert stack["p95_all_sec"] == 506


def test_p95_all_sec_includes_timeout():
    """시한 초과 회차(exit_code=124)는 p95_all_sec에 절단 관측으로 포함된다"""
    runs = """stackA_r1\t0 100\t1
stackA_r2\t124 720\t0
stackA_r3\t0 200\t1"""
    scores = """stackA_r1 6/6
stackA_r2 6/6
stackA_r3 6/6"""

    code, out, _ = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None

    stack = next(s for s in out["stacks"] if s["stack"] == "stackA")
    # 성공 elapsed: 100, 200 -> p95 = 100 + (200-100)*0.95 = 195
    # 전체 (성공+타임아웃): 100, 200, 720 -> p95 = 200 + (720-200)*0.9 = 668
    assert stack["p95_success_sec"] == 195
    assert stack["p95_all_sec"] == 668


def test_denominator_mismatch_rejected():
    """같은 스택 내에서 채점 분모가 다르면 종료 코드 2로 거부"""
    runs = """stackX_r1\t0 100\t1
stackX_r2\t0 200\t1"""
    # r1은 6점 만점, r2는 5점 만점 -> 분모 불일치
    scores = """stackX_r1 5/6
stackX_r2 4/5"""

    code, out, stderr = run_aggregate(runs, scores)
    assert code == 2
    assert out is None
    assert "채점 분모가 다릅니다" in stderr
    assert "stackX" in stderr


def test_denominator_match_accepted():
    """같은 스택 내에서 채점 분모가 같으면 정상 동작"""
    runs = """stackY_r1\t0 100\t1
stackY_r2\t0 200\t1"""
    scores = """stackY_r1 5/6
stackY_r2 4/6"""

    code, out, stderr = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None
    assert stderr == ""


def test_reconstruct_tsv_scores_from_json():
    """결과 JSON의 runs 배열에서 tsv와 scores를 역산 복원할 수 있다"""
    # 원본 JSON 읽기
    json_path = Path(
        "/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/"
        "benchmarks/free_workers/results/2026-08-20-builder_02.json"
    )
    original = json.loads(json_path.read_text(encoding="utf-8"))

    # runs -> tsv 복원
    tsv_lines = []
    scores_lines = []
    for r in original["runs"]:
        tag = f"{r['stack']}_r{r['rep']}"
        rc = r["exit_code"]
        elapsed = r["elapsed_sec"] if r["elapsed_sec"] is not None else ""
        commits = r["commits"]
        tsv_lines.append(f"{tag}\t{rc} {elapsed}\t{commits}")

        score = r["score"]
        if score:
            scores_lines.append(f"{tag} {score}")

    tsv_content = "\n".join(tsv_lines) + "\n"
    scores_content = "\n".join(scores_lines) + "\n"

    # 복원한 데이터로 다시 집계
    code, out, _ = run_aggregate(tsv_content, scores_content)
    assert code == 0
    assert out is not None

    # 핵심 필드들이 원본과 일치하는지 확인
    assert len(original["stacks"]) == len(out["stacks"])
    for orig_stack, new_stack in zip(original["stacks"], out["stacks"]):  # noqa: B905
        assert orig_stack["stack"] == new_stack["stack"]
        assert orig_stack["success"] == new_stack["success"]
        assert orig_stack["success_rate"] == new_stack["success_rate"]
        assert orig_stack["median_success_sec"] == new_stack["median_success_sec"]
        assert orig_stack["p95_success_sec"] == new_stack["p95_success_sec"]
        assert orig_stack["p95_all_sec"] == new_stack["p95_all_sec"]
        assert orig_stack["contaminated"] == new_stack["contaminated"]
        assert orig_stack["trustworthy"] == new_stack["trustworthy"]


def test_clean_stack_trustworthy_true():
    """오염 없는 스택은 trustworthy: true"""
    runs = """clean_stack_r1\t0 100\t1
clean_stack_r2\t0 200\t1
clean_stack_r3\t0 150\t1"""
    scores = """clean_stack_r1 6/6
clean_stack_r2 6/6
clean_stack_r3 6/6"""

    code, out, _ = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None

    stack = next(s for s in out["stacks"] if s["stack"] == "clean_stack")
    assert stack["contaminated"] is False
    assert stack["trustworthy"] is True


def test_multiple_stacks_only_contaminated_gets_warning():
    """여러 스택 중 오염된 것만 limitations에 경고 추가"""
    runs = """clean_stack_r1\t0 100\t1
clean_stack_r2\t0 200\t1
dirty_stack_r1\t124 720\t0
dirty_stack_r2\t124 720\t2
dirty_stack_r3\t0 500\t2"""
    scores = """clean_stack_r1 6/6
clean_stack_r2 6/6
dirty_stack_r1 6/6
dirty_stack_r2 6/6
dirty_stack_r3 6/6"""

    code, out, _ = run_aggregate(runs, scores)
    assert code == 0
    assert out is not None

    # dirty_stack만 contaminated
    dirty = next(s for s in out["stacks"] if s["stack"] == "dirty_stack")
    clean = next(s for s in out["stacks"] if s["stack"] == "clean_stack")
    assert dirty["contaminated"] is True
    assert dirty["trustworthy"] is False
    assert clean["contaminated"] is False
    assert clean["trustworthy"] is True

    # limitations에 dirty_stack 경고만 한 번
    assert "오염 확인" in out["limitations"][0]
    assert "dirty_stack" in out["limitations"][0]
    # 오염 문장은 하나만 추가됨 (첫 번째 항목만)
    contamination_count = sum(1 for lim in out["limitations"] if "오염 확인" in lim)
    assert contamination_count == 1


if __name__ == "__main__":
    test_contamination_detection()
    print("✓ test_contamination_detection passed")

    test_p95_all_sec_excludes_normal_failure()
    print("✓ test_p95_all_sec_excludes_normal_failure passed")

    test_p95_all_sec_includes_timeout()
    print("✓ test_p95_all_sec_includes_timeout passed")

    test_denominator_mismatch_rejected()
    print("✓ test_denominator_mismatch_rejected passed")

    test_denominator_match_accepted()
    print("✓ test_denominator_match_accepted passed")

    test_reconstruct_tsv_scores_from_json()
    print("✓ test_reconstruct_tsv_scores_from_json passed")

    test_clean_stack_trustworthy_true()
    print("✓ test_clean_stack_trustworthy_true passed")

    test_multiple_stacks_only_contaminated_gets_warning()
    print("✓ test_multiple_stacks_only_contaminated_gets_warning passed")

    print("\n모든 테스트 통과!")
