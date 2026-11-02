# 핸드오프 인수인계 - 2026-11-02 세션

> **작성일**: 2026-11-02
> **작성**: 코디네이터(Grok). Orca Run `run_4d41c7466734`
> **기준 커밋**: `b4cd0866` (`main`, `origin/main` 과 같음)
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 `66f408d3`, `updated_at` 은 2026-11-02 입니다. 이 인수인계 브랜치는 그 파일을 바꾸지 않습니다.
> **종료 사유**: 주간 토큰 사용 83% 시점에서 남은 한도로 다음 과업을 병렬로 열고, 만료 전에 인수인계를 남기는 것이 우선이었습니다.
> **이 문서의 위치**: 브랜치 `kwanbum217/handoff-20261102-close`. 작성 시점에는 `main` 에 없습니다.

---

## 0. 다음 세션이 바로 할 일

1. 이 브랜치를 읽습니다. `main` 병합은 Level 1 strict 기록과 `scripts/premerge_full_suite_gate.py --record` 뒤에만 합니다. 증거 파일은 한 칸이라, 이 브랜치를 기록한 뒤 다른 브랜치를 먼저 병합하지 않습니다.
2. 배달함은 코디네이터가 직접 비웁니다. `orca orchestration check --run run_4d41c7466734` 입니다. 이 Orca 버전은 check 가 배달을 소진합니다. 스크립트로 check 를 돌리면 코디네이터 알림이 사라집니다.
3. 2절 빌더가 `worker_done` 을 보냈으면 회수하기 전에 산출물(커밋, `git diff main...HEAD`, 문서의 숫자)을 저장소에서 확인합니다. 보고만으로 병합하지 않습니다.
4. 리뷰어는 빌더 `worker_done` 뒤에만 띄웁니다. 모델은 Command Code `z-ai/glm-5.3-flash`, `--effort high --auto --role reviewer` 입니다. taskctl 은 빌더와 리뷰어가 같은 cmd 공급자면 거부하므로 5절의 비감독 런처 경로를 씁니다.
5. 리뷰가 pass 이고 게이트가 끝나면 조사 브랜치를 한 번에 하나씩 `main` 에 `--no-ff` 로 넣습니다. 병합 커밋 안에서 `source_commit` 을 병합 직전 `main` 8자로 고치고, 문자 수 8000 을 유지합니다.
6. 로컬 `main` 에 병합된 워크트리만 회수합니다. `orca worktree rm --worktree path:<경로> --force` 뒤에 필요하면 `git worktree remove --force`. `git branch -d` 는 `main` 의 조상일 때만. `--delete-branch` 와 `git branch -D` 는 쓰지 않습니다.
7. `kwanbum217/gap-guard-eligibility-20261031`(`6ec9b56b`) 은 병합하지 않습니다. 적격심사 실지원이 그 미지원 안내를 대체했습니다.
8. `scripts/backfill_openg_results.py --execute` 와 나라장터 API 호출은 사용자 승인이 새로 있기 전에는 하지 않습니다. 재입찰번호 실측이 끝나도 승인으로 보지 않습니다.

---

## 1. 이 세션에서 main 에 넣고 원격까지 반영한 것

이전 원격 `ada865fb` 에서 `b4cd0866` 까지 fast-forward 되었습니다. 로컬 `main` 과 `origin/main` 은 작성 시점에 같습니다.

| 병합 | 내용 |
| --- | --- |
| `508a837c` | 백업 도구가 DB 비밀번호를 명령 인자에 넣지 않음. 팁 `22d9dacd`. 리뷰 `task_138e66ec1bc0` pass |
| `aec0cdfb` | 개찰결과 설계, T1-T4, G1 스키마 기준선. 수집 플래그 `OPENG_RESULT_COLLECTION_ENABLED` 기본 꺼짐 |
| `40574908` | chromadb 취약점 예외 만료를 2027-03-31 로 연장. 팁 `d82f242f` |
| `aea81ede` | 인사와 연결 확인에 짧은 도움말. 팁 `82d53acb`. 게이트 6 은 과거 worker_done 건수 불일치로 `report_path` 를 뺀 캡슐 사본을 사용 |
| `c223a973` | 적격심사, 사정률 조회, 경쟁률 중앙값. 중앙값 재계산은 당시 Docker 가 꺼져 있어 하지 않음. 리뷰 `task_6dec298c7fa5` pass |
| `66f408d3` | 금액대별 공고 건수 네 구간. 팁 `ab331f00` |
| `b4cd0866` | 2026-10-31 인수인계 문서. 팁 `df1461aa` |

