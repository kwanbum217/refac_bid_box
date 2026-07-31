# ML 가중치 및 ChromaDB 보존 검증

> **작성일**: 2026-07-31
> **상태**: 설계 (실행 전)
> **관련**: [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 5.4~5.5장

---

## 1. ML 모델 가중치 검증

### 1.1 보존 대상 (4개 모델)

| 모델 | 경로 (기존) | 크기 | 분야 |
| --- | --- | --- | --- |
| `v25` | `apps/predictions/model_files/v25/` | ~1.1MB | 건설·외자 범용 |
| `quantum_leap_v25_pro` | `apps/predictions/model_files/quantum_leap_v25_pro/` | ~24KB | 물품(Thng) |
| `ssh_hist_premium` | `apps/predictions/model_files/ssh_hist_premium/` | ~4.1MB | 용역(Servc) |
| `v13_hybrid` | `apps/predictions/model_files/v13_hybrid/` | ~36MB | 하이브리드 |

### 1.2 체크섬 기록 (이행 전)

```bash
# 각 모델 디렉토리의 모든 파일에 대해 sha256 기록
find apps/predictions/model_files -type f -exec shasum -a 256 {} \; > ml_weights_checksums_pre.txt
```

### 1.3 검증 절차

```
[1] 파일 체크섬: 복사 후 sha256이 기준선과 100% 일치하는지 확인
[2] 로드 검증:   신규 predictor로 각 모델 로드 → 예외 없이 로드되는지 확인
[3] 회귀 테스트: 샘플 입력(동일 features_dict) → 예측값이 기존과 동일한지 확인
[4] 메타데이터:  metadata.json / champion_summary.json 스펙 호환성 확인
```

### 1.4 레지스트리 등록

기존 4개 모델은 신규 **모델 레지스트리**의 초기 champion으로 등록합니다.

- 가중치 파일을 `ml_registry/{model_name}/{version}/model.bin`으로 복사.
- 메타데이터를 레지스트리 포맷으로 변환 (기존 `metadata.json` 흡수).
- 상태 = `champion`.

---

## 2. ChromaDB 보존 검증

### 2.1 보존 대상

| 자산 | 경로 | 규모 |
| --- | --- | --- |
| ChromaDB | `chroma_db/` | 3.4MB, 19개 컬렉션 |

### 2.2 백업

```bash
cp -R chroma_db/ chroma_db_backup_YYYYMMDD/
```

### 2.3 검증 절차

```
[1] 컬렉션 수: 신규 위치에서 19개 컬렉션 존재 확인
[2] 문서 수:   각 컬렉션의 문서 수가 원본과 동일한지 비교
[3] 쿼리 검증: 샘플 쿼리 10건 → 동일 top-k 결과 반환 확인
```

---

## 3. 기타 데이터 자산

| 자산 | 경로 | 처리 |
| --- | --- | --- |
| parquet 스냅샷 | `data/exports/` (438MB) | 외부 저장소 이동 (Git 제외) |
| 학습 데이터 | `ssh/`, `sde/` (~54MB) | `src/ml/dataset.py`용 참조 데이터로 보존 |
| RAG KB | `rag_kb.csv` (768KB) | 보존 (RAG 시스템용) |

---

## 4. 체크리스트

- [ ] ML 가중치 체크섬 기준선 기록
- [ ] ChromaDB 백업
- [ ] 4개 모델 로드 + 회귀 테스트 통과
- [ ] ChromaDB 19개 컬렉션 문서수/쿼리 검증 통과
- [ ] 레지스트리 초기 champion 등록 완료
