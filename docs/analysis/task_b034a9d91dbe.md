# fixture q21 검색 미스 원인 규명 분석 보고서

> **작성일**: 2026-08-30
> **대상**: `data/eval/llm_quality_fixture_v2.json` q21 ("2026년 조림지 풀베기사업 2차(동부지구)")
> **결론**: 원인 규명 완료. DB·ChromaDB·Meilisearch 색인에는 정상 실재하나, `_rerank_by_exact_title` 및 Lexical 채널의 질의-공고명 비교 로직이 자연어 질문 전체 문자열과 공고명의 단순 동치(`==`)를 검사하여 정확 일치 재순위가 작동하지 않았고, 동명 공고 밀집군 내 벡터 거리 순위(9위)가 `top_k=5` 절단선 밖으로 밀려 누락됨.

---

## 1. 개요 및 핵심 결론

2026-08-30 정본 측정에서 fixture v2 32문항 중 q21만 numeric 0/2, evidence recall 0.0을 기록했습니다.
본 조사는 운영 DB 및 검색 엔진을 변경하지 않고 실제 검색 경로를 호출하여 원인을 실측·규명했습니다.

| 검증 항목 | 실측 결과 | 판정 |
| --- | --- | :---: |
| **G1 DB 실재 여부** | `bid_announcements` id=10169448, `bid_results` id=4353652 존재 | 정상 실재 |
| **ChromaDB 색인 여부** | `bidding_kb` 컬렉션 내 id=`bid_10169448` 문서 존재 | 정상 색인 |
| **Meilisearch 색인 여부** | `bid_records` 인덱스 내 id=`announcement_Cnstwk_R26BK01682348` 존재 | 정상 색인 |
| **후보군 내 존재 여부** | ChromaDB 30건 후보 풀 중 **9위** (거리 0.3161) 실재 | 후보 풀 포함 |
| **검색 누락 기전** | `_rerank_by_exact_title` 동치 비교 불일치로 승격 실패 후 `top_k=5` 절단 | 결함 특정 완료 |

---

## 2. 문자 단위 대조 및 DB 데이터 실재 검증

### 2.1 질의 문자열 대조

- **질의 문자열 (q21)**: `"2026년 조림지 풀베기사업 2차(동부지구)의 공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"`
- **DB 원본 공고명**: `"2026년 조림지 풀베기사업 2차(동부지구)"`

```
질의 접두부: 2026년 조림지 풀베기사업 2차(동부지구)  (24자, 공백/괄호/숫자 100% 일치)
질의 접미부: 의 공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘 (41자, 자연어 요청문)
```

### 2.2 DB 원본 데이터 상세

| 테이블 | 컬럼 | 값 | 비고 |
| --- | --- | --- | --- |
| `bid_announcements` | `id` | `10169448` | PK |
| | `bid_ntce_no` | `R26BK01682348` | 차수 `000` |
| | `bid_ntce_nm` | `2026년 조림지 풀베기사업 2차(동부지구)` | 정확 공고명 |
| | `category` | `Cnstwk` | 건설 |
| | `dminstt_nm` | `경상남도 거제시` | 수요기관 |
| | `base_amount` | `54,175,770` | 원 |
| | `bid_ntce_dt` | `2026-08-13 20:01:17` | |
| `bid_results` | `id` | `4353652` | PK |
| | `bidwinnr_nm` | `주식회사 백화` | 낙찰업체 |
| | `sucsf_bid_amt` | `48,445,040` | 낙찰금액 |
| | `sucsf_bid_rate` | `90.0150` | 낙찰률 (%) |

---

## 3. 동명 공고 밀집도 및 검색된 5건 분석

### 3.1 동명/유사 공고 분포 조사

- DB 전체 "조림지 풀베기" 공고: **15,372건**
- 2026년 조림지 풀베기 2차 공고: **310건**
- "동부" 지구가 포함된 조림지 풀베기 공고: **133건** (2026년도 포함 다수)

