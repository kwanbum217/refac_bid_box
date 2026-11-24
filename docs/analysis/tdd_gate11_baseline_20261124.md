# 게이트 11 실패→통과 증명 기준선 (2026-11-24)

> 작성일: 2026-11-24
> 대상: `scripts/orca_level1_gate.py` 게이트 11, `scripts/orca_gate11_backfill.py`
> 측정 스크립트: `uv run python scripts/orca_gate11_backfill.py`
> 범위: 경고 모드 게이트 구현과 2026-11-24 병합 6건 소급 실행. 운영 DB·Redis·Meilisearch 는 읽지도 쓰지도 않습니다.

---

## 1. 목적

기존 Level 1 게이트는 시험이 통과했는지만 확인합니다. 그래서 변경을 실제로 잡지 못하는
시험도 병합될 수 있습니다. 게이트 11 은 작성 순서가 아니라 **시험이 변경을 잡는가**를
기계로 확인합니다. 브랜치에서 추가·수정된 시험을 기준(base) 코드에 그대로 얹었을 때
단언 실패가 나고, 브랜치 코드에서는 전부 통과하는지를 봅니다.

이번 단계는 사용자 승인에 따른 **경고 모드**입니다. 게이트 11 은 어떤 경우에도 병합을
막지 않습니다. 2주 동안 결과를 쌓은 뒤 차단 전환 여부를 사용자가 결정합니다.

---

## 2. 판정 정의

게이트 11 은 `status` 를 `fail` 로 두지 않습니다. 판정은 `raw_data["verdict"]` 에만
남기고, `proven` 일 때만 `status=pass`, 나머지는 `status=skipped` +
`required=False` 입니다. 따라서 `--strict` 병합 판정은 바뀌지 않습니다.

| verdict | 조건 | status |
| --- | --- | --- |
| `proven` | 기준 코드에서 단언 실패 1건 이상, 브랜치에서 전부 통과 | `pass` |
| `not_proven` | 기준 코드에서도 전부 통과 | `skipped` |
| `collection_only` | 기준 코드에서 수집·import 오류만 발생, 단언 실패 0건 | `skipped` |
| `branch_failed` | 브랜치에서 단언 실패 또는 오류 발생 | `skipped` |
| `exempt` | 대상 시험 파일 0개, 또는 문서·정리·리팩터링·시험 커밋만 있고 `src/` 변경 없음 | `skipped` |
| `error` | git·압축 해제·pytest·junit 파싱 등 도구 오류 | `skipped` |

대상 시험은 `git diff --name-only --diff-filter=AM <base>...<branch> -- tests/` 에서
고른 `tests/**/test_*.py` 파일입니다. `tests/e2e/` 는 제외하고, 시험 함수 단위로
좁히지 않고 파일 단위로 실행합니다.

기준 트리와 브랜치 트리는 `git worktree` 없이 `git archive` 로 임시 디렉터리에 풉니다.
대상 시험 파일만 브랜치 판으로 덮어쓰고, `.env` 가 있으면 임시 디렉터리로 복사합니다.
실행 명령은 다음과 같고 시간 상한은 `GATE11_TIMEOUT_SECONDS = 600` 초입니다.

```text
<repo>/.venv/bin/python -m pytest -q -m "not data_assets and not e2e" \
  -p no:cacheprovider --junitxml=<tmp>/gate11_junit.xml <대상 시험 파일들>
```

junit xml 의 `failure`(단언 실패)와 `error`(수집·설정 오류)를 구분해 셉니다.
`collection_only` 를 `proven` 으로 승격하지 않는 이유가 여기에 있습니다.

---

## 3. 소급 실행 방법

`scripts/orca_gate11_backfill.py` 는 읽기 전용입니다. 브랜치·참조·작업 트리를 바꾸지
않고, 참조별로 다음 순서로 base 를 정합니다.

1. `git log main --merges --format='%H %P'` 에서 두 번째 부모가 대상 참조 커밋인 병합
   커밋을 찾고 첫 번째 부모를 base 로 씁니다.