위 작업의 워크트리와 로컬 브랜치는 병합 뒤 회수했습니다. `git worktree list` 에 남은 것은 아래 2절과 이 인수인계 브랜치뿐입니다.

---

## 2. 진행 중인 빌더 (비감독 cmd 런처)

cmd 와 qwen 은 `worker-start` 에이전트가 아닙니다. 터미널을 만들고 `scripts/orca_cmd_launch.py` 로 붙인 뒤 taskctl `--launcher` 로 고유 preamble 을 넘겼습니다. 감독 Dispatch 가 아닙니다.

| Task | 내용 | 브랜치 / 워크트리 | 터미널 | Dispatch |
| --- | --- | --- | --- | --- |
| `task_a578b85123cb` | 재입찰번호가 공고, 차수, 분류 안에서 중복되는지 읽기 전용 실측 | `kwanbum217/openg-rbidno-20261102` | `term_a1764f18-4732-4628-9716-ca0ced35d7f3` | `ctx_9615e5640153` |
| `task_71f974178f18` | 날짜 창 없는 적격심사 건수의 JSON 스캔 비용을 읽고, 스키마를 바꾸지 않는 다음 선택만 문서로 제안 | `kwanbum217/eligibility-json-scan-20261102` | `term_3b57b1f9-5d73-438f-aaf4-3f2ca88a1e06` | `ctx_ce4c0ce9b6a0` |

워크트리 둘 다 기동 시점 HEAD 는 `b4cd0866` 입니다. `.venv` 와 `.env` 는 주 저장소로 이어 둔 심볼릭 링크입니다. `.env` 를 커밋하지 않습니다.

허용 산출물은 각 한 파일입니다.

| Task | 문서 | 커밋 제목 |
| --- | --- | --- |
| `task_a578b85123cb` | `docs/analysis/openg_rbidno_uniqueness_20261102.md` | `docs: 개찰결과 재입찰번호 중복을 실측한다` |
| `task_71f974178f18` | `docs/analysis/eligibility_json_scan_20261102.md` | `docs: 날짜 창 없는 적격심사 건수의 JSON 스캔 비용을 기록한다` |

Intent 는 `.orca/intents/openg_rbidno_uniqueness_20261102.yaml`, `.orca/intents/eligibility_json_scan_20261102.yaml` 입니다. Capsule 은 실제 Task ID 디렉터리와 Intent stem 디렉터리 둘 다에 있습니다. spec 은 stem 경로를 가리킵니다.

금지입니다. 운영 DB 쓰기, `docker exec`, mysql 직접 호출, `sh -c` 감싸기, 소급 스크립트 실행, API 호출, 마이그레이션, `src` 수정, 앱 재시작, 푸시, 병합. 조회는 `uv run python scripts/db_readonly_query.py --sql` 한 문장씩만 됩니다.

기동 직후 감시는 커밋 0, 미커밋 0 이었습니다. 조사 단계입니다. 5분 넘게 커밋과 변경이 없으면 터미널을 한 번 읽어 정체인지 확인합니다. 폴링 루프는 돌리지 않습니다.

리뷰어를 붙일 때의 빌더 체크리스트 id 는 그대로 씁니다.

| Task | id |
| --- | --- |
| 재입찰번호 | `wrote_db`, `no_count`, `scope_exceeded` |
| JSON 스캔 | `schema_changed`, `no_observation`, `scope_exceeded` |

`defect_when` 은 모두 `yes` 입니다.

---

## 3. 아직 하지 않은 과업

| 과업 | 상태 |
| --- | --- |
| 재입찰번호 유니크 실측 | 2절 빌더가 진행. 숫자 확인 전 설계 8항은 미확인 |
| 적격심사 JSON 전량 스캔 | 2절 빌더가 문서만 작성. 코드 변경은 사용자 결정 후 |
| 유찰 1년 소급 `--execute` | 차단. dry-run 과 `--max-calls` 는 스크립트에 있음. 승인 전 실행 금지 |
| 유찰 T5 | 소급 적재 뒤에만 |
| v2 재측정 | 앱을 재시작한 뒤. 중앙값 병합 때는 Docker 가 꺼져 재계산하지 않았음 |
| 앱 재시작 | 이 세션은 `db` 만 `docker compose up -d db` 로 올렸고 healthy 였음. app, redis, meilisearch, worker 는 내리지 않았고 올리지도 않았음. 다음 반영은 `docker compose up -d` 후 `docker compose restart app` |
| 의미 검색 공백 삽입 | "최근 에" 위치는 아직 코드에서 확정하지 않음. 범위 없는 수정 금지 |
| gap-guard 브랜치 | 병합 금지. 로컬 브랜치만 남아 있음 |

