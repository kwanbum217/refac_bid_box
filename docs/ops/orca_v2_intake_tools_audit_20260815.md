# Orca v2 코디네이터 수신면 도구 독립 감사 보고서

> **작성일**: 2026-08-15
> **작성자**: Orca Dispatched Reviewer (task_3a80e902743a)
> **감사 대상**: 커밋 c381075..de26b3f 병합분 (코디네이터 수신면 도구 4개 및 테스트)
> **대상 파일**: `scripts/orca_contract.py`, `scripts/orca_level1_gate.py`, `scripts/summarize_worker_done.py`, `scripts/orca_metrics_ledger.py`, `scripts/validate_review_report.py`
> **규약 문서**: [`docs/ops/orca_task_capsule_v2.md`](orca_task_capsule_v2.md), [`docs/ops/orca_v2_metrics_ledger.md`](orca_v2_metrics_ledger.md)

---

## 1. 감사 개요 및 방법

본 감사는 2026-08-15 `main`에 병합된 코디네이터 수신면 도구 4종에 대한 Level 2 독립 감사 작업입니다. 대상 코드는 코디네이터 1인의 검토만 거쳐 병합되었으며, 이후 모든 Task의 통과/반려/지표 산출의 기준이 되므로 기계적 실행 재현을 통해 논리적 결함을 검증했습니다.

### 1.1 감사 대상 및 원칙
- **코드 수정 금지**: 본 감사는 결함을 확인하더라도 코드를 직접 수정하지 않고, 재현 명령과 실제 출력을 명시하여 보고합니다.
- **실행 기반 검증**: 정적 코드 분석(읽기)뿐만 아니라, `python3 -c` 및 단위 스크립트 실행을 통해 경계값과 예외 상황을 직접 재현했습니다.

---

## 2. 체크리스트 판정 요약

| ID | 검사 항목 요약 | 판정 (Defect) | 확인 방법 | 결과 요약 |
| --- | --- | --- | --- | --- |
| **C1** | `matches_any` / `scope_excess` 허용 범위 과대 판정 | **YES (결함)** | 실행 검증 | `..` 경로 탐색 허용, 빈 문자열 `""` 매칭 결함 |
| **C2** | `parse_capsule_list` 인접 필드 오흡수 및 항목 누락 | **YES (결함)** | 실행 검증 | 따옴표 내 `#` 절단, 0열 주석 시 블록 조기 종료 |
| **C3** | `orca_level1_gate.py` 실패를 통과로 오판하는 경로 | **NO (정상)** | 실행/코드 | `code == 0` 종료 코드로 판정하여 오류 누락 없음 |
| **C4** | `orca_level1_gate.py` 사람 출력이 max-chars 초과 | **YES (결함)** | 실행 검증 | `ContractError` 미포획으로 stderr 트레이스백 유출 |
| **C5** | `summarize_worker_done.py` 계약 위반 누락 | **YES (결함)** | 실행 검증 | 문자열 `"0"` 미검출, dict형 blocking 누락, verdict 검증 부재 |
| **C6** | `orca_metrics_ledger.py` append-only 및 중복 방지 파괴 | **YES (결함)** | 실행 검증 | 파일 락 부재로 동시 실행 시 중복 기록, 손상행 건너뜀 |
| **C7** | `orca_metrics_ledger.py` summary 집계 수치 왜곡 | **YES (결함)** | 실행 검증 | `bool` (`True`/`False`)이 `1.0`/`0.0`으로 수치 집계에 합산 |
| **C8** | 도구 간 판정 출처 불일치 및 결과 괴리 | **YES (결함)** | 실행 검증 | git diff vs 보고서 JSON 출처 괴리, verdict 격하 미반영 |
| **C9** | 테스트 픽스처와 실제 운영 입력 괴리 | **YES (결함)** | 실행 검증 | YAML multiline (`>`), 따옴표 포함 시 파싱 실패 |
| **C10** | 추가 동작 결함 확인 | **YES (결함)** | 실행 검증 | `validate_review_report` 서브스트링 충돌, `--since` 누락일자 포함 |

---

## 3. 확인된 결함 상세 및 재현 증거

