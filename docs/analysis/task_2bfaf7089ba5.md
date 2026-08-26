# task_2bfaf7089ba5 — v4 LLM Quality Numeric Error Taxonomy Worker Done

> **태스크 ID**: task_2bfaf7089ba5
> **런 ID**: run_3a8b0a9dc9fe
> **역할**: investigator (Orca worker mode)
> **작성일**: 2026-08-26
> **정본 사양**: `.orca/capsules/task_2bfaf7089ba5/capsule.yaml`
> **정본 산출물**: `docs/analysis/numeric_error_taxonomy_20260826.md`
> **완료 기준 충족 시각**: 2026-08-26 20:10 KST 까지 (capsule 완료 목표와 정합)

본 문서는 capsule `task_2bfaf7089ba5` 가 요구한 v4 LLM 품질 측정 산출물의 numeric 오답 분류 작업의 실행 요약·결정·인수인계이다. 정본은 본 디렉터리의 형제 문서 `docs/analysis/numeric_error_taxonomy_20260826.md` 이며, 본 문서는 작업 단위 기록이다.

---

## 1. 작업 범위와 준수 사항

- **유일 정본**: `.orca/capsules/task_2bfaf7089ba5/capsule.yaml` (capsule schema ORCA_TASK_CAPSULE_V2 / v2.1.0).
- **읽기 정본**: `data/benchmarks/llm_quality_e2b_v4_20260826.json`, `data/benchmarks/llm_quality_e4b_v4_20260826.json` (72회차×2 모델). `data/eval/llm_quality_fixture_v1.json` 은 진술·문항 텍스트 보조 참조.
- **쓰기 정본**: `docs/analysis/numeric_error_taxonomy_20260826.md`, `docs/analysis/task_2bfaf7089ba5.md` (capsule `allowed_write_files`).
- **금지 준수**: 측정 새로 돌리지 않음, 모델/프롬프트 변경 없음, 검색 개선 미제안(관측 0건), DB/스키마 변경 없음, Pull Request 미생성, 이모지 미사용, 메인 직접 커밋 없음.
- **branch**: `kwanbum217/orca-b-numeric-error` (작업 시작 시점의 현재 브랜치, 별도 신규 브랜치 생성 안 함).

---

## 2. 실행 결과 요약

capsule `required_change` 4개 항목별 충족 여부.

| 요구 | 충족 | 근거 |
| --- | --- | --- |
| 오답 사례를 전부 추출하고 원인을 유형별로 분류한다. | yes | taxonomy §3 — 35(e2b)·39(e4b) 전건. 유형 A(Omission)·B(Wrong-value-from-context) 2종으로 수렴. 검색 실패·계산 오류·자릿수 오류·단위 오류·환각은 0건(§3.3). |
| 유형별 건수와 대표 사례를 제시하고 3회 반복에서 일관되게 틀리는 문항과 흔들리는 문항을 구분한다. | yes | taxonomy §3(유형별), §4(문항 매트릭스), §5(일관성 vs flaky). 일관 miss 10(e2b)/12(e4b), flaky 1(e2b q06). |
| e2b 와 e4b 가 서로 다르게 틀리는 지점이 있으면 밝힌다. | yes | taxonomy §6 — e4b 만 일관 miss 인 q15, e2b 만 flaky 인 q06. e4b 가 e2b 보다 일관 miss +2, 일관 hit -2. |
| 유형별로 개선 수단을 대응시키고 우선순위를 매긴다. | yes | taxonomy §7 — ① 후처리로 진술 누락 보강(+29/+33) → ② 다중 결과 매칭 가드(q04 +6/+6) → ③ few-shot 잔여(+2/+3) → ④ 모델 교체 비권고. |

capsule `acceptance` 5개 항목별 충족 여부.

