# Arq 정식 기준선 캘리브레이션 산식 퇴화 수정 Task 요약

> **작성일**: 2026-08-24
> **Task ID**: task_e860cec0fde5
> **상태**: 완료 (코드 변경 없음, 측정 미실시)
> **observed_commit**: `b1c6af3`
> **superseded_by**: 정식 기준선이 실제 캘리브레이션 런으로 도출되면 별도 문서로 대체된다.
> **외부 감사**: P1-2, P2-4

---

## 1. 수행 내용

1. `arq_calibration_design_20260824.md` 6장의 퇴화 산식(`max(Q_p(T, 0.05), min(T) * 0.95)`, `max(Q_p(P, 0.95), max(P) * 1.05)`)을 제거하고, 중앙값 기반 기준선 추정 + 상대 허용 비율 회귀 게이트 + CV/MAD 반복 안정성 판정의 **분리 구조**로 재설계했습니다.
2. 설계서의 `docs/analysis/` 접두 상대 링크 5곳(13, 44, 79, 259, 326행 부근)을 같은 디렉터리 기준 상대경로(`arq_threshold_derivation_20260823.md`)로 정정했습니다.
3. `calibration_executability_20260824.md` 3.1절에 7개 항목을 BLOCKER/MANUAL/WARNING/RESOLVED 네 상태로 재분류한 표를 추가하고, 5장 6.2/6.3 행과 7장 결론을 갱신했습니다.
4. 두 문서 머리에 `observed_commit`, `status`, `superseded_by` 메타데이터를 추가했습니다.
5. 근거와 수치 예시를 `arq_calibration_formula_fix_20260824.md`에 기록했습니다.

## 2. 새 산식 요약

| 판정 | 산식 |
| --- | --- |
| 기준선 추정 | `throughput_baseline = median(T)`, `p95_baseline = median(P)`, `failure_baseline = 0` (전제 조건) |
| 회귀 게이트 | `rt = max(3 * CV(T), 0.06)`, `rp = max(3 * CV(P), 0.06)`, `t < median(T) * (1 - rt)`, `p > median(P) * (1 + rp)` |
| 반복 안정성 | `CV <= 0.05` 및 `MAD/median <= 0.03` |

- 원칙: 회귀 허용 폭은 반드시 반복 안정성 임계값(`cv_max = 0.05`)보다 엄격히 커야 하며, `3 * CV` 항과 하한 0.06이 이를 보장한다.
- `m_ratio = 0.03`: 정규분포에서 `MAD/median ≈ 0.67 * CV`이므로 `m_ratio = 0.05`는 CV 판정보다 느슨해 보조 역할을 못 하여 `0.03`으로 조였다.

## 3. 수치 예시 (3회 synthetic, 예시 계산용)

- 처리량 1681/1710/1764 → `median = 1710 jobs/sec`, `rt = 0.0735`, 회귀 판정선 1584.3, `CV 0.0245`, `MAD/median 0.0170`
- P95 325/333/342 → `median = 333 ms`, `rp = 0.0765`, 회귀 판정선 358.5, `CV 0.0255`, `MAD/median 0.0240`
- 예시값은 정식 기준선으로 승격하지 않습니다.

## 4. 변경 파일

- `docs/analysis/arq_calibration_design_20260824.md` (수정)
- `docs/analysis/calibration_executability_20260824.md` (수정)
- `docs/analysis/arq_calibration_formula_fix_20260824.md` (신규)
- `docs/analysis/task_e860cec0fde5.md` (본 문서, 신규)

## 5. 검증

- `python3 scripts/validate_agent_rules.py --quiet` 통과 (12/12).
- 설계서 내 `docs/analysis/docs/analysis` 로 해석되는 링크 잔존 없음.
- 코드·스크립트 수정 없음, 이모지 없음.

## 6. 남은 작업

- 10회 정식 캘리브레이션 런으로 `rt`, `rp`, 반복 안정성 임계값 확정.
- `scripts/arq_gate.py` `RepetitionThresholds` 대체 코드 변경은 별도 Task.
- BLOCKER 3건(대표값 산식 자동 적용, 부하 규약 자동 강제, provenance unknown 자동 기각)의 하네스 보강 여부 결정.