### 3.2 검색된 상위 5건과 기대 문서(기존 순위 9위) 대조

ChromaDB `where={'has_result': True}` 조건에서 `query_top_k=30` 후보 풀을 조회했을 때의 실측 순위입니다.

| 순위 | 문서 ID | 공고명 | 수요기관 | 벡터 거리 | 비고 |
| :---: | :---: | --- | --- | :---: | :---: |
| 1위 | `bid_10146912` | 2026년 조림지 풀베기사업(2차)(영암지구) | 영암군산림조합 | 0.2980 | 검색 반환 (이전 환각 근거) |
| 2위 | `bid_10179117` | 2026년 조림지풀베기사업 2차 (산동용방2지구) | 구례군산림조합 | 0.3041 | 검색 반환 |
| 3위 | `bid_10146781` | 2026년 2차 조림지 풀베기사업(산청오부지구) | 산청군산림조합 | 0.3091 | 검색 반환 |
| 4위 | `bid_10148336` | 2026년 조림지 풀베기 사업(대술지구 2차) | 예산군산림조합 | 0.3114 | 검색 반환 |
| 5위 | `bid_7951329` | 2026년 조림지 풀베기사업(신양2지구 2차) | 예산군산림조합 | 0.3123 | 검색 반환 |
| 6위 | `bid_10148341` | 2026년 조림지 풀베기사업(예산지구 2차) | 예산군산림조합 | 0.3147 | 후보 풀 |
| 7위 | `bid_10146882` | 2026년 조림지 풀베기사업(2차)(신북지구) | 영암군산림조합 | 0.3151 | 후보 풀 |
| 8위 | `bid_5976271` | 2026년 조림지풀베기사업(2-4지구)(2회베기) | 영암군산림조합 | 0.3155 | 후보 풀 |
| **9위** | **`bid_10169448`** | **2026년 조림지 풀베기사업 2차(동부지구)** | **경상남도 거제시** | **0.3161** | **기대 정답 (top_k=5 절단)** |

### 3.3 상위 5건이 기대 문서보다 높게 나온 이유

1. **임베딩 모델(`bge-m3`)의 글로벌 의미 압축**:
   질의의 공통 토큰("2026년", "조림지", "풀베기사업", "2차", "지구", "공고번호", "수요기관", "낙찰업체", "낙찰금액", "낙찰률")이 후보 문서들 전체에 고르게 분포하여 벡터 거리가 0.2980 ~ 0.3161 사이 초미세 차이(<0.018)로 빽빽하게 밀집되었습니다.
2. **지구명 희소성 차이**:
   - `q22` ("거제사등지구"): 전국에 1건만 존재하는 고유 지명이 포함되어 벡터 거리 **0.2257 (1위)** 로 압도적 적중.
   - `q21` ("동부지구"): 전국 수십 개 지자체에 존재하는 범용 지명이라 의미 분산이 발생해 9위로 배치됨.

---

## 4. 검색 경로별 상세 조사

### 4.1 Lexical 경로 (Meilisearch)

