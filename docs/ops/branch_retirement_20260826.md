# 폐기 브랜치 삭제 기록 (2026-08-26)

> **작성일**: 2026-08-26
> **근거 판정**: [`bakeoff_branches_verdict_20260826.md`](bakeoff_branches_verdict_20260826.md), [`arq_worker_cutover_branch_verdict_20260826.md`](arq_worker_cutover_branch_verdict_20260826.md), [`codex_task_routing_branch_verdict_20260814.md`](codex_task_routing_branch_verdict_20260814.md), [`phase8_predict_tail_merge_verdict_20260814.md`](phase8_predict_tail_merge_verdict_20260814.md)
> **사용자 승인**: 2026-08-26 세션에서 삭제 승인

---

## 1. 왜 SHA 를 남기는가

판정이 폐기 권고인 브랜치는 병합되지 않으므로 `git branch -d` 가 거부합니다.
`-D` 로 지우면 reflog 만료 뒤에는 복구할 수 없습니다. 아래 SHA 를 남겨 두면
판정이 뒤집혔을 때 `git checkout -b <이름> <sha>` 로 되살릴 수 있습니다.

## 2. 삭제한 브랜치

| 브랜치 | 마지막 커밋 | 고유 커밋 수 | 판정 |
| --- | --- | ---: | --- |
| `kwanbum217/b2-deepseek` | `d672f7c` | 1 | --json 중복 |
| `kwanbum217/b2-laguna_xs` | `1b80496` | 1 | --json 중복 |
| `kwanbum217/b2-mimo` | `bf7f511` | 1 | --json 중복 |
| `kwanbum217/b2-oc_nemo3ultra` | `bc971ea` | 2 | --json 중복, 시그니처 변경 |
| `kwanbum217/bakeoff-deepseek` | `ba03d6e` | 1 | 관측 이력 개념 중복 |
| `kwanbum217/bakeoff-nemotron_ultra` | `ab97c29` | 1 | 관측 이력 개념 중복 |
| `kwanbum217/bakeoff-oc_nemotron_ultra` | `9af64d7` | 1 | 관측 이력 개념 중복 |
| `integrate/arq-worker-cutover` | `602072f` | 12 | 전량 main 반영 완료 |
| `feat/codex-task-routing` | `70bd666` | 1 | 고유 파일 17건 전량 폐기 권고 |
| `perf/predict-tail` | `0fd489a` | 4 | 계측 하네스 병합 불가 |

## 3. 회수 완료 후 삭제한 브랜치

두 브랜치는 회수 후보였고, 2026-08-26 야간 세션에서 **변경 내용만 현재 main 코드에
맞게 이식**했습니다(`f89c6a0`). 브랜치를 그대로 병합하지 않은 것은 둘 다
2026-08-20 기준이라 이후 변경과 충돌하기 때문입니다. 이식이 끝나 삭제했습니다.

| 브랜치 | 마지막 커밋 | 회수한 내용 |
| --- | --- | --- |
| `kwanbum217/b2-or_nemoultra` | `5dc2a2b` | `--json` 출력 옵션 |
| `kwanbum217/bakeoff-mimo` | `c95cd60` | `audit_with_state()` 함수 분리 |

## 4. 보존한 브랜치

| 브랜치 | 사유 |
| --- | --- |
| `kwanbum217/orca-w1-concurrency-2` | 동시성 테스트 병합 기각의 근거 |
| `feat/p1-reliability-lock` | 미판정 |
