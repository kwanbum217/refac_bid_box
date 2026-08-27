# LLM 일반화 측정 설계서

> **updated_at**: 2026-08-26
> **version**: v1.0.0
> **status**: 설계 완료 (측정 미실행)
> **목적**: fixture 밖 일반화 측정을 위한 완전한 실행 설계. 다음 세션이 문항 제작부터 다시 고민하지 않고 측정만 실행하면 되는 상태를 만든다.

---

## 1. 배경과 목적

### 1.1 문제 정의

현재 `gemma4:e2b` 승격 근거는 24문항 fixture(`data/eval/llm_quality_fixture_v1.json`) 안에서만 성립한다. fixture 문항은 DB 실재 공고 16건 + 거절 8건으로 구성되어 모델이 이미 학습·노출된 분포다. **e2b는 e4b보다 작은 모델이므로 fixture 밖 분포(미노출 공고, 다른 기관/업종/금액대)에서 성능이 뒤집힐 수 있다.** 그대로 컷오버하면 운영에서 발견하게 된다.

### 1.2 설계 범위

- **이 문서가 다루는 것**: 문항 수집·제작 절차, 증거 구축·검증, 채점 축·판정 기준, 반복 회차·표본 수, 공유 자원·동결 범위, 예상 소요
- **이 문서가 다루지 않는 것**: 실제 측정 실행, 문항 파일 생성, 측정 스크립트 수정

---

## 2. 문항 수집 및 제작 설계

### 2.1 기존 fixture 분석 (중복 방지 기준)

| 구분 | 개수 | 비율 | 특징 |
|------|------|------|------|
| context_sufficient=True (답변 가능) | 16 | 66.7% | 실재 공고 16건, 각 3~5개 사실(numeric 2~3개 포함) |
| context_sufficient=False (거절 기대) | 8 | 33.3% | 미래/해외/미개찰/비공개/결과 없음 5가지 유형 |
| **총계** | **24** | **100%** | |

**중복 방지 규칙**: 새 문항은 기존 16건의 `expected_evidence_ids`(`bid_10015927` 등)와 **공고번호가 겹치지 않아야 한다.** 동일 공고에서 다른 사실을 묻는 것도 금지한다(동일 분포 노출).

### 2.2 신규 문항 소스: 실제 DB 공고에서 추출

**대상 테이블**: `bid_announcements` (입찰공고), `bid_results` (낙찰결과)

두 테이블은 `bid_ntce_no`(공고번호) + `category`(업무구분) + `bid_ntce_ord`(공고차수)로 조인합니다. 차수는 `bid_announcements`가 3자리(`000`), `bid_results`가 2자리(`00`)로 오므로 정규화(`zfill(3)[-3:]`) 후 조인해야 합니다(`src/ml/dataset.py`의 `_normalized_ord` 참조).

**추출 쿼리 원칙**:
```sql
-- fixture 기 사용 공고 제외 (bid_ntce_no 기준)
WHERE r.bid_ntce_no NOT IN ('R26BK01659912-001', 'R26BK01660507-001', ...)
  AND r.bidwinnr_nm IS NOT NULL       -- 낙찰업체 존재
  AND r.sucsf_bid_amt IS NOT NULL     -- 낙찰금액 존재
  AND r.sucsf_bid_rate IS NOT NULL    -- 낙찰률 존재
  AND r.dminstt_nm IS NOT NULL        -- 수요기관명 존재
```

**다양성 보장 스트라타(층화)**:
| 스트라타 | 기준 | 최소 할당 |
|----------|------|-----------|
| 공사/용역/물품 | `bid_results.category` (Cnstwk/Servc/Thng) | 각 2건 이상 |
| 기관 유형 | 광역/기초/교육청/공기업/기타 (`dminstt_nm` 분석) | 각 1건 이상 |
| 금액 구간 | 1억 미만 / 1~5억 / 5~10억 / 10억 이상 (`sucsf_bid_amt`) | 각 2건 이상 |
| 지역 | 수도권/비수도권 (`dminstt_nm`에서 시도 추출) | 각 4건 이상 |
| 낙찰률 구간 | 85% 미만 / 85~95% / 95% 초과 (`sucsf_bid_rate`) | 각 2건 이상 |

