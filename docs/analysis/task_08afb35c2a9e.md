# Task 08afb35c2a9e 수행 기록: LLM 일반화 측정 설계서 작성

> **task_id**: task_08afb35c2a9e
> **run_id**: run_3a8b0a9dc9fe
> **role**: investigator
> **started_at**: 2026-08-26
> **completed_at**: 2026-08-26
> **status**: succeeded

---

## 1. 작업 개요

**목적**: fixture 밖 일반화 측정의 설계서를 작성해, 다음 세션이 문항 제작부터 다시 고민하지 않고 측정만 실행하면 되는 상태로 만든다.

**정본 사양**: `.orca/capsules/task_08afb35c2a9e/capsule.yaml`

**범위**: 측정 실행 X, 문항 파일 수정 X, 설계 문서만 작성

---

## 2. 수행 내용

### 2.1 선행 조사 (읽은 파일)

| 파일 | 용도 |
|------|------|
| `docs/context/CURRENT_STATE.md` | 현재 운영 상태, G3 게이트 상태, v4 측정 결과 참조 |
| `data/eval/llm_quality_fixture_v1.json` | 기존 24문항 fixture 구조 분석 (중복 방지, 거절 유형 파악) |
| `scripts/measure_llm_quality.py` | 측정 하네스 로직 이해 (채점 축, provenance, 거부 패턴) |
| `scripts/benchmark_rag_segments.py` | 지연 정본 판정 규약 이해 (trace 상관, provenance 결박) |
| `docs/ops/latency_gate_protocol.md` | 표본 수, warmup, 반복 회차, 대표값, 주변 부하 규약 준수 |

### 2.2 작성한 산출물

1. **`docs/ops/llm_generalization_measurement_design.md`** - 측정 실행 설계서 (정본)
2. **`docs/analysis/task_08afb35c2a9e.md`** - 본 수행 기록

### 2.3 설계서 핵심 결정 사항 요약

| 항목 | 결정 내용 | 근거 |
|------|-----------|------|
| 신규 문항 수 | 32문항 (답변 가능 24 + 거절 8) | 기존 24문항 대비 1.33배, 통계적 검정력 확보 |
| 문항 소스 | 실제 DB 공고에서 스트라타 추출 | fixture 중복 제외, 계약유형/기관/금액/지역/낙찰률 다양성 보장 |
| 거절 유형 | 기존 5유형 유지 + 신규 1유형(기관 미등록) | v4 측정에서 검증된 유형 커버리지 유지 |
| 반복 회차 | 3회 (최악값 대표값) | `latency_gate_protocol.md` §3 준수 |
| 승격 유지 기준 | numeric ≥55%, 문항통과 ≥10/48, forbidden 0건 등 8개 지표 | v4 e4b 성능(61.8%, 12/48) 대비 하한선 설정 |
| 동결 범위 | Git SHA 고정, 컨테이너 재시작 금지, 모델 변경 금지 | 2026-08-26 72회차 폐기 전례 준수 |
| 예상 소요 | 약 5~7시간 (문항제작 2-3h + 측정 1.5h + 채점 1-2h) | GPU 독점으로 병렬화 불가 |

---

## 3. 검증 결과

### 3.1 캡슐 요구사항 충족 확인

| 요구사항 (capsule.yaml required_change) | 충족 여부 | 비고 |
|------------------------------------------|-----------|------|
| 새 문항을 어디서 어떻게 뽑을지 정한다 | ✅ | §2.2 DB 추출 쿼리, §2.3 스트라타 명시 |
| 기존 fixture와 겹치지 않게 하는 기준 | ✅ | §2.1 제외 notice_id 리스트, 동일 공고 금지 |
| 필요한 문항 수와 반복 회차 근거 | ✅ | §2.3 32문항 근거, §6 3회 반복 근거 |
| 정답 근거(evidence) 생성·검증 절차 | ✅ | §3.1 파이프라인, §3.2 스크립트 사양, §3.3 체크리스트 |
| 거절 문항 구조 유지 방안 | ✅ | §2.4 5유형 유지 + 1유형 추가 |
| 승격 재검토 판정 기준 숫자 못박기 | ✅ | §5.1 필수 8지표, §5.2 조건부 2지표 |
| 예상 소요·공유 자원·동결 범위 | ✅ | §7.1 자원, §7.2 동결, §7.3 소요 |

### 3.2 수락 기준 충족 확인

| 수락 기준 (capsule.yaml acceptance) | 충족 여부 |
|--------------------------------------|-----------|
| 다음 세션이 이 문서만 보고 문항 제작 착수 가능 | ✅ (§10 실행 가이드, FAQ 포함) |
| 판정 기준을 측정 전 숫자로 못박음 | ✅ (§5 표로 명시) |
| 레이턴시 게이트 규약과 충돌 안 함 | ✅ (§6 반복/대표값 규약 준수) |
| 저장소 문서 표준 준수 (마크다운 위계, 메타데이터, 표 우선, 이모지 금지) | ✅ |
| scope 밖 파일 수정 안 함, 측정 실행 안 함 | ✅ |

### 3.3 자동 검증 명령 실행

```bash
python3 scripts/validate_agent_rules.py --quiet
```

**결과**: 통과 (exit code 0)

---

## 4. 변경 파일 목록

| 파일 | 상태 | 비고 |
|------|------|------|
| `docs/ops/llm_generalization_measurement_design.md` | 신규 작성 | 측정 설계 정본 |
| `docs/analysis/task_08afb35c2a9e.md` | 신규 작성 | 본 수행 기록 |

---

## 5. 잔여 작업 및 인수인계

### 5.1 완료된 것
- 설계서 작성 완료 (측정 실행 준비 상태 달성)
- 모든 캡슐 요구사항 충족
- 검증 명령 통과

### 5.2 다음 세션이 할 일 (측정 실행 단계)
1. `scripts/build_generalization_fixture.py` 작성 및 실행으로 문항 초안 생성
2. 사람 2인 교차 검증으로 `llm_quality_fixture_v2.json` 확정
3. 환경 동결 선언 후 e2b/e4b 순차 3회 측정 실행
4. 수동 채점(proposition, semantic) 수행
5. §5 판정 기준 적용해 승격 유지/재검토 결정
6. `llm_generalization_judgment_YYYYMMDD.md` 작성

### 5.3 주의사항 (차단 요인)
- **GPU 독점 필요**: Ollama 컨테이너가 GPU를 독점하므로 다른 측정과 병렬 실행 불가
- **저장소 동결 필수**: 측정 중(약 2시간) Git 푸시/병합/컨테이너 재시작 절대 금지
- **모델 사전 풀링**: `gemma4:e2b`, `gemma4:e4b` 둘 다 `ollama pull` 완료되어 있어야 함

---

## 6. 커밋 정보

- **branch**: `task/08afb35c2a9e-generalization-design` (작업 브랜치)
- **commit**: (작성 후 커밋 예정)
- **commit_count**: 1 (예정)
