# ML 가중치 및 ChromaDB 보존 검증

> **작성일**: 2026-07-31
> **상태**: Phase 1 검증 보강 완료
> **관련**: [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) 5.4~5.5장

---

## 1. ML 모델 가중치 검증

### 1.1 보존 대상 (4개 모델)

| 모델 | 경로 (refac) | 크기 | 분야 |
| --- | --- | --- | --- |
| `v25` | `data/model_files/v25/` | ~1.1MB | 건설·외자 범용 |
| `quantum_leap_v25_pro` | `data/model_files/quantum_leap_v25_pro/` | ~24KB | 물품(Thng) |
| `ssh_hist_premium` | `data/model_files/ssh_hist_premium/` | ~4.1MB | 용역(Servc) |
| `v13_hybrid` | `data/model_files/v13_hybrid/` | ~36MB | 하이브리드 |

> 가중치 바이너리(`*.bin`, `*.joblib`)는 `.gitignore` 대상입니다. SHA256 manifest는 `data/backups/data_assets_checksums.json`에 기록합니다.

### 1.2 체크섬 기록

```bash
python3 scripts/import_data_assets.py
python3 scripts/verify_migration.py
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

### 1.5 2026-08-06 용역 champion 체크섬

`servc_institution_v1/v_20260806_025423_494`를 `ml_registry/`에 보존하고
운영 서빙 슬롯으로 승격했습니다. 레지스트리와 서빙 슬롯의 SHA256이 모두 아래
값으로 일치합니다.

| 파일 | SHA256 |
| --- | --- |
| `model.bin` | `5e2ec89afaf8e4884343f534406a1ee461e057c56e4eabf9257edfec7c1d6f88` |
| `model_q10.bin` | `fcd237c42acfc718e4f620d5a372cf72a4393272149bb4a116647634b73b161f` |
| `model_q90.bin` | `b89e90b5abe6c1beaab077cf5f8ff8e24d4bda51d32e39e90a334c3218088c6e` |

이 기록은 승격 아티팩트의 복사 무결성 기준입니다. 직전 서빙본
`v_20260805_103528_292`는 `data/model_backups/servc_institution_v1`에 보관했습니다.
기존 4개 이식 모델의 정본 manifest인 `data/backups/data_assets_checksums.json`은
변경하지 않았습니다.

---

## 2. ChromaDB 보존 검증

### 2.1 보존 대상

| 자산 | 경로 | 규모 |
| --- | --- | --- |
| 원본 스냅샷 | `data/backups/chroma_source/` | 3.4MB, `bidding_kb` 1개 / 임베딩 10건 |
| 운영 ChromaDB | `chroma_db/` | `bidding_kb` 1개 / 현재 임베딩 500건 |

### 2.2 백업

원본 `bid_box/chroma_db/`를 `data/backups/chroma_source/`에 복사하고
`data/backups/data_assets_checksums.json`의 SHA256 기준선으로 검증합니다.
운영 `chroma_db/`는 KB 갱신으로 변경될 수 있으므로 원본 스냅샷과 분리합니다.

### 2.3 검증 절차

```
[1] 원본 스냅샷: 모든 파일 SHA256이 manifest와 일치하는지 확인
[2] 논리 기준선: `bidding_kb` 1개 컬렉션 / 임베딩 10건 확인
[3] 운영 데이터: `bidding_kb` 1개 컬렉션과 1건 이상 임베딩 확인
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

- [x] ML 가중치 체크섬 기준선 기록 (`data/backups/data_assets_checksums.json`)
- [x] ChromaDB 원본 스냅샷 보존 (`data/backups/chroma_source/`, Git 제외)
- [ ] 4개 모델 로드 + 회귀 테스트 통과 (`RUN_MODEL_TESTS=1`)
- [x] ChromaDB 원본 체크섬·논리 기준선·운영 구조 검증 (`verify_migration.py`)
- [ ] DB 풀 덤프/복원 및 행 수 대조