### 2.3 신규 문항 수: **32문항** (답변 가능 24 + 거절 8)

**근거**:
- 기존 fixture 24문항 대비 **1.33배**로 통계적 검정력 확보
- 답변 가능 24문항: numeric 팩트 2개×24=48개 원자 판정 → Wilson 95% CI 상한 ≈ 0.15 (충분)
- 거절 8문항: 기존 5유형(미래/해외/미개찰/비공개/결과없음) 각 1~2건 유지, 유형별 최소 1건 보장
- **3회 반복 × 32문항 = 96회 질의/모델** → 측정 시간 약 45분/모델 (c1 순차 기준)

### 2.4 거절 문항 구조 유지 (기존 5유형 + 신규 3유형)

| 유형 | 기존 개수 | 신규 개수 | 설명 |
|------|-----------|-----------|------|
| 미래 시점 공고/낙찰 | 2 (q17, q21) | 2 | 2027년 이후 예정가격/낙찰 예측 불가 |
| 해외 조달 | 2 (q19, q22) | 1 | EU/GSA 등 수집 범위 외 |
| 미개찰 공고 | 1 (q20) | 2 | 개찰 전 낙찰 결과 제공 불가 |
| 비공개 내부 정보 | 1 (q23) | 1 | 심사위원 채점표 등 비공개 자료 |
| 결과 없는 공고 | 1 (q24) | 1 | 공고만 있고 낙찰 결과 없음 |
| **신규: 기관 미등록 공고** | 0 | 1 | 수요기관이 DB에 없는 공고 |

**거절 판정 기준**: `measure_llm_quality.py`의 `REFUSAL_PATTERNS`와 동일 적용. `refusal_expected=true` 문항에서 실제 거절이면 정답, 답변이면 오답.

---

## 3. 정답 근거(evidence) 구축 및 검증 절차

### 3.1 증거 생성 파이프라인

```
1. 공고 선정 (스트라타 충족, fixture 중복 제외)
   ↓
2. 자동 근거 추출 스크립트 실행
   - bid_announcements + bid_results JOIN (bid_ntce_no + category + 정규화된 bid_ntce_ord)
   - 공고번호, 수요기관, 낙찰업체, 낙찰금액, 낙찰률, 계약유형, 지역 추출
   ↓
3. 사람 검증 (2인 교차)
   - 추출된 JSON을 사람이 DB 원본과 대조
   - 불일치 시 원본 우선, 재추출
   ↓
4. fixture 포맷 변환
   - expected_facts: proposition(문자열) + numeric(수치+허용오차) 분리
   - forbidden_literals: 기존 4개(Servc, Thng, Cnstwk, Frgcpt) 유지
   - semantic_forbidden_claims: 자기모순/허위낙찰 등 문항별 추가
   - citation_required: context_sufficient=True 문항만 true
   ↓
5. 최종 fixture 파일 저장: data/eval/llm_quality_fixture_v2.json
```

### 3.2 자동 추출 스크립트 사양 (별도 파일로 제공)

**파일**: `scripts/build_generalization_fixture.py`

**입력**: 제외할 `bid_ntce_no` 리스트, 스트라타별 최소 할당 수
**출력**: fixture v2 포맷 JSON (사람 검증 전 초안)

**조인 로직** (src/ml/dataset.py `_normalized_ord` 재사용):
```python
# bid_announcements(bid_ntce_ord: 3자리) ↔ bid_results(bid_ntce_ord: 2자리)
normalized_ord = bid_ntce_ord.zfill(3)[-3:]  # 양쪽 모두 3자리로 정규화
JOIN ON a.bid_ntce_no = r.bid_ntce_no
    AND a.category = r.category
    AND a.bid_ntce_ord = normalized_ord
```

