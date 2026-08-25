# Task: docs/README.md 추적 문서 인덱스 누락 보완

> **작성일**: 2026-08-25
> **Task ID**: task_0ef63b963bf8
> **설계 정본**: `.orca/capsules/task_docs_readme_index/capsule.yaml`

---

## 1. 목표

독립 감사에서 보고된 `docs/README.md` 인덱스 누락을 보완해, 다른 정본이 참조하는 문서를 인덱스에서 찾을 수 있게 한다.

## 2. 수행 내용

- `git ls-files docs/` 로 추적 문서를 얻어 `design/`, `migration/`, `handoff/`, `ops/`, `changelogs/` 5개 절의 기존 표 형식을 그대로 따라 누락 문서를 등재했다.
- 각 문서를 읽고 내용에 근거한 한 줄 설명을 붙였다. 파일명을 되풀이하지 않고 그 문서가 정하거나 기록하는 것을 적었다.
- `docs/orca/` 는 등재하지 않았다 (Git 미추적, ground_truth).
- `analysis/` 는 개별 문서를 나열하지 않고 기존 디렉터리 성격·최신 정본 안내를 유지했다.
- 폴더 구조 다이어그램에 루트 산출물 `servc_model_status.md` 를 추가해 실제 구성과 맞췄다.
- 버전을 v1.3.0 -> v1.4.0, 정정일을 2026-08-25 로 갱신했다.

## 3. 변경 파일

- `docs/README.md` (유일한 수정 파일. 107줄 추가, 2줄 변경)

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `python3 scripts/validate_doc_links.py --quiet` | [PASS] 문서 링크 검증 통과 (292개 파일) |
| `python3 scripts/validate_agent_rules.py --quiet` | 12/12 PASS |
| `git ls-files docs/` 대조 | design 32건, migration 2건, handoff 29건, ops 41건, changelogs 1건 누락 없음 |
| `git diff --name-only` | `docs/README.md` 1건 |

## 5. 남은 작업

- 없음. 후속 검증(리뷰어)과 병합만 남아 있다.
