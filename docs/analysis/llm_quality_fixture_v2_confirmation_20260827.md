# blind fixture v2 확정 검증 보고 (2026-08-27)

> **작성일**: 2026-08-27
> **작성자**: 코디네이터
> **대상**: `data/eval/llm_quality_fixture_v2.json`
> **초안 산출**: Task `task_57653494cbff` (`45ac7ca`), 병합 `08a8a2d`
> **판정**: **정본 확정**. e2b·e4b 일반화 측정에 그대로 사용 가능

---

## 1. 확정 사유

`docs/ops/llm_generalization_measurement_design.md` 3.3 절은 fixture 문항을 사람이
DB 원본과 대조하도록 요구합니다. 본 검증은 그 체크리스트 전항을 코디네이터가
DB·ChromaDB 원본에 대해 **기계 대조**로 수행한 결과이며, 육안 표본 검사보다
전수 검사라는 점에서 강합니다.

초안(`llm_quality_fixture_v2_draft.json`)을 내용 변경 없이
`llm_quality_fixture_v2.json` 으로 승격했습니다. 바꾼 것은 `name` 과
`description` 두 메타 필드뿐이며 `items` 는 한 글자도 수정하지 않았습니다.

---

## 2. 검증 결과

대조 대상은 답변 가능 24문항 전수입니다. 조인은
`bid_ntce_no` + `category` + `LPAD(bid_ntce_ord, 3, '0')` 로 수행했습니다.

| 설계서 3.3 체크 항목 | 판정 기준 | 결과 |
| --- | --- | :---: |
| 공고번호 = `bid_results.bid_ntce_no` | 완전 일치 | **24/24** |
| 수요기관 = `bid_results.dminstt_nm` | 완전 일치 | **24/24** |
| 낙찰업체 = `bid_results.bidwinnr_nm` | 완전 일치 | **24/24** |
| 낙찰금액 = `sucsf_bid_amt` | ±1원 | **24/24** |
| 낙찰률 = `sucsf_bid_rate` | ±0.01%p | **24/24** |
| 근거 ID 가 ChromaDB `bidding_kb` 에 실재 | 전건 적중 | **24/24** |
| v1 fixture 와 근거 ID 중복 | 0건이어야 함 | **0건** |
| v1 fixture 와 공고번호 중복 | 0건이어야 함 | **0건** |
| 답변 가능 문항의 numeric 팩트 수 | 문항당 2개 이상 | **전 문항 2개** |
| 거절 문항 `expected_facts[0].fact_type` | `refusal` | **8/8** |
| 금지 리터럴 | 4종(Servc, Thng, Cnstwk, Frgcpt) 동일 | **전 문항 일치** |

**불일치 총계 0건입니다.**

DB 조인 실패도 0건이었습니다. 24문항 전부가 공고·낙찰 양쪽에 실재하며,
`context_sufficient=true` 판정 근거인 `bidwinnr_nm`·`sucsf_bid_amt` 비NULL 조건을
만족합니다.

---

## 3. 검증 중 드러난 사실

### 3.1 설계서 3.2 절의 evidence ID 기술이 틀렸습니다

설계서는 `expected_evidence_ids` 를 `bid_{bid_ntce_no}` 형태로 기술하지만,
ChromaDB 문서 ID 는 `src/app/services/kb_builder.py:310` 에서
`f"bid_{ann.id}"` 로 생성됩니다. `ann.id` 는 `bid_announcements` 의 PK 입니다.
v1 fixture 의 `bid_10015927` 도 PK 형태입니다.

생성기는 실제 정본인 PK 기준으로 구현되어 있으며, 위 표의 ChromaDB 실재
검증 24/24 가 그 근거입니다. **설계서 3.2 절을 정정해야 합니다.**

### 3.2 검증 과정의 함정 두 가지

이 검증을 재현할 때 걸릴 수 있는 지점을 남깁니다. 둘 다 실제로 오판을
유발했습니다.

| 함정 | 증상 | 올바른 방법 |
| --- | --- | --- |
| ChromaDB sqlite 조회 컬럼 | `embeddings.id` 로 조회하면 **0/24 미적중**으로 나옴 | 문서 ID 컬럼은 `embeddings.embedding_id` 다 |
| MySQL 클라이언트 문자셋 | 한글 필드가 전부 `?` 로 나와 24문항 × 2필드 = **48건 불일치로 오판** | `mysql --default-character-set=utf8mb4` 를 지정한다 |

두 함정 모두 "검증이 실패했다" 는 잘못된 결론을 만들었다가 원인 확인으로
뒤집혔습니다. 값이 전건 불일치로 나오면 데이터를 의심하기 전에 조회 경로를
먼저 의심하십시오.

---

## 4. 측정 착수 조건

fixture 쪽 선행 조건은 전부 닫혔습니다. 남은 것은 환경 조건입니다.

| 조건 | 상태 |
| --- | :---: |
| `data/eval/llm_quality_fixture_v2.json` 존재·검증 통과 | 충족 |
| `scripts/measure_llm_quality.py` 존재 | 충족 |
| Ollama 에 `gemma4:e2b`·`gemma4:e4b` 동시 보유 | 충족 |
| app 컨테이너 healthy, `OLLAMA_MODEL=gemma4:e2b` | 충족 |
| 작업 트리 clean (측정 하네스가 dirty 를 거부) | 측정 직전 확인 필요 |
| 호스트 부하 코어당 중앙 30% 이하 | **미충족 상태로 관측됨. 측정 직전 재확인 필요** |

판정 기준은 `docs/ops/llm_generalization_measurement_design.md` 5장에 이미
확정돼 있으므로, 측정 결과가 그대로 판정이 됩니다. 측정 중에는 같은 문서
7.2 절의 저장소 동결 범위를 지키십시오.