**검증 규칙**:
- `expected_value`의 numeric 타입은 문자열로 저장, `tolerance`는 float
- 낙찰금액 tolerance=1원, 낙찰률 tolerance=0.01%p 고정
- `expected_evidence_ids`는 `bid_{bid_announcements.id}` 형태다. ChromaDB 문서 ID 가 `src/app/services/kb_builder.py:310` 에서 PK 기준으로 만들어지며 v1 fixture 도 같은 형태다. 2026-08-27 이전 판본은 이를 `bid_{bid_ntce_no}` 로 잘못 적었다
- `context_sufficient`는 낙찰 결과 존재 여부(`bidwinnr_nm` 및 `sucsf_bid_amt` 비NULL)로 자동 판정
- 수요기관: `r.dminstt_nm` 우선, 없으면 `a.dminstt_nm` 사용
- 공고명: `r.bid_ntce_nm` 우선, 없으면 `a.bid_ntce_nm` 사용

### 3.3 사람 검증 체크리스트 (필수)

- [ ] 공고번호가 DB `bid_results.bid_ntce_no` (또는 `bid_announcements.bid_ntce_no`)와 일치
- [ ] 수요기관이 `bid_results.dminstt_nm` (우선) 또는 `bid_announcements.dminstt_nm`와 일치
- [ ] 낙찰업체가 `bid_results.bidwinnr_nm`과 일치
- [ ] 낙찰금액이 `bid_results.sucsf_bid_amt`와 ±1원 이내
- [ ] 낙찰률이 `bid_results.sucsf_bid_rate`와 ±0.01%p 이내
- [ ] 업무구분이 `bid_results.category` (Thng/Cnstwk/Servc/Frgcpt)와 일치
- [ ] 금지 리터럴 4개(Servc, Thng, Cnstwk, Frgcpt)가 응답에 나오면 안 됨 확인
- [ ] 거절 문항의 `refusal_expected=true` 및 `expected_facts[0].fact_type="refusal"`

---

## 4. 채점 축 및 자동/수동 판정 분리

### 4.1 자동 판정 항목 (measure_llm_quality.py 재사용)

| 축 | 판정 로직 | 통과 기준 |
|------|-----------|-----------|
| **numeric 팩트** | 응답 본문에서 기대 수치 ±허용오차 내 탐색 | 문항당 모든 numeric 팩트 발견 |
| **forbidden_literals** | 4개 영문 코드 대소문자 무시 검색 | 위반 0건 |
| **citation_required** | 대괄호 숫자 인용 `\[\d+\]` 존재 여부 | context_sufficient=True 문항에서 인용 필수 |
| **evidence_hit** | 검색된 문서 ID가 `expected_evidence_ids` 포함 여부 | Recall ≥ 0.5 (최소 1개 이상 적중) |
| **refusal 정확도** | `is_refusal()` 판정 결과 vs `refusal_expected` 일치 | 일치 |

### 4.2 수동 판정 항목 (사람 채점 필요)

| 축 | 판정 방식 | 루브릭 |
|------|-----------|--------|
| **proposition 팩트** | 문자열 일치 불가 → 사람 판정 | 문항별 `scoring_rubric` 참조 (10점 만점) |
| **semantic_forbidden_claims** | 자기모순/허위 주장 문자열 매칭 불가 → 사람 판정 | 위반 시 0점 |
| **과잉응답** | 거절 기대 문항에서 답변 생성 시 | 0점 |
| **과잉거절** | 답변 가능 문항에서 거절 시 | 0점 |

### 4.3 종합 점수 계산

```
자동_점수 = (numeric_정답률 × 30) + (forbidden_위반없음 × 20) +
            (citation_적중률 × 15) + (evidence_recall × 15) +
            (refusal_정확도 × 20)   [100점 만점]

수동_점수 = (proposition_정답률 × 60) + (semantic_위반없음 × 20) +
            (과잉응답_없음 × 10) + (과잉거절_없음 × 10)   [100점 만점]

최종_점수 = (자동_점수 + 수동_점수) / 2
```

---

## 5. 승격 재검토 판정 기준 (사전 못박기)

**핵심 원칙**: 측정 **전에** 숫자로 기준을 못박는다. 측정 후 기준을 정하는 여지를 남기지 않는다.

### 5.1 필수 통과 기준 (모두 충족해야 e2b 승격 유지)