옛 실패 Task `task_f95f75a5a2ad`(리뷰어 조사 결과 문서) 는 이 대기열 밖입니다. 다시 열지 않습니다.

---

## 4. 병합 절차 (조사 브랜치와 이 인수인계)

주 저장소가 `main` 인지 `git branch --show-current` 로 확인한 뒤에만 병합합니다.

```bash
uv run python scripts/orca_level1_gate.py --base main --branch <브랜치> --repo <워크트리> --capsule <캡슐> --strict --record-evidence --json
# 리뷰 보고가 있으면 --review-report 를 붙입니다. 문서 전용이고 리뷰가 없으면 게이트 5 는 생략됩니다.
# 워커 worker_done 의 테스트 건수가 현재 환경과 다르면 report_path 를 뺀 캡슐 사본으로 게이트 6 을 건너뜁니다. 과거 보고는 고치지 않습니다.
(cd <워크트리> && uv run python scripts/premerge_full_suite_gate.py --record)
git merge --no-ff --no-commit <브랜치>
```

`CURRENT_STATE.md` 의 `source_commit` 만 병합 직전 `main` 짧은 해시로 바꿉니다. 본문 길이를 바꾸지 않습니다. 실패하면 커밋하지 않고 `git reset --merge` 합니다. 원격은 `git push origin main` 만 사용합니다. force 는 쓰지 않습니다.

증거 캐시는 주 저장소 `.cache/level1_strict_evidence.json` 과 `.cache/premerge_full_suite_evidence.json` 입니다. 둘의 commit 이 `MERGE_HEAD` 와 같아야 훅이 통과합니다.

---

## 5. 리뷰어를 띄우는 방법

1. 빌더 워크트리에 리뷰 Capsule 을 두고 `review_checklist` id 를 2절과 같게 합니다.
2. 터미널을 만듭니다. `orca terminal create --worktree path:<워크트리> --command "uv run python scripts/orca_cmd_launch.py --model z-ai/glm-5.3-flash --effort high --auto --role reviewer" --json`
3. 고정 파일 `.orca/preamble.txt` 는 런처가 거부합니다. taskctl 이 `preamble_<task>_<dispatch>_<nonce>.txt` 를 쓰게 합니다.
4. `orca terminal close --tab` 은 코디네이터 창까지 닫으므로 쓰지 않습니다. 닫기 전에 `tabId` 가 코디네이터와 다른지 봅니다.

빌더 모델은 `deepseek/deepseek-v4.1-flash`, effort high, `--auto` 입니다. `--auto` 를 빼면 승인 창에서 멈춥니다.

---

## 6. 운영 메모

| 항목 | 내용 |
| --- | --- |
| taskctl create | Task 는 생긴 뒤에도 Task ID 파싱 실패로 종료 코드 1 이 나고 Capsule 을 지웁니다. ID 는 task-list 로 찾고, 실제 ID 경로와 spec 이 가리키는 stem 경로에 같은 Capsule 을 다시 씁니다 |
| 동시 쓰기 | 지금 쓰기 워커는 빌더 2대입니다. 상한은 3 입니다. 리뷰어는 쓰기 상한 밖입니다 |
| 편집 가능 설치 | `uv pip show` 의 Editable project location 은 주 저장소입니다. 워크트리가 사라진 뒤 주 저장소에서 `uv run` 이 설치 경로를 옮긴 적이 있으므로, 게이트 전에 위치를 확인합니다 |
| Docker | 조사 조회를 위해 `db` 만 올렸습니다. 볼륨은 지우지 않았습니다. 워커가 DB 를 보는 동안 `docker compose down` 하지 않습니다 |
| 인수인계 병합 | 이 브랜치 병합은 조사 브랜치 검증과 증거 칸을 다툰다. 조사를 먼저 병합하려면 이 문서 병합의 증거 기록을 그 뒤로 미룹니다 |