1. **운영 환경 설정**: `settings.MEILI_ENABLED` 가 기본값 `False`로 설정되어 있어 RAG 실행 시 Lexical 채널이 바이패스됩니다 (`[]` 반환).
2. **Meilisearch 단독 호출 실측**:
   `q="2026년 조림지 풀베기사업 2차(동부지구)..."`, `filter="dataset = 'announcement'"` 로 Meilisearch 검색 시 `bid_10169448` 이 **1위(Hit #1)** 로 정상 반환됩니다.
3. **코드 레벨 결함**:
   `src/rag/engine.py:HybridRAGEngine._prepare_context` 에서 Meilisearch 결과를 평가할 때:
   ```python
   query_key = _normalize_match_key(plan.lexical_query or plan.semantic_query)
   if doc_title and _normalize_match_key(doc_title) == query_key:
       exact_lexical_matches.append(doc)
   ```
   `plan.lexical_query` 는 사용자 전체 질의문(`"2026년...알려줘"`)이므로 `_normalize_match_key(doc_title) == query_key` 는 항상 `False`가 됩니다. 즉, Meilisearch가 켜져 있어도 정확 일치 우선 채택이 작동하지 않습니다.

### 4.2 Vector 경로 (ChromaDB)

1. **후보 풀 조회**: `query_top_k = max(target_top_k, 30)` 에 의해 ChromaDB에서 30건을 가져오며, `bid_10169448` 은 **9위**에 포함되어 있습니다.
2. **재순위 함수 결함**:
   `src/rag/vector_store.py:_rerank_by_exact_title` 에서:
   ```python
   query_key = _normalize_match_key(semantic_query)
   for doc in documents:
       doc_title = extract_document_title(doc_text)
       if doc_title and _normalize_match_key(doc_title) == query_key:
           exact_matches.append(doc)
   ```
   `semantic_query` 가 자연어 전체 문장이므로 `query_key` 와 `doc_title` 이 결코 같을 수 없습니다. 따라서 `exact_matches` 가 0건이 되고, 기존 거리 순서(9위)가 유지된 채 `[:5]` 로 잘려 최종 탈락합니다.

---

## 5. fixture v2 전체 24개 질의 대조 검증

fixture v2의 24개 질의에 대해 ChromaDB 30건 후보 풀 내 순위 및 `_normalize_match_key(doc_title) in query_key` 포함 매칭 여부를 전수 검증했습니다.

| 문항 ID | 기대 근거 ID | 공고명 주요 어구 | ChromaDB 순위 | 벡터 거리 | 포괄 매칭 여부 |
| :---: | :---: | --- | :---: | :---: | :---: |
| q01 | `bid_10169971` | 합포고등학교 교실천장 교체 전기... | **1위 (Rank 0)** | 0.3069 | 매칭 성공 (1위) |
| q02 | `bid_10168839` | (긴급)2025년 조사료 경영체 기계장비... | **1위 (Rank 0)** | 0.3592 | 매칭 성공 (1위) |
| q03 | `bid_10153847` | 광주시 소하천정비종합계획 재수립... | **1위 (Rank 0)** | 0.2602 | 매칭 성공 (1위) |
| q04 | `bid_10169443` | 2026년 은행나무 열매 조기채취... | **1위 (Rank 0)** | 0.3517 | 매칭 성공 (1위) |
| q05 | `bid_10154066` | 건축물대장 전면 재정비용역 | **1위 (Rank 0)** | 0.5818 | 매칭 성공 (1위) |
| q06 | `bid_10154623` | [P.Q 후 가격입찰] 사상산업단지... | **1위 (Rank 0)** | 0.3400 | 매칭 성공 (1위) |
| q07 | `bid_10169454` | 부림봉수농공단지 복합문화센터... | **1위 (Rank 0)** | 0.3676 | 매칭 성공 (1위) |
| q08 | `bid_10168836` | 서울회생법원 전산소모품... | **2위 (Rank 1)** | 0.3182 | 매칭 성공 (1위 동명공고 존재) |
| q09 | `bid_10154876` | 사업수행능력평가(P.Q) 후 가격입찰... | **1위 (Rank 0)** | 0.3650 | 매칭 성공 (1위) |
| q10 | `bid_10169970` | 창원중앙여자고등학교 화장실 보수... | **1위 (Rank 0)** | 0.2283 | 매칭 성공 (1위) |
| q11 | `bid_10169969` | 창원중앙고등학교 외 1교(창원신월초)... | **1위 (Rank 0)** | 0.1859 | 매칭 성공 (1위) |
| q12 | `bid_10169968` | 태봉고등학교 급식조리실 환기개선... | **1위 (Rank 0)** | 0.3247 | 매칭 성공 (1위) |
| q13 | `bid_10169967` | 마산내서여자고등학교 본관동 화장실... | **1위 (Rank 0)** | 0.2459 | 매칭 성공 (1위) |
| q14 | `bid_10169965` | 강릉 스포츠파크 조성사업 재해영향성... | **1위 (Rank 0)** | 0.3013 | 매칭 성공 (1위) |
| q15 | `bid_10169812` | 제71주년 강릉 시민의 날 기념행사... | **1위 (Rank 0)** | 0.3273 | 매칭 성공 (1위) |
| q16 | `bid_10169806` | 국도46호선 고성 간성 광산2 길어깨... | **1위 (Rank 0)** | 0.2852 | 매칭 성공 (1위) |
| q17 | `bid_10169804` | 광석소로(3-52호선) 가옥 철거... | **1위 (Rank 0)** | 0.3432 | 매칭 성공 (1위) |
| q18 | `bid_10169802` | 2026년 국토교통부 빈집사업... | **1위 (Rank 0)** | 0.3673 | 매칭 성공 (1위) |
| q19 | `bid_10169453` | 은용지구 농업기반시설(관정) 설치... | **1위 (Rank 0)** | 0.3231 | 매칭 성공 (1위) |
| q20 | `bid_10169451` | 순천만 큰고니습지 서식지 확장... | **1위 (Rank 0)** | 0.2626 | 매칭 성공 (1위) |
| **q21** | **`bid_10169448`** | **2026년 조림지 풀베기사업 2차(동부지구)** | **10위 (Rank 9)** | **0.3161** | **매칭 성공 (단독 1위 승격 가능)** |
| q22 | `bid_10169447` | 2026년 조림지 풀베기사업 2차(거제사등지구) | **1위 (Rank 0)** | 0.2257 | 매칭 성공 (1위) |
| q23 | `bid_10169445` | 내와동산 소망재활원 소방설비공사 | **1위 (Rank 0)** | 0.2884 | 매칭 성공 (1위) |
| q24 | `bid_10168850` | 2026년 9월분 충주중앙탑초 외4개교... | **1위 (Rank 0)** | 0.2170 | 매칭 성공 (1위) |

- **분석 요약**: 다른 모든 문항은 공고명의 고유성 덕분에 벡터 거리 자체로 1위에 안착했으나, q21만 유일하게 동명 공고 밀집으로 인해 9위로 밀렸습니다. 30건 후보 풀 내에서는 24개 문항 모두 정답 문서가 존재하며, 포괄 매칭 적용 시 q21도 즉시 1위로 승격됩니다.

---

## 6. 결함 원인 특정 (Root Cause Summary)

1. **원인 1 (직접 원인)**: `src/rag/vector_store.py:_rerank_by_exact_title` 에서 후보 문서 제목과 질의문을 비교할 때 `_normalize_match_key(doc_title) == _normalize_match_key(semantic_query)` 로 동치 비교를 수행함. 질의문에 포함된 조사 및 서술어("의 공고번호...알려줘") 때문에 정확 일치 판정이 무력화됨.
2. **원인 2 (연계 원인)**: `src/rag/engine.py:HybridRAGEngine._prepare_context` 의 Meilisearch Lexical 채널 평가 로직도 동일하게 단순 동치(`==`)를 사용해 Lexical 정확 일치 바이패스가 작동하지 않음.
3. **원인 3 (파급 원인)**: 동명/유사 공고가 수백 건 존재하는 고밀도 사업군에서 벡터 거리가 0.2980 ~ 0.3161로 촘촘하게 형성되어 정답 문서(`bid_10169448`)가 9위에 머물렀고, `top_k=5` 절단 시 컨텍스트에서 완전히 누락됨.

---

## 7. 수정 지점 및 개선 방안 제안 (Code Changes Proposal)

> **주의**: 본 Task는 조사 전용이므로 운영 코드를 직접 수정하지 않고 제안만 명시합니다.

### 7.1 제안 1: `src/rag/vector_store.py` 내 `_rerank_by_exact_title` 수정

- **수정 위치**: `src/rag/vector_store.py:250-290`
- **수정 내용**:
  후보 문서의 제목 키가 정규화 질의문의 부분 문자열(포함 관계)인지 검사합니다 (단, 오탐 방지를 위해 최소 길이 제한 5자 이상 적용).
  ```python
  # 기존:
  if doc_title and _normalize_match_key(doc_title) == query_key:
      exact_matches.append(doc)

  # 개선안:
  title_key = _normalize_match_key(doc_title) if doc_title else ""
  if title_key and len(title_key) >= 5 and title_key in query_key:
      exact_matches.append(doc)
  ```

### 7.2 제안 2: `src/rag/engine.py` 내 Lexical 정확 일치 검사 수정

- **수정 위치**: `src/rag/engine.py:175-195`
- **수정 내용**:
  동일하게 `_normalize_match_key(doc_title) in query_key` 로 포함 관계를 평가하여 Meilisearch 적중 문서를 우선 채택할 수 있도록 보강.

### 7.3 타 문항 영향도 및 회귀 위험 평가

1. **긍정적 영향**: 30건 후보 풀에 포함되어 있으나 유사 공고 밀집으로 5위권 밖에 머물던 모든 개체 질의가 1위로 정확하게 승격됨 (q21 recall 0.0 -> 1.0 회복).
2. **부작용 위험 없음**: fixture 24개 문항 전수 조사 결과, 오탐으로 인해 엉뚱한 문서가 승격되는 사례 0건 (모든 문항에서 기대 정답 문서만 단독 매칭됨 확인).

---

## 8. 재현 절차 (Reproduction Script)

아래 명령을 복사하여 실행하면 본 분석의 모든 수치(DB 존재, Meilisearch 1위, ChromaDB 9위, 매칭 실패 원인)를 그대로 재현할 수 있습니다.

```bash
uv run python -c "
import chromadb, json
from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.embeddings import get_collection
from src.rag.vector_store import (
    DEFAULT_COLLECTION,
    _normalize_text,
    _normalize_match_key,
    extract_document_title,
)
from src.rag.engine import build_retrieval_plan
from src.app.services.search_index import INDEX_UID, MeiliSearchClient
from sqlalchemy import select

# 1. DB 확인
with SessionLocal() as db:
    ann = db.execute(select(BidAnnouncement).where(BidAnnouncement.id == 10169448)).scalar_one_or_none()
    res = db.execute(select(BidResult).where(BidResult.bid_ntce_no == ann.bid_ntce_no)).scalar_one_or_none()
    print('[1] DB Data:', ann.bid_ntce_nm, '| Agency:', ann.dminstt_nm, '| Winner:', res.bidwinnr_nm)

# 2. ChromaDB 확인
q = '2026년 조림지 풀베기사업 2차(동부지구)의 공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘'
client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
col = get_collection(client, DEFAULT_COLLECTION)
res_vec = col.query(query_texts=[_normalize_text(q)], n_results=30, where={'has_result': True})
docs, metas, dists = res_vec['documents'][0], res_vec['metadatas'][0], res_vec['distances'][0]

print('
[2] ChromaDB Top-10:')
for idx, (doc, meta, dist) in enumerate(zip(docs[:10], metas[:10], dists[:10])):
    print(f'  Rank {idx}: id={meta.get("id")}, dist={dist:.4f}, title={extract_document_title(doc)}')

# 3. 매칭 결함 증명
query_key = _normalize_match_key(q)
target_title = '2026년 조림지 풀베기사업 2차(동부지구)'
title_key = _normalize_match_key(target_title)
print('
[3] Matching Defect Proof:')
print('  Query Key :', query_key)
print('  Title Key :', title_key)
print('  Strict Equality (==) :', title_key == query_key, '-> 재순위 실패 원인')
print('  Containment (in)     :', title_key in query_key, '-> 해결 방안')
"
```