### [C1] matches_any 및 scope_excess 경로 정규화 미비로 인한 범위 초과 미검출
- **결함 내용**: `_strip_leading_dot_slash`가 `..` 디렉터리 탐색을 정규화(`os.path.normpath`)하지 않아 `scripts/...` 허용 패턴에 `scripts/../../secret.py`가 허용(True)으로 판정됩니다. 또한 빈 문자열 경로 `""`가 `*` 및 `**` 패턴에 True로 매칭됩니다.
- **재현 명령**:
```bash
python3 -c '
from scripts.orca_contract import matches_any, scope_excess
print("traversal:", matches_any("scripts/../../secret.py", ["scripts/..."]))
print("empty_path:", matches_any("", ["*"]))
print("scope_excess:", scope_excess(["scripts/../../secret.py"], ["scripts/..."]))
'
```
- **실제 출력**:
```text
traversal: True
empty_path: True
scope_excess: []
```

### [C2] parse_capsule_list 문자열 내 `#` 절단 및 0열 주석 블록 조기 종료
- **결함 내용**:
  1. `re.sub(r"\s+#.*$", "", value)`가 따옴표 내부의 `#`까지 주석으로 간주해 잘라냅니다 (`"- \"src/file #1.py\""` -> `"src/file"`).
  2. 블록 탐색 정규식 `(?=^\S|\Z)`가 0열의 `# 주석`에 매칭되어, 주석 이후의 리스트 항목이 통째로 누락됩니다.
- **재현 명령**:
```bash
python3 -c '
from scripts.orca_contract import parse_capsule_list
yaml_text = """allowed_read_files:
  - "src/file #1.py"
# 중간 주석
  - "src/file2.py"
"""
print("parsed:", parse_capsule_list(yaml_text, "allowed_read_files"))
'
```
- **실제 출력**:
```text
parsed: ['src/file']
```

### [C4] orca_level1_gate.py ContractError 미포획으로 인한 max-chars 초과 트레이스백 출력
- **결함 내용**: `run_level1_gate`는 `GateToolError`만 `except`로 잡고 있습니다. `load_capsule`이나 `load_report`에서 발생하는 `ContractError` 또는 JSON 파싱 예외가 발생하면 예외가 상위로 전파되어 `truncate(..., max_chars)` 없이 stderr로 장문의 트레이스백이 출력됩니다.
- **재현 명령**:
```bash
python3 -c '
import tempfile
from pathlib import Path
from scripts.orca_level1_gate import run_level1_gate
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    c = p / "capsule.yaml"; c.write_text("schema: ORCA_TASK_CAPSULE_V2\n", encoding="utf-8")
    r = p / "bad.json"; r.write_text("invalid json " + "A"*2000, encoding="utf-8")
    run_level1_gate(capsule=c, review_report=r, max_chars=100)
'
```
- **실제 출력**:
```text
scripts.orca_contract.ContractError: 보고 JSON 파싱 실패: ... (수십 줄의 트레이스백 출력)
```

### [C5] summarize_worker_done.py 계약 위반 검증 누락 및 형식 불일치
- **결함 내용**:
  1. `commit_count`가 문자열 `"0"`으로 전달되면 `"0" == 0`이 `False`가 되어 규약 3.3 위반이 검출되지 않고 exit code 0으로 통과합니다.
  2. `blocking_issues`가 dict인 경우 `isinstance(..., list)` 검사에서 누락되어 digest에 전혀 표시되지 않고 `blocking_issues_count`가 0으로 보고됩니다.
  3. `verdict`가 `"succeeded"` 등 비표준 값일 때 `declared_verdict in ("pass", "candidate")` 조건에 걸리지 않아 `blocking_issues`가 있어도 격하되지 않고 exit code 0으로 종료됩니다.
- **재현 명령**:
```bash
python3 -c '
import json, tempfile
from pathlib import Path
from scripts.summarize_worker_done import summarize_worker_report
with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "r.json"
    f.write_text(json.dumps({
        "schema": "ORCA_WORKER_DONE_V2", "version": "2.0.0", "task_id": "t1",
        "status": "succeeded", "branch": "b", "commit": "c", "commit_count": "0",
        "changed_files": ["a.py"], "read_files": [], "verification": [],
        "verdict": "succeeded", "blocking_issues": {"id": "C1"}
    }))
    res = summarize_worker_report(f)
    print("exit_code:", res["exit_code"])
    print("violations:", res["violations"])
    print("blocking_count:", res["blocking_issues_count"])
'
```
- **실제 출력**:
```text
exit_code: 0
violations: []
blocking_count: 0
```