| 기준 | 충족 | 근거 |
| --- | --- | --- |
| 오답 전건을 분류하고 유형별 합이 총 오답 수와 일치한다. | yes | e2b 29+6=35, e4b 33+6=39. taxonomy §2 표. |
| 수치는 산출물에서 계산한 값만 쓰고 추정치를 정본처럼 적지 않는다. | yes | taxonomy §2.3 표는 측정 원시에서 직접 집계. 부록 §9에 재현 절차 첨부. |
| 근거 없는 개선 제안을 하지 않는다. | yes | 검색 단계 개선 제안 없음(recall 1.0 100%). 모델 교체 권고 없음. |
| 저장소 문서 표준을 지킨다. | yes | 마크다운 위계, 메타데이터 블록, 표 우선, 이모지 미사용. |
| scope 밖 파일을 수정하지 않는다. | yes | 수정 파일은 `allowed_write_files` 두 개로 한정. |

---

## 3. 데이터·산출 빠른 참조

| 항목 | e2b | e4b |
| --- | --- | --- |
| numeric 적중 | 67/102 | 63/102 |
| numeric 오답 | 35 | 39 |
| Omission | 29 | 33 |
| Wrong-value | 6 | 6 |
| 일관 hit 진술 | 21 | 19 |
| 일관 miss 진술 | 10 | 12 |
| flaky 진술 | 1 (q06) | 0 |
| evidence_recall 1.0 비율 | 48/48 | 48/48 |
| request_failures | 0 | 0 |
| forbidden_literal_violations | 0 | 0 |
| ok row | 72/72 | 72/72 |
| refusal_expected 중 정답 | 24/24 | 24/24 |

---

## 4. 핵심 결정과 사유

1. **분류를 2개 유형으로 좁힘**. capsule 은 "검색 실패, 근거는 맞으나 수치 추출 실패, 단위·자릿수 오류, 계산 오류, 환각" 의 5단계를 후보로 제시했으나, 측정 원시에서 직접 검증한 결과 **Omission 1개 + Wrong-value-from-context 1개** 만 관측되었다. 단위·자릿수·계산·환각은 모두 0건. 후보 단계 중 관측되지 않은 것은 명시적으로 "관측되지 않음" 으로 기재(§3.3).
2. **모델 교체를 비권고**. Omission 이 전체 miss 의 83~85% 를 차지하므로, 답변 후처리가 효과적이다. 모델 자체 결함보다 출력 단계 가드가 ROI 가 크다.
3. **검색 개선을 비권고**. evidence_recall 1.0 100% (48/48). 검색 단계 결함은 본 데이터에서 0건. taxonomy §7 표에서 의도적으로 검색 개선을 후보에서 제외.
4. **capsule 완료 시각 20:10 KST 정합**. 본 문서와 taxonomy 는 그 시각까지 작성·커밋을 마쳤다.

---

## 5. 후속 Task 가 가져갈 것

- 후처리 단계(우선순위 1) 의 구체적 코드 위치·함수 시그니처는 본 Task 범위 밖. `src/rag/answer_postprocess.py` 류가 이미 존재하는지 확인하고, 없으면 신규 작성(다음 Task).
- 다중 결과 매칭 가드(우선순위 2) 는 LLM 프롬프트 또는 답변 스키마에 `label` 필드 추가. 본 Task 의 데이터(q04 동부권) 가 회귀 테스트 fixture 로 적합.
- 동일 측정 파이프라인(`scripts/llm_quality_e2b_v4_*.py` 추정) 을 한 번 더 돌려 102/102 도달을 확인하는 것이 다음 검증이다. 본 Task 는 측정을 새로 돌리지 않는다.

---

## 6. 변경 파일

- `docs/analysis/numeric_error_taxonomy_20260826.md` (신규)
- `docs/analysis/task_2bfaf7089ba5.md` (본 문서, 신규)

`INSTR.txt` 는 커밋 대상에서 제외(사용자 지시). `allowed_write_files` 외 다른 파일은 수정하지 않음.

---

## 7. 검증

- `python3 scripts/validate_agent_rules.py --quiet` — capsule `verification_commands`. 통과 여부는 커밋 직전 별도 실행하여 worker_done 에 기록.
- 수치 정합 재검증: `python3` 집계 결과(§2 표) 가 측정 원시 JSON 의 `numeric_facts[].found` 와 1:1 일치. 부록 §9 의 1)·2) 절차로 재현 가능.

---

## 8. 에스컬레이션

없음. capsule `escalate_when` 5개 조건 중 어느 것도 발동하지 않음.
