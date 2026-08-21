# CURRENT_STATE.md 최소 diff 정비 및 경량화 재작업 보고서

> **작성일**: 2026-08-22
> **Task ID**: task_current_state_cleanup_rework
> **대상 파일**: `docs/context/CURRENT_STATE.md`
> **목적**: 1차 산출물의 1~3장·5~7장 재서식 원복, 4장/4.1절 중심 종결 항목 이관 및 7,400자 이하 예산 달성

---

## 1. 재작업 개요

1차 산출물에서 발생했던 1~3장 및 5~7장의 불필요한 문장·표 재서식을 `main` 원본 기준으로 완전 복구하고, 과업 범위에 맞춰 4장(진행 과업) 및 4.1절(종결 계열 요약)만을 중심적으로 정비했습니다.

- **목표 문자 수**: 7,400자 이하 (정본 8,000자 상한 대비 여유 확보)
- **최종 실측 문자 수**: **7,379자** (목표 충족, 21자 여유)
- **`main` 대비 변경 범위**: `docs/context/CURRENT_STATE.md` 4장/4.1절 및 `updated_at`, `docs/analysis/task_current_state_cleanup_rework.md` (총 2개 파일)

---

## 2. 세부 정비 및 이관 내역

### 2.1 1~3장 및 5~7장 복구 (최소 diff 원칙)
- `main` 정본의 CommonMark 표 공백, 정렬, 굵은 글씨, 문장 구조를 100% 동일하게 유지했습니다.
- 헤더의 `updated_at` 은 2026-08-22 로 갱신하였으며, `source_commit` 은 코디네이터 소유 규칙에 따라 `1cfea2e` 를 그대로 보존했습니다.

### 2.2 4장 및 4.1절 종결 항목 이관
- **항목 0 (무료 워커 경합 종료)**: 4.1절 `워커 풀 정비·상시 관측 전환 (11장)` 항목으로 통합 이관.
- **항목 4 (ORM Mapped[] 전환 완료)**: 4.1절 전용 항목으로 이관 (13개 모델·137개 컬럼, 메타데이터 지문 일치, call-overload 6개 제거 사실 보존).
- **항목 1 (워커 기동 준비 자동화)**:
  - 완료부(`scripts/orca_prepare_worktree.py` `.env`·신뢰·pre-commit 자동화, `shift+tab` 필요)는 4.1절로 이관.
  - 후속 판단(pre-commit pytest 미실행 대응 커밋 게이트 도입 여부)은 4장 1번으로 유지.
- **항목 3 (동기 블로킹 I/O)**:
  - 실측 완료부(예측 API 웜 P95 61.9~83.6ms 목표 100ms 충족, 콜드 383·122ms 미달, SSE 1.26~2.29s 및 6.37~7.65s 충족, 기준선 부재로 개선폭 미주장, 단발 목표 미정의)는 4.1절로 이관.
  - 후속 판단(예측 콜드 워밍업 여부, 단발 목표/SSE, Arq 설계)은 4장 3번으로 유지.
- **진행 과업 재번호**: 남은 과업을 1번부터 6번까지 순차 재번호화 완료.

---

## 3. 검증 결과

1. **컨텍스트 예산 및 규칙 검증**:
   - `CURRENT_STATE.md`: **7,379자** (7,400자 이하 및 8,000자 상한 준수)
   - `python3 scripts/validate_agent_rules.py`:
     - `[PASS] 컨텍스트 예산` (CURRENT_STATE.md 7379자/8000)
     - `[PASS]` 1~3장, 5~7장 무손실 및 무서식화
     - `source_commit` 지연(1cfea2e) 1건은 사양(코디네이터 후속 처리)에 따라 의도된 상태로 보존
2. **변경 파일 최소화**:
   - `docs/context/CURRENT_STATE.md`
   - `docs/analysis/task_current_state_cleanup_rework.md`
   - 1차 요약 파일(`docs/analysis/task_current_state_cleanup.md`)은 병합 대상에서 제외 완료