2. 찾지 못하면 `git merge-base main <ref>` 를 base 로 씁니다.

이번 6건은 모두 `merge_parent` 로 base 를 찾았습니다. 스크립트는 게이트 11 함수를
직접 호출해 verdict 와 수치를 JSON 으로 표준출력에 냅니다.

```bash
uv run python scripts/orca_gate11_backfill.py
```

---

## 4. 기준선 결과

2026-11-24 07:56 UTC 실행 결과입니다. 소요 초는 그 실행의 측정값입니다.

| 참조 | 커밋 type | 대상 시험 파일 수 | verdict | 기준 failed/errors | 브랜치 passed/failed | 소요 초 |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| `refs/backup/dark-suffix-20261124` | refactor | 5 | proven | 15/0 | 27/0 | 7.65 |
| `refs/backup/home-prefs-perf-20261124` | chore, fix | 3 | proven | 10/0 | 22/0 | 6.07 |
| `refs/backup/kb-count-perf-20261124` | docs, refactor | 1 | collection_only | 0/1 | 6/0 | 4.05 |
| `refs/backup/kb-result-cleanup-20261124` | fix | 1 | proven | 2/0 | 5/0 | 4.27 |
| `refs/backup/meili-ranking-20261124` | docs, feat | 1 | collection_only | 0/1 | 7/0 | 4.53 |
| `refs/backup/search-cache-20261124` | feat | 1 | collection_only | 0/1 | 17/0 | 4.26 |

참조별 커밋과 base 는 다음과 같습니다.

| 참조 | 커밋 | base | base 판정 방법 |
| --- | --- | --- | --- |
| `dark-suffix-20261124` | `95c9873e` | `3c070786` | merge_parent |
| `home-prefs-perf-20261124` | `24a566b0` | `eca7419c` | merge_parent |
| `kb-count-perf-20261124` | `35d7ab06` | `bfbda343` | merge_parent |
| `kb-result-cleanup-20261124` | `93f5a523` | `458d88c9` | merge_parent |
| `meili-ranking-20261124` | `2094e63c` | `6ef2b7e6` | merge_parent |
| `search-cache-20261124` | `d3b53d6d` | `f341b73d` | merge_parent |

---

## 5. 해석

- `proven` 3건은 시험이 실제 변경을 잡았습니다. `dark-suffix` 는 템플릿·CSS 변경을
  15건의 단언 실패로 잡았고, `home-prefs-perf` 는 10건, `kb-result-cleanup` 은 2건을
  잡았습니다. 세 건 모두 브랜치에서는 단언 실패와 오류가 0건입니다.
- `collection_only` 3건은 기준 코드에서 시험 파일의 import 가 실패했습니다.
  `kb-count-perf`, `meili-ranking`, `search-cache` 는 새 함수·상수를 시험 파일 상단에서
  바로 import 하므로, 그 심볼이 없는 기준 코드에서는 수집 단계에서 멈춥니다. 이는
  변경을 잡은 증거이긴 하지만 단언 실패는 아니므로 이 게이트는 `proven` 으로 세지
  않습니다.
- `not_proven` 과 `branch_failed` 는 이번 6건에 없습니다. 모든 참조의 브랜치 시험은
  통과했고, 기준 코드에서는 최소한 import 오류나 단언 실패가 났습니다.
- 따라서 현재 병합 이력의 시험들은 변경과 최소한 결합되어 있습니다. 다만 새 기능
  시험의 절반이 `collection_only` 라는 점은, 시험이 공개 동작을 안정된 인터페이스로
  검증하기보다 새 심볼 import 에 먼저 의존한다는 뜻입니다. 차단 전환 전에 시험 작성
  지침으로 이 부분을 다뤄야 합니다.

---

## 6. 경고 모드 운영 방법