| 지표 | e4b 기준선(v4 측정) | e2b 통과 기준 | 판정 방식 |
|------|---------------------|---------------|-----------|
| **numeric 팩트 정답률** | 동일 blind fixture 동시 실측치 (v4 참고: 61.8%) | **동일 blind fixture 의 e4b 값 이상 이면서 ≥ 55.0%** | 3회 반복 최악값 |
| **문항 단위 통과율** | 12/48 (25.0%) | **≥ 10/48** (20.8%) | 3회 반복 최악값 |
| **forbidden 리터럴 위반** | 0/48 | **0/48** (완전 일치) | 3회 반복 최악값 |
| **evidence recall** | 미측정 | **≥ 0.50** | 3회 반복 최악값 |
| **citation 적중률** | 미측정 | **≥ 0.70** | 3회 반복 최악값 |
| **refusal 정확도** | 24/24 (100%) | **≥ 22/24** (91.7%) | 3회 반복 최악값 |
| **과잉응답** | 0/24 | **0/24** | 3회 반복 최악값 |
| **과잉거절** | 0/48 | **≤ 2/48** (4.2%) | 3회 반복 최악값 |

> **분모 설명**: numeric 팩트 102개(답변 가능 16문항 × 반복 3회 × 문항당 평균 2~3개 팩트), 문항 단위 48회(16문항 × 3회), refusal 24회(거절 8문항 × 3회), 과잉응답 24회(거절 문항만 해당), 과잉거절 48회(답변 가능 문항만 해당).

> **확정 판정 기준 및 근거**: blind fixture 에서 e2b 와 e4b 를 동일 조건으로 함께 측정하고, e2b 승격 유지 조건은 (A) e2b numeric 정답률이 같은 blind fixture 의 e4b numeric 정답률 이상이고 (B) e2b numeric 정답률이 55.0% 이상인 두 조건을 모두 만족하는 것입니다. 하나라도 미달이면 e2b 승격을 철회 후보로 올립니다. v4 fixture 의 61.8% 는 분포가 다른 fixture 의 값이므로 blind fixture 의 절대 문턱으로 이식하지 않으며(동일 blind fixture 에서의 상대 비교가 정본), 55.0% 는 모델 선택 문턱이 아니라 두 모델 모두 미달이면 RAG 답변 생성 자체의 실패로 판정하는 바닥선입니다.

### 5.2 조건부 통과 기준 (하나라도 미달 시 재검토)

| 지표 | e2b 기준 | 미달 시 조치 |
|------|----------|-------------|
| **P50 레이턴시** | ≤ 3,500ms (v4 e2b: 2,681.6ms) | e4b 재검토 또는 모델 교체 |
| **수동 proposition 점수** | ≥ 50/100 | e4b 재검토 |

### 5.3 판정 로직 요약

```
IF (e2b_numeric >= e4b_blind_numeric) AND (e2b_numeric >= 55.0%)
   AND (기타_필수_통과_기준_충족) AND (조건부_통과_기준_충족):
    결과 = "e2b_승격_유지"
ELSE:
    결과 = "e2b_승격_재검토_필요"  # e4b 복귀 또는 대체 모델 탐색
```

**중요**: blind fixture 에서 e2b 와 e4b 를 동일 조건으로 함께 측정하며, e2b 가 **blind fixture 에서 동일 조건으로 측정한 e4b 값 아래**로 떨어지거나 바닥선 55.0% 에 미달하면 승격 근거가 소멸한다 (e2b 승격 철회 후보 상정). v4 측정치(e4b 61.8%)는 참고치일 뿐 blind fixture 의 절대 기준으로 적용하지 않는다.

---

## 6. 반복 회차 및 표본 수 설계

### 6.1 반복: **3회** (레이턴시 게이트 규약 준수)

- **근거**: `latency_gate_protocol.md` §3 "최소 반복 회차 3회, 판정 대표값은 회차별 값 중 최악값"
- **회차 간 간격**: 직전 회차 종료 후 30초 이상 (규약 §3)
- **대표값**: 3회 중 **최악값(worst)** 사용

### 6.2 표본 수: 문항당 1회 질의 × 3회 반복 = 3회/문항

- LLM 품질 측정은 레이턴시 게이트와 달리 **동시성 부하가 아닌 정확도 측정**이므로 표본 수 = 반복 회차
- 각 문항을 3번 물어 일관성 확인 (확률적 생성 모델의 분산 포착)
- 총 질의 수: 32문항 × 3회 = **96회/모델**

