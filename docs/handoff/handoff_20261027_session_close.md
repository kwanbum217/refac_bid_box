# 핸드오프 인수인계 - 2026-10-27 세션 종료

> **작성일**: 2026-10-27
> **작성**: 코디네이터(Grok). Orca Run `run_89eeda0fdf77`
> **기준 커밋**: `474def84` (main, 환경 의존 테스트 병합. CI `40459206540` success)
> **직전 인수인계**: [handoff_20261026_chatbot_wave2.md](handoff_20261026_chatbot_wave2.md)
> **종료 사유**: 사용자 지시. 16:20 컴퓨터 종료. 진행 중 검증은 중단하고 미병합 브랜치를 다음 세션으로 넘긴다.
> **Docker**: 종료 시점 데몬 소켓이 이미 없었다. 볼륨은 지우지 않았다.

---

## 0. 다음 세션이 바로 할 일

1. `docker compose up -d` 후 app, db, meilisearch, redis 가 healthy 이고 worker 가 up 인지 본다. 헬스 경로는 `/api/v1/health/ready` 다. `/health` 는 404 다.
2. 아래 1번 브랜치부터 엄격 레벨1과 전량 시험 증거를 다시 기록하고 `main` 에 `--no-ff` 병합한다. 이번 세션의 증거 파일은 이 브랜치 것이 아니다.
3. 2번 브랜치 리뷰는 이미 계약 통과다. 리뷰를 다시 시키지 말고 엄격 증거만 기록한 뒤 병합한다. 보고 파일이 워크트리에 없을 때만 리뷰어를 다시 붙인다.
4. 3번 진단 문구 수정은 1번이 `main` 에 들어간 뒤에만 `query_planning.py` 를 연다.
5. 10.5 결정(약칭, 공고명 낱말 건수, 명사구, 빠른 실행, 자격 필터, v3)은 사용자 결정 전이라 착수하지 않는다.

병합 직전 `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 그 병합 직전 `main` HEAD 8자로 바꾼다. `updated_at` 은 그 날로 둔다. 본문은 8000자 상한에 붙어 있어(이번 세션 실측 7994자) 문장을 더하면 검증이 실패한다. 길이를 유지한 채 날짜와 해시만 바꾼다.

---

## 1. 미병합: 범위 목록 재작업

| 항목 | 값 |
| --- | --- |
| 브랜치 | `kwanbum217/scoped-list-rework-20261027` |
| 커밋 | `cf970586` `fix: 마감 기한 표지가 범위 공고 목록으로 올라가지 않게 한다` |
| 워크트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/scoped-list-rework-20261027` |
| 빌더 | `task_928a7c0381bb`, dispatch `ctx_d3c65c164f68`. 터미널은 회수함 |
| 리뷰 | `task_05cb8f0217ed`, dispatch `ctx_17127f68a5bc`. 계약 검사 실효 pass. 터미널은 닫음 |
| 파일 | `src/rag/query_planning.py`, `tests/test_scoped_list_request.py` |
| 비엄격 레벨1 | 통과. 리뷰 항목은 엄격 모드가 아니라 건너뜀. 빌더 전량 시험 보고는 9744 passed |
| 엄격 증거 | 기록 중에 세션을 종료했다. 병합 훅에 쓰지 말 것. 워크트리에서 다시 기록한다 |

다음 명령은 그 워크트리에서, 커밋이 `cf970586` 인 채로 실행한다.

```bash
uv run python scripts/orca_level1_gate.py \
  --base main \
  --branch kwanbum217/scoped-list-rework-20261027 \
  --repo . \
  --capsule .orca/capsules/task_scoped_list_rework_20261027/capsule.yaml \
  --report .orca/capsules/task_scoped_list_rework_20261027/worker_done.json \
  --review-report .orca/capsules/task_scoped_list_review_20261027/review_done.json \
  --tests "tests/test_scoped_list_request.py tests/test_deadline_amount_sort.py -q -m 'not data_assets'" \
  --verify "uv run pytest tests/ -q -m 'not data_assets'" \
  --verify "uv run mypy src" \
  --strict --record-evidence
uv run python scripts/premerge_full_suite_gate.py --record
```

통과 뒤에만 주 저장소에서 `git merge --no-ff` 한다. 상태 문서 수정은 그 병합 커밋에 넣는다. 푸시 후 `git log main..그브랜치` 가 비면 워크트리를 `orca worktree rm --worktree path:<경로> --force` 로 지우고 디렉터리가 사라질 때까지 기다린 다음 `git worktree prune` 한다.

동작 요약: 미병합 `082e5f85` 의 기관·지역 범위 공고 목록을 현재 `query_planning.py` 에 옮겼다. 마감 창이 없는 마감 기한·마감일 네 건은 목록으로 올리지 않는다. 마감 임박과 이번 주 마감은 기존 창을 유지한다.

---

## 2. 미병합: 커밋 제목 반복 거절