게이트 11 은 Capsule 을 받는 Level 1 호출에서만 실행됩니다(게이트 9·10 과 같은 조건).
인간용 출력에서는 `[PASS]` 또는 `[N/A]` 로 표시되고, 요약 앞에 `[경고 모드]` 가
붙습니다. JSON 출력에서는 `gates.gate11_fail_pass` 아래에 다음 필드가 남습니다.

| 필드 | 내용 |
| --- | --- |
| `verdict` | `proven`, `not_proven`, `collection_only`, `branch_failed`, `exempt`, `error` |
| `target_files` | 대상 시험 파일 목록 |
| `commit_types` | `base..branch` 비병합 커밋의 type 목록 |
| `src_changed` | `src/` 변경 여부 |
| `base_counts` | 기준 트리의 passed/failed/errors/skipped 와 실패 시험 id 최대 20개 |
| `branch_counts` | 브랜치 트리의 같은 집계 |
| `duration_seconds` | 게이트 전체 소요 초 |

`proven` 이 아닌 결과는 모두 `required=False` 인 건너뜀이므로 `--strict` 판정에
영향을 주지 않습니다. 병합을 막지 않으면서 결과만 쌓습니다.

---

## 7. 차단 전환 판단 기준 후보

2주 경고 모드 운영 뒤 다음 지표를 보고 전환 여부를 정합니다. 어느 하나도 단독
기준으로 삼지 않습니다.

| 후보 지표 | 전환 찬성 신호 | 유보 신호 |
| --- | --- | --- |
| `proven` 비율 | 최근 병합 10건 중 7건 이상 | 4건 이하 |
| `not_proven` 비율 | 10% 이하 | 30% 이상 |
| `collection_only` 비율 | 20% 이하 | 40% 이상 |
| `error` 발생 | 0건 | 재현되는 도구 오류 1건 이상 |
| 오탐(정당한 변경인데 실패) | 보고된 오탐 0건 | 오탐 1건 이상 |
| 게이트 소요 시간 | Level 1 전체 증가가 2분 이내 | 5분 초과 |

`collection_only` 는 차단 전환 시 `proven` 과 동일하게 취급할지 먼저 정해야 합니다.
기준 코드에 심볼이 없는 새 기능 시험은 구조적으로 `collection_only` 가 되므로,
이를 차단 대상으로 삼으면 새 기능 개발이 막힙니다. 전환 시에는 `collection_only` 를
경고로 두고 `not_proven` 과 `branch_failed` 만 차단하는 안을 우선 검토합니다.

---

## 8. 한계와 후속

- 기준 트리 실행은 현재 저장소의 `.venv` 파이썬을 빌려 씁니다. 기준 커밋의 의존성
  lock 이 지금과 다르면 환경 차이로 실패할 수 있습니다. 이번 6건은 모두 현재 환경에서
  실행됐고 도구 오류가 없었습니다.
- 시험 파일 단위로 실행하므로, 대상 파일 안의 기존 시험도 함께 돌아갑니다. 기준
  코드에서 원래 실패하던 기존 시험이 있으면 `proven` 으로 오인할 수 있습니다. 이번
  6건의 기준 실패는 모두 브랜치가 바꾼 시험에서 나왔습니다.
- 소급 실행은 `.env` 를 임시 디렉터리로 복사합니다. 운영 자격 증명이 임시 디렉터리에
  잠시 존재하므로 실행 후 즉시 지웁니다. `shutil.rmtree` 는 `finally` 에서 수행합니다.
- 다음 단계는 2주간 병합마다 `verdict` 를 기록하고, `collection_only` 를 줄이기 위한
  시험 작성 지침(공개 동작 우선, 새 심볼 import 최소화)을 정하는 것입니다.

---

## 9. 재현

```bash
# 게이트 11 시험
uv run pytest -q -m "not data_assets" tests/test_orca_gate11_fail_pass.py \
  tests/test_orca_level1_gate.py

# 소급 실행 (JSON)
uv run python scripts/orca_gate11_backfill.py

# 특정 참조만
uv run python scripts/orca_gate11_backfill.py \
  --refs refs/backup/search-cache-20261124
```