### [C6] orca_metrics_ledger.py 동시 실행 시 원장 중복 및 손상 행 건너뜀
- **결함 내용**:
  1. 파일 락(`flock`)이 없어 동일한 `(task_id, dispatch_id)`를 가진 2개 프로세스가 동시에 `record`를 실행할 경우 중복 방지를 통과하여 원장에 중복 기록됩니다.
  2. `_load_rows`가 손상 행을 건너뛰므로, 손상 행에 기록되어 있던 `(task_id, dispatch_id)`는 중복 검사에서 제외되어 재기록됩니다.
- **재현 명령**:
```bash
python3 -c '
import tempfile, json, subprocess, sys
from pathlib import Path
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    ledger = t / "ledger.jsonl"
    cap = t / "capsule.yaml"; cap.write_text("schema: ORCA_TASK_CAPSULE_V2\nversion: \"2.1.0\"\nmode: worker\nrun_id: r1\ntask_id: t1\nallowed_read_files: []\nallowed_write_files: []\nreturn_contract: ORCA_WORKER_DONE_V2\n")
    rep = t / "report.json"; rep.write_text(json.dumps({"schema":"ORCA_WORKER_DONE_V2","version":"2.1.0","status":"succeeded","verdict":"pass","read_files":[],"changed_files":[],"verification":[],"commit_count":0,"blocking_issues":[]}))
    cmd = [sys.executable, "scripts/orca_metrics_ledger.py", "--ledger", str(ledger), "record", "--run", "r1", "--task", "t1", "--dispatch", "d1", "--role", "builder", "--model", "m1", "--capsule", str(cap), "--report", str(rep)]
    p1 = subprocess.Popen(cmd); p2 = subprocess.Popen(cmd)
    p1.wait(); p2.wait()
    print("ledger rows count:", len(ledger.read_text().strip().splitlines()))
'
```
- **실제 출력**:
```text
ledger rows count: 2
```

### [C7] orca_metrics_ledger.py boolean 값을 float(1.0/0.0)으로 오인 집계
- **결함 내용**: `_collect_numeric`에서 `float(v)` 변환 시 Python의 `float(True) == 1.0`, `float(False) == 0.0` 특성으로 인해 boolean 플래그가 수치 지표의 유효 표본으로 둔갑하여 평균/중앙값을 왜곡합니다.
- **재현 명령**:
```bash
python3 -c '
from scripts.orca_metrics_ledger import _collect_numeric
rows = [{"roundtrips": True}, {"roundtrips": False}, {"roundtrips": 5}]
print("collected:", _collect_numeric(rows, "roundtrips"))
'
```
- **실제 출력**:
```text
collected: [1.0, 0.0, 5.0]
```

### [C8] 도구 간 changed_files 출처 불일치 및 verdict 격하 미반영 괴리
- **결함 내용**:
  1. `orca_level1_gate.py`(게이트 2)는 `git diff`에서 실제 변경 파일을 읽지만, `summarize_worker_done.py`는 워커가 보고서 JSON에 자진 신고한 `changed_files`를 읽습니다. 워커가 임의 파일을 수정하고 보고서에서 누락하면 게이트 2는 `fail`이나 `summarize_worker_done`은 `pass`로 판정합니다.
  2. `orca_metrics_ledger.py`는 `summarize_worker_done.py`가 수행하는 verdict 격하(`candidate`/`pass` -> `blocked`)를 적용하지 않고 보고서 원본 verdict를 그대로 기록합니다.
- **재현 명령**:
```bash
python3 -c '
import json, tempfile
from pathlib import Path
from scripts.orca_level1_gate import run_gate2_scope
from scripts.summarize_worker_done import summarize_worker_report
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    c = p / "capsule.yaml"; c.write_text("schema: ORCA_TASK_CAPSULE_V2\nallowed_write_files:\n  - a.py\n")
    r = p / "report.json"; r.write_text(json.dumps({"schema":"ORCA_WORKER_DONE_V2","version":"2.0.0","task_id":"t1","status":"succeeded","branch":"b","commit":"c","commit_count":1,"changed_files":["a.py"],"read_files":[],"verification":[],"verdict":"candidate","blocking_issues":[]}))
    g2 = run_gate2_scope(["a.py", "unauthorized.py"], c)
    s = summarize_worker_report(r, c)
    print("Gate 2 status (git):", g2.status)
    print("Summarize exit_code (json):", s["exit_code"])
'
```
- **실제 출력**:
```text
Gate 2 status (git): fail
Summarize exit_code (json): 0
```

