# Task J — CURRENT_STATE 정비 및 ngram 런북 (2026-09-01)

> **Task**: `task_d33cbcec73c1`
> **Run**: `run_f5b20eafcaff`
> **작성일**: 2026-09-01
> **역할**: documenter

---

## 1. 배경

`CURRENT_STATE` 6.1절이 공고 상세 쿼리를 "실측 미수행"으로 기술하고 있었으나
`docs/analysis/detail_query_explain_20260830.md` 에 이미 실측 결과가 기록돼 있었습니다.
또한 Wave I 미병합 현황(I-F/I-H 미병합, I-C 반려)과 운영 FULLTEXT 보류가 문서에
반영되지 않았습니다. 운영 FULLTEXT 인덱스 생성 절차를 승인 후 실행할 수 있는 런북으로
문서화하는 것이 이 Task 의 목표입니다.

---

## 2. 확인한 사실 (재조사 없음, Capsule ground_truth 기준)

| 사실 | 근거 |
| --- | --- |
| 공고 상세 신 구현 실행 시간: 5.09ms | `detail_query_explain_20260830.md` 1절 표 |
| API P95: 47.98ms (5개 공고 x 24회, 120표본) | `detail_query_explain_20260830.md` 3절 표 |
| 추가 인덱스 불필요 | `detail_query_explain_20260830.md` 4절 |
| ngram 선행필터: 기본값 OFF 플래그, 기관명·업체명 집계 두 경로만 적용 | 코디네이터 확인 사실 |
| I-A/I-B/I-D/I-G: `main` 병합 완료 | `handoff_20260831_wave_i_prep.md` 0절 |
| I-C: `citations_wrong` 반려 (`kwanbum217/orca-i-c`, `9210641`) | `handoff_20260831_wave_i_prep.md` 0절 |
| I-F: 조율 계약 강제, MATCH AGAINST 아님. 미병합 (`kwanbum217/orca-i-f`, `f9184f5`) | `handoff_20260831_wave_i_prep.md` 0절 |
| I-H: 미병합 (`kwanbum217/orca-i-h`, `d8aa9a9`) | `handoff_20260831_wave_i_prep.md` 0절 |
| 운영 FULLTEXT 인덱스 생성: 사용자 승인 전 보류 | 코디네이터 확인 사실 |

---

## 3. 변경 파일 요약

| 파일 | 변경 내용 |
| --- | --- |
| `docs/context/CURRENT_STATE.md` | 6.1절 공고 상세 쿼리: 미실측 -> 실측 완료 정정. 4장 1-0항 I-F/I-H/I-C 현황 반영. 6.1절 Wave I 미병합 현황 블록 추가. `updated_at`·`source_commit` 갱신. |
| `docs/ops/ngram_fulltext_cutover_runbook.md` | 신규 작성 (9단계 런북). |
| `docs/ops/handoff_20260901_wave_j.md` | 신규 작성 (이 Task 인수인계). |
| `docs/analysis/task_d33cbcec73c1.md` | 신규 작성 (이 문서). |

---

## 4. 인용 수치 검증

CURRENT_STATE 에 옮겨 적은 수치는 없습니다. 6.1절 정정 항목은 아티팩트 경로 인용으로
대체했고 수치는 원문에서 직접 확인합니다.

런북 7단계 개선 기대값은 `handoff_wave_f_20260830.md` 3절 표에서 옮겨 왔습니다:
- `dminstt_nm`: warm 1,719.6ms -> 90.6ms (19.0배)
- `bidwinnr_nm`: warm 808.7ms -> 283.8ms (2.9배)

---

## 5. 금지 행위 확인

- src/ 수정 없음.
- 운영 DB, Docker, 기능 플래그 수정 없음.
- 이모지 없음.
- main 직접 커밋 없음 (작업 브랜치 `kwanbum217/orca-j2`).
- PR 생성 없음.