| 항목 | 값 |
| --- | --- |
| 브랜치 | `kwanbum217/commit-subject-repeat-20261027` |
| 커밋 | `241b5c6e` `fix: 같은 커밋 제목이 최근 이력에서 반복되면 거절한다` |
| 워크트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/commit-subject-repeat-20261027` |
| 빌더 | `task_bd74dfa9abcc`, dispatch `ctx_f77ea272abee`. 계약 검사 통과. 터미널은 회수함 |
| 리뷰 | `task_311614a7fd69`, dispatch `ctx_048f1941e8c6`. 15:44 계약 검사 실효 pass. 보고는 워크트리 `.orca/capsules/task_commit_subject_review_20261027/review_done.json` |
| 파일 | `scripts/validate_commit_message.py`, `tests/test_validate_commit_message.py` |
| 레벨1 | 비엄격 전량 시험 중에 세션을 종료했다. 결과는 쓰지 않는다 |

규칙: 최근 HEAD 40개 제목에서 merge 타입을 빼고, 같은 제목이 이미 2번 있으면 거절한다. 1번 이하와 새 제목은 통과한다. 과거 이력은 되돌리지 않았다. 빌더 전량 시험 보고는 9736 passed 이며 코디네이터가 다시 돌리기 전에 종료했다.

리뷰는 통과했으므로 다시 시키지 않는다. 1번과 같은 엄격 게이트와 전량 시험 기록을 이 워크트리에서 한다. 보고 파일이 없을 때만 GLM `z-ai/glm-5.3-flash` `--effort high` `--auto` `--role reviewer` 로 리뷰어를 다시 붙인다. 체크리스트 id 는 `history_rewritten`, `unique_subject_blocked`, `merge_subject_blocked`, `scope_exceeded` 다.

이 파일은 1번과 겹치지 않으므로 1번 병합을 기다리지 않아도 된다. 증거 파일 `.cache/level1_strict_evidence.json` 과 `.cache/premerge_full_suite_evidence.json` 은 한 브랜치씩만 기록한다.

---

## 3. 조사만 완료: 묶음 6 계획 비교

조사 `task_cc716c963b03` 는 커밋 없이 종료했다. 워크트리 `/Users/kwanbum/orca/workspaces/refac_bid_box/bundle6-sweep-20261027` 는 그대로 둔다. 보고서 원문은 git 에 없다. `.orca/capsules/task_chat_bundle6_regression_sweep_20261026/design.md` 에만 있다.

워커 보고이며 코디네이터는 114개 비교를 다시 실행하지 않았다.

| 항목 | 값 |
| --- | --- |
| 비교 | `17c431f6` 대 `80cd1653` 의 `build_retrieval_plan` |
| 질문 | 114개. 계획 변경 7개. 실행 판정 회귀 0건 |
| 진단 의심 | q097 `최근 30일 수요기관별 낙찰 금액 상위는 어디야`, q101 `공사 부문 최근 30일 낙찰 동향 알려줘` |
| 내용 | SQL 로 바뀌었는데 `route_reason` 은 전후 모두 `기본 벡터 질의` |

다음 빌더는 1번이 `main` 에 들어간 뒤 `query_planning.py` 만 연다. `route_reason` 이 최종 `use_sql`/`use_vector` 와 어긋나지 않게 하고, q097, q101, 그리고 보고서에 적힌 q092 를 고정 시험으로 넣는다. 실행 판정을 되돌리는 수정은 하지 않는다.

---

## 4. 오늘 main 에 넣은 것

| 병합 | 내용 | CI |
| --- | --- | --- |
| `957b4871` | 질의 표현 상수를 `query_lexicon` 로 분리. 빌더 `6744ced2` | `40456336852` success |
| `ed54bda5` | 정답과 측정기를 한 브랜치에서 같이 못 고치게 하는 가드. 빌더 `6eba4b01` | `40457742098` success |
| `474def84` | 환경에 따라 깨지던 콜백·커버리지·훅 검사 분리. 빌더 `0df5eeeb` | `40459206540` success |

세 워크트리는 병합 확인 후 삭제했다. 로컬 브랜치도 함께 지워졌다. `CURRENT_STATE.md` 의 `source_commit` 은 `ed54bda5`, `updated_at` 은 2026-10-27 이다.

---

## 5. 착수하지 말 것

| 항목 | 이유 |
| --- | --- |
| 인수인계 10.5 여섯 결정 | 사용자 결정 전 |
| 재무제표 OCR, 회원가입 재무 | 2026-10-12 보류 |
| chromadb 1.x | 수정 버전 없음. allowlist 만료는 2026-12-31 근처 |
| 규칙 YAML 전면 이전 | 설계 합의 전 |
| 산림청 등록, `rule_coverage_ledger.yaml` 재작성, 계산 차단 구현 | 사용자 승인 전 |
| 1번 병합 전 `query_planning.py` 추가 수정 | 범위 목록 브랜치와 겹침 |

---

## 6. 모델과 회수

이번 세션 빌더는 OpenCode `opencode/deepseek-v4.1-flash-free`, 리뷰어는 Command Code `z-ai/glm-5.3-flash` `--effort high` 다. 사용자 지정이 저장소 기본 리뷰어보다 우선한다.

완료된 빌더 터미널은 회수했다. 리뷰어가 프롬프트만 남은 터미널은 `orca terminal close --terminal` 로 닫았다. `--tab` 은 쓰지 않는다.