### [C9] YAML 블록 스칼라(`>`) 및 따옴표 포함 문자열 파싱 실패
- **결함 내용**:
  1. `validate_review_report.py`의 `parse_checklist`가 YAML folded scalar(`question: >`)를 파싱할 때 질문 본문을 버리고 `">"`만 추출합니다.
  2. 질문 내부에 큰따옴표가 이스케이프 또는 직접 포함된 경우 정규식 매칭이 실패하여 `question` 필드 자체가 누락됩니다.
  3. `parse_capsule_scalar` 또한 `objective: >` 형태의 다중 행 스칼라를 `">"`로 읽습니다.
- **재현 명령**:
```bash
python3 -c '
from scripts.validate_review_report import parse_checklist
capsule = """review_checklist:
  - id: "C1"
    question: >
      다중 행으로 작성된
      질문 본문입니다.
    defect_when: "yes"
  - id: "C2"
    question: "verdict 가 \"succeeded\" 일 때"
    defect_when: "yes"
"""
print("parsed checklist:", parse_checklist(capsule))
'
```
- **실제 출력**:
```text
parsed checklist: [{'id': 'C1', 'question': '>', 'defect_when': 'yes'}, {'id': 'C2', 'defect_when': 'yes'}]
```

### [C10] validate_review_report 서브스트링 충돌 및 metrics_ledger 날짜 필터 결함
- **결함 내용**:
  1. `validate_review_report.py`의 `evaluate()`가 `if item["id"] not in blocking_text:`로 단순 문자열 포함 여부를 검사합니다. `C1` 항목이 결함인데 `blocking_issues`에 `C10`만 있는 경우, `"C1" in '["C10"]'`이 `True`가 되어 `C1` 누락 위반을 감지하지 못합니다.
  2. `orca_metrics_ledger.py`의 `summary --since`에서 날짜가 비어있거나 형식 오류인 행을 예외 처리(`except ValueError`/`else`) 시 필터에서 배제하지 않고 결과에 포함시킵니다.
- **재현 명령**:
```bash
python3 -c '
from scripts.validate_review_report import evaluate
chk = [{"id": "C1", "question": "q1", "defect_when": "yes"}, {"id": "C10", "question": "q10", "defect_when": "yes"}]
rep = {"verdict": "fail", "checklist_results": [{"id": "C1", "answer": "yes", "evidence": "broken"}, {"id": "C10", "answer": "no", "evidence": "ok"}], "blocking_issues": ["C10 is broken"]}
res = evaluate(chk, rep)
print("C1 누락 감지 여부 (ok should be False):", res["ok"])
'
```
- **실제 출력**:
```text
C1 누락 감지 여부 (ok should be False): True
```

---

## 4. 정상 판정 항목 확인 내역

### [C3] orca_level1_gate.py pytest 실패 누락 여부
- **확인 결과**: `run_gate3_tests`는 요약 텍스트의 "failed" 문자열 매칭에만 의존하지 않고, 실행 프로세스의 `proc.returncode == 0`을 기준으로 `passed` 여부를 결정합니다.
- 수집 오류(exit code 2), 테스트 0건(exit code 5), 출력 공백(exit code 1) 등 비정상 종료 시 모두 `code != 0`이 되어 `overall_status = "fail"`로 정상 처리됨을 확인했습니다.

---

## 5. 잔여 위험 요소 (Remaining Risks)

1. **Working Tree 미커밋 변경 감지 부재**: `orca_level1_gate.py`의 `get_git_changed_files`는 `git diff base...branch` 및 `git ls-tree`만 사용하므로, 워커 워크트리에 커밋되지 않은 스테이징/미추적 파일은 검증 대상에서 누락될 위험이 있습니다.
2. **원장 대용량 파일 파싱 부하**: `orca_metrics_ledger.py`는 원장 전체를 한 번에 읽어 메모리에서 집계하므로, Dispatch 행이 수만 건 이상 누적될 경우 스트리밍 파싱 도입이 필요할 수 있습니다.

---

## 6. 결론

코디네이터 수신면 도구 4종 및 검증 헬퍼를 감사한 결과, 10개 체크리스트 항목 중 **9개 항목(C1, C2, C4, C5, C6, C7, C8, C9, C10)에서 동작 결함이 확인**되었습니다.

본 감사는 감사 전용 작업이므로 코드를 임의 수정하지 않고 본 보고서 및 `ORCA_REVIEW_DONE_V2`(`verdict: fail`)로 보고를 완료합니다.
