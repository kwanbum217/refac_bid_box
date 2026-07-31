# refac_bid_box 스킬 시스템 & 리팩토링 인수인계서 (정정본)

> **작성일**: 2026-07-31
> **정정일**: 2026-07-31
> **버전**: v1.1.0
> **상태**: Phase 0 완료 / Phase 1~3 진행 중 (Antigravity 스캐폴드 정정 후)

---

## 1. 개요

본 문서는 `refac_bid_box` 저장소의 **실제 진행 상태**를 기록합니다.
이전 v1.0.0 문서의 "Phase 0~7 완수" 주장은 **Antigravity 워크스페이스 격리로 인한
스텁(scaffold) 착오**였으며, 본 정정본이 현재 기준선입니다.

---

## 2. 현재 달성 상태

| 목표 | 상태 | 비고 |
| --- | --- | --- |
| G1 데이터 무손실 | **진행 중** | ML 4종 + ChromaDB 이전 완료, DB 덤프 대기 |
| G2 크로스 플랫폼 | **부분** | Docker/Makefile 골격 완료 |
| G3 스택 최적화 | **미검증** | 실측 P95 벤치마크 미수행 (스텁 측정 무효) |

---

## 3. 완료된 작업

1. **Phase 0**: uv, Docker, Makefile, 5-CLI 스킬 시스템, pre-commit
2. **Phase 1 (부분)**: `data/model_files/` 4종, `chroma_db/` 복사, SHA256 manifest
3. **Phase 2~3 (부분)**: FastAPI ORM 8모델, API 라우터, `model_registry.py` 이식

---

## 4. 진행 중 / 미착수

| 항목 | 상태 |
| --- | --- |
| `predictor.py` (789줄) | `src/ml/model_registry.py` 이식 완료, 통합 테스트 필요 |
| `rag_engine.py` (945줄) | `src/rag/engine.py` 핵심 이식, Gemini 연동 |
| `planner.py` (806줄) | `src/app/services/planner.py` 규칙 기반 핵심 이식 |
| G2B 수집 (`api_collector.py`) | 미이식 |
| DB 풀 덤프/복원 | 미수행 (MySQL 연결 필요) |
| Phase 4~7 E2E/벤치마크 | 미착수 |

---

## 5. 검증 명령

```bash
python3 scripts/import_data_assets.py   # 최초 1회
python3 scripts/verify_migration.py
SKIP_MODEL_LOAD=true pytest tests/ -q  # CI 경량
pytest tests/ -q                        # 전체 (모델 로드 포함)
```

---

## 6. 프론트엔드 방향

설계서 3.7절에 따라 **SSR + HTMX**를 1차 목표로, React SPA(`frontend/`)는
레거시 스캐폴드로 보존하되 신규 UI는 `src/app/templates/`에서 진행합니다.
상세: [`docs/design/FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md)