### 6.3 측정 대상 모델: **gemma4:e2b** (승격 대상) + **gemma4:e4b** (비교 기준선)

- 동일 컨테이너에서 `OLLAMA_MODEL` 환경변수만 교체하여 순차 측정
- 측정 순서: e2b 3회 → e4b 3회 (또는 교차 측정으로 호스트 드리프트 상쇄)
- **동일 Git SHA, 동일 컨테이너 이미지, 동일 호스트**에서 수행 필수

---

## 7. 공유 자원, 동결 범위, 예상 소요

### 7.1 공유 자원 (직렬 점유 필요)

| 자원 | 점유 형태 | 비고 |
|------|-----------|------|
| **Ollama GPU** | 독점 | 모델 로드/언로드 시 VRAM 경합. 동시 측정 금지 |
| **app 컨테이너** | 독점 | `/api/v1/chatbot/query` 엔드포인트 단독 사용 |
| **ChromaDB** | 읽기 전용 공유 가능 | 검색만 수행하므로 타 읽기 작업과 공유 가능 |
| **MySQL** | 읽기 전용 공유 가능 | 증거 구축 시에만 읽기, 측정 중엔 불필요 |

### 7.2 저장소 동결 범위 (측정 중 절대 금지)

**측정 시작 전 커밋 SHA 고정**. 측정 기간(약 2시간) 동안:
- `main` 브랜치 푸시 금지
- 작업 브랜치 병합 금지
- `docker compose restart app` 금지
- `OLLAMA_MODEL` 환경변수 변경 금지 (스크립트만 변경)
- ChromaDB 재색인 금지

> **전례**: 2026-08-26 측정 중 병합으로 72회차를 전량 폐기한 적이 있다. 동결 위반 시 측정 무효.

### 7.3 예상 소요 시간

| 단계 | 소요 | 비고 |
|------|------|------|
| 문항 제작 (자동 추출 + 사람 검증) | 2~3시간 | 32문항 × 검증 |
| fixture 파일 최종화 | 30분 | JSON 포맷 검증 포함 |
| e2b 3회 측정 | 45분 | c1 순차, 문항당 ~15초 |
| e4b 3회 측정 | 45분 | 동일 조건 |
| 수동 채점 (proposition + semantic) | 1~2시간 | 2인 교차 채점 |
| 결과 집계·판정 | 30분 | 스크립트 자동화 가능 |
| **총계** | **약 5~7시간** | 병렬화 불가 (GPU 독점) |

---

## 8. 실행 전 사전 체크리스트 (측정 당일)

### 8.1 환경 검증 (스크립트 자동 수행)

- [ ] `docker compose ps` → app, ollama, chromadb, mysql, redis 모두 healthy
- [ ] `docker exec refac_bid_box-app-1 printenv OLLAMA_MODEL` → 기대 모델과 일치
- [ ] `curl -s http://localhost:8000/health` → 200 OK
- [ ] ChromaDB `bidding_kb` 컬렉션 문서 수 확인 (최근 색인 기준)
- [ ] Git 상태: `git status --porcelain` 빈 출력 (dirty 아님)
- [ ] Git SHA 기록: `git rev-parse HEAD` → 측정 문서에 기재

### 8.2 호스트 부하 기준 (레이턴시 게이트 규약 §5.3 준수)

- 측정 전 5분간 코어당 사용률 중앙값 ≤ 30%, 최대 ≤ 50% 확인
- 초과 시 측정 연기

### 8.3 측정 스크립트 실행 명령 (예시)

```bash
# e2b 측정
python3 scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --model-label "gemma4:e2b_generalization" \
  --expected-model "gemma4:e2b" \
  --repetitions 3 \
  --app-container refac_bid_box-app-1 \
  --output data/benchmarks/llm_gen_e2b_$(date +%Y%m%d_%H%M).json

# e4b 측정 (동일 fixture, 동일 조건)
python3 scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --model-label "gemma4:e4b_generalization" \
  --expected-model "gemma4:e4b" \
  --repetitions 3 \
  --app-container refac_bid_box-app-1 \
  --output data/benchmarks/llm_gen_e4b_$(date +%Y%m%d_%H%M).json
```

---

## 9. 산출물 및 보관

### 9.1 산출 파일

| 파일 | 설명 | 보관 위치 |
|------|------|-----------|
| `llm_quality_fixture_v2.json` | 신규 32문항 fixture (정본) | `data/eval/` |
| `llm_gen_e2b_YYYYMMDD_HHMM.json` | e2b 3회 반복 원시 결과 | `data/benchmarks/` |
| `llm_gen_e4b_YYYYMMDD_HHMM.json` | e4b 3회 반복 원시 결과 | `data/benchmarks/` |
| `llm_generalization_judgment_YYYYMMDD.md` | 수동 채점 포함 종합 판정문 | `docs/analysis/` |

### 9.2 보존 방침 (레이턴시 게이트 규약 §8 준수)

- 판정 근거로 인용된 측정치: **영구 보존**
- 탐색용 중간 산출물: 판정 완료 후 폐기
- 무효 측정치(동결 위반, 모델 불일치 등): **즉시 삭제**, 사유 기록

---

## 10. 다음 세션 실행 가이드 (이 문서만 보고 실행 가능)

### 10.1 단계별 실행 순서

1. **문항 제작** (이 문서 §2, §3 참조)
   ```bash
   python3 scripts/build_generalization_fixture.py \
     --exclude-notice-ids "10015927,10015878,..." \
     --output data/eval/llm_quality_fixture_v2_draft.json
   ```
   → 사람 2인 교차 검증 → `llm_quality_fixture_v2.json` 확정

2. **환경 준비 및 동결**
   - Git 커밋 확정, `main` 푸시/병합 금지 선언
   - Ollama에서 `gemma4:e2b`, `gemma4:e4b` 둘 다 `ollama pull` 완료 확인
   - 호스트 부하 기준 확인

3. **측정 실행** (이 문서 §8.3 명령 사용)
   - e2b 3회 → e4b 3회 순차 실행
   - 각 회차 사이 30초 이상 대기

4. **수동 채점**
   - `llm_quality_fixture_v2.json`의 `scoring_rubric` 기준으로 proposition/semantic 채점
   - 2인 독립 채점 후 불일치 조정

5. **판정 및 기록**
   - §5 기준 적용하여 pass/fail 결정
   - `llm_generalization_judgment_YYYYMMDD.md` 작성

### 10.2 자주 묻는 질문 (FAQ)

| 질문 | 답변 |
|------|------|
| fixture v1을 수정해서 쓰면 안 되나? | **안 됨**. v1은 정본으로 보존하고 v2를 새로 만든다. v1과의 비교를 위해 원본 유지 필수. |
| 문항 수를 더 늘리면 안 되나? | 32문항이 통계적 검정력(Wilson CI)과 측정 시간(45분/모델)의 균형점. 늘리려면 사전 합의 필요. |
| 거절 문항 유형을 바꿔도 되나? | **5대 유형(미래/해외/미개찰/비공개/결과없음)은 필수 유지**. 신규 유형만 추가 가능. |
| 측정 중 컨테이너 재시작해도 되나? | **절대 안 됨**. 동결 위반으로 측정 무효. |
| e2b만 측정하고 e4b는 생략해도 되나? | **안 됨**. 비교 기준선(동일 blind fixture 에서의 e4b 실측치)이 없으면 상대 판정 불가. |

---

## 11. 변경 이력

| 버전 | 일자 | 변경 내용 | 작성자 |
|------|------|-----------|--------|
| v1.0.0 | 2026-08-26 | 최초 작성 (Task capsule 기반 설계 완료) | Investigator |
| v1.1.0 | 2026-08-27 | 코디네이터 확정 판정 기준 반영 (동일 blind fixture e4b 상대 비교 + 바닥선 55.0%), 정책 충돌 해소 | Builder |

---

> **이 문서는 측정 실행 전 최종 승인을 받은 정본입니다.** 측정 중 기준 변경은 금지되며, 불가피한 변경 시 별도 승인 문서를 남겨야 합니다.
