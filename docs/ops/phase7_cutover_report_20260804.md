# Phase 7 검증 보고서

> **작성일**: 2026-08-04
> **갱신일**: 2026-08-11
> **버전**: v1.4
> **상태**: HISTORICAL (과거 측정 기록. 2026-08-14 latency_gate_protocol 제정 이전 결과로 현행 G3 판정 근거 사용 금지. 현재 정본은 [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 참조)
> **판정**: **컷오버 보류**

> [!WARNING]
> **HISTORICAL / 과거 측정 보고서 안내**
> 본 문서는 **2026-08-14 `docs/ops/latency_gate_protocol.md` 제정 이전**에 측정된 과거 Phase 7 검증 결과입니다.
> 규약 제정 이전의 표본 수(예측 100회 등)와 측정 방식은 현행 G3 판정 근거로 사용할 수 없으며, 당시의 이력 증거로만 보존됩니다.
> 현재 유효한 레이턴시 판정 규약 및 프로젝트 운영 상태는 [`docs/ops/latency_gate_protocol.md`](latency_gate_protocol.md) 및 [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)를 참조하십시오.

---

## 1. 요약

| 목표 | 항목 | 결과 |
| --- | --- | --- |
| G1 | 데이터 무손실 | **통과** |
| G3 | 낙찰가 예측 API P95 100ms | **통과** (기동 직후 19.1ms) |
| G3 | SSE 전체 응답 P95 20초 | **통과** (6.39초) |
| G3 | SSE 첫 토큰 P95 3초 | **통과** (2.66초) |
| G2 | macOS/Windows 동일 구동 | **부분 검증** (macOS 실기·Windows CI 통과, Windows Docker 실기 대기) |

G1과 G3는 목표를 충족했습니다. G2는 macOS 실기와 Windows Python CI까지
확인했으나 Windows Docker Desktop 전체 스택을 실행하지 못했으므로 컷오버를
선언하지 않습니다.

검증 과정에서 **침묵하는 오답 1건**을 발견해 수정했습니다. 레이턴시보다 우선순위가
높은 정확성 결함이었습니다(SKILLS.md 품질 기준 1순위).

---

## 2. 측정 환경

| 항목 | 값 |
| --- | --- |
| 서버 | uvicorn, 로컬 단일 프로세스, `http://127.0.0.1:8000` |
| DB | MySQL 8 (Docker), `bid_announcements` 5,461,079행 / `bid_results` 3,405,928행 |
| LLM | Ollama `gemma4:e4b` (로컬 추론) |
| 표본 | SSE 20회, 단발 질의 10회, 예측 100회 |

벤치마크는 TestClient 가 아니라 기동 중인 서버에 HTTP 로 붙어 측정합니다.
인프로세스 호출은 네트워크와 이벤트 루프 경합을 건너뛰어 체감치를 재지 못합니다.
이 장의 표본 수는 2026-08-04 최초 측정 조건입니다. 이후 스크립트는 캐시를 피하는
고유 질의, 예측 10개 동시 요청, 오류 포함 판정, 원시 표본 JSON 저장을 추가해
강화했습니다. 2026-08-06에는 병렬 학습이 없는 병합 상태에서 SSE 10회와 기동
직후 예측 100회를 다시 측정했고, 그 결과를 5장의 최종 기준선으로 반영했습니다.

---

## 3. G1 데이터 무손실 — 통과

```
PASS: ML 가중치 4종 manifest 체크섬 일치
PASS: ChromaDB 원본 10건 보존 / 운영 500건 확인
PASS: DB 테이블 ORM 정합성 확인 (31개 테이블)
PASS: 공고 5,461,079행 / 낙찰 3,405,928행 확인
PASS: 등록 모델 5종 scikit-learn 1.8.0 직렬화·서빙 특징 호환성 확인
```

### ChromaDB 기준선 정정과 보존 방식

원본 `bid_box/chroma_db`를 직접 조회한 결과 활성 컬렉션은 `bidding_kb`
1개, 임베딩은 10건입니다. 과거 문서의 19개는 삭제된 컬렉션의 UUID
디렉토리를 실제 컬렉션으로 잘못 센 값입니다.

원본은 `data/backups/chroma_source/`에 별도 보존했습니다. 검증 스크립트는
manifest에 기록된 모든 원본 파일의 SHA256, `bidding_kb` 1개, 임베딩 10건을
확인합니다. 운영 `chroma_db/`의 500건은 KB 재구축 결과이며 원본 스냅샷과
분리해 검증합니다. 검증 런타임은 원본 저장소 형식과 호환되는 ChromaDB 0.6.3으로
고정합니다.

2026-08-05 격리 작업 트리에서 Python 3.12, ChromaDB 0.6.3,
scikit-learn 1.8.0으로 재검증했습니다. G1 검증, 모델 호환성 5/5, 전량 테스트
`632 passed / 2 skipped`, 규칙 정합성 `6/6`이 통과했습니다.

---

## 4. 발견한 결함과 수정

### 4.1 연·월 표현이 무시되어 전 기간을 집계 (정확성)

**증상**: "2025년 물품 낙찰 평균 낙찰률" 질의가 기간 조건 없이 전 기간을
집계하고도 2025년을 답한 것처럼 응답했습니다.

**원인**: `_parse_time_window` 가 완전한 날짜 쌍(`2026년 4월 19일부터
2026년 4월 25일까지`)과 상대 표현(`최근 3개월`)만 처리하고, 일자 없는
연·월 표현을 전부 흘려보냈습니다.

| 표현 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `2025년` | 기간 조건 없음 | 2025-01-01 ~ 2025-12-31 |
| `2025년 3월` | 기간 조건 없음 | 2025-03-01 ~ 2025-03-31 |
| `2025년 1월부터 3월까지` | 기간 조건 없음 | 2025-01-01 ~ 2025-03-31 |
| `2024년 11월부터 2025년 2월까지` | 기간 조건 없음 | 2024-11-01 ~ 2025-02-28 |

오류를 내지 않고 그럴듯한 숫자를 돌려주므로 사용자가 알아챌 수 없습니다.
느린 것보다 나쁜 결함입니다.

**수정**: `src/rag/engine.py` 에 `_parse_year_month_window` 추가. 완전한
날짜 쌍 규칙보다 뒤에 두어 기존 동작을 보존합니다. 회귀 테스트 8건 추가
(`tests/test_chatbot_core.py`) — 윤년 말일과 해를 넘기는 구간 포함.

### 4.2 통계 집계가 340만 행 풀스캔 (성능)

**원인**: `bid_results` 의 `category` 단일 인덱스만으로는 집계 컬럼
(`sucsf_bid_rate`, `sucsf_bid_amt`)을 읽으려 테이블로 되돌아가야 해
옵티마이저가 풀스캔(`type=ALL`, 3,390,117행)을 택했습니다.

**수정**: 커버링 인덱스 `ix_bid_results_cat_dt_stats (category,
rl_openg_dt, sucsf_bid_rate, sucsf_bid_amt)` 추가. 마이그레이션
`a1c4e7b90d21` 로 재현 가능합니다.

| 질의 | 이전 | 이후 | 배수 |
| --- | --- | --- | --- |
| category 단독 집계 | 5,347ms | 236ms | 22.7배 |
| category + 1년 기간 집계 | 4,825ms | 23ms | 208배 |

실행 계획이 `type=ALL` 에서 `Using index` 로 바뀌어 테이블을 읽지 않습니다.

### 4.3 기각한 최적화

`bid_announcements` 에 같은 형태의 커버링 인덱스
`(category, bid_ntce_dt, bid_ntce_nm)` 를 시험했습니다.

| 항목 | 값 |
| --- | --- |
| `retrieve_structured_data` 개선 | 1,706ms → 1,448ms (15%) |
| 인덱스 생성 시간 | 31.9초 |

**기각합니다.** 546만 행 테이블에 매일 수집 INSERT 가 들어가는데 쓰기
비용 대비 이득이 작습니다. 남은 병목은 `bid_ntce_nm` GROUP BY 인데
카디널리티가 높고 `NOT LIKE` 필터가 걸려 인덱스로 해결되지 않습니다.

---

## 5. G3 레이턴시 — 통과

### 5.1 최종 측정치

| 구간 | P50 | P95 | 목표 | 판정 |
| --- | ---: | ---: | ---: | --- |
| SSE 첫 토큰 | 1.12초 | **2.66초** | 3초 | 통과 |
| SSE 전체 응답 | 기록하지 않음 | **6.39초** | 20초 | 통과 |
| 낙찰가 예측 API (기동 직후) | 기록하지 않음 | **19.1ms** | 100ms | 통과 |

2026-08-04 최초 측정과 2026-08-06 최종 측정의 비교입니다.

| 구간 | 최초 P95 | 최종 P95 |
| --- | --- | --- |
| SSE 첫 토큰 | 11.06초 | **2.66초** |
| SSE 전체 응답 | 13.19초 | **6.39초** |
| 낙찰가 예측 API | 예열 상태 1.4ms | **기동 직후 19.1ms** |

예측 API는 예열된 1.4ms 수치 대신 더 보수적인 기동 직후 수치를 기준선으로
채택했습니다. 이 조건에서도 목표 100ms 안입니다.

### 5.2 최초 원인 해석의 정정

최초 보고서는 검색이 50~65ms인 질의에서도 첫 토큰이 6초 이상 걸리는 현상을
로컬 LLM 프리필 한계로 해석했습니다. 측정값은 맞았지만 원인 분해가 부족했습니다.
Ollama 응답 메타데이터와 스트리밍 청크를 다시 분석한 결과, 실제 운영 프롬프트의
프리필은 0.1초 미만이었고 지연의 주원인은 다음 세 가지였습니다.

| 원인 | 대책 | 결과 |
| --- | --- | --- |
| `gemma4` 사고 단계가 본문 토큰보다 먼저 생성됨 | `LLM_THINKING=false` | 계층 단독 첫 토큰 평균 10.53초에서 0.38초로 감소 |
| Ollama 기본 5분 후 모델 언로드 | `OLLAMA_KEEP_ALIVE=-1`, 기동 예열 | 콜드 스타트 약 11.78초 제거 |
| 날짜 필터 상위 N 실시간 쿼리 반복 | 조건별 TTL 캐시 | 정형 조회 반복 1,967ms에서 5ms로 감소 |

로컬 LLM과 기존 하드웨어를 유지한 상태에서 첫 토큰 P95 2.66초를 달성했습니다.
따라서 목표 재설정이나 하드웨어 변경은 필요하지 않습니다. 상세 측정과 회귀 방지
계약은 `docs/design/sse_first_token_20260805.md`에 기록했습니다.

### 5.3 남은 성능 위험

`LLM_THINKING=false`는 복잡한 추론 질의의 품질을 낮출 수 있습니다. 품질 회귀로
이를 다시 켜면 첫 토큰이 약 10초로 돌아갑니다. 또한 날짜 창이 있는 콜드 첫
질의는 약 2초의 실시간 집계 비용이 남아 있으므로, 장비 부하와 캐시 상태를 함께
기록하며 사후 모니터링해야 합니다.

---

## 6. G2 크로스 플랫폼 — 부분 검증

macOS에서 Docker Compose 기동, 마이그레이션, 전량 테스트가 통과했습니다.
GitHub Actions의 macOS·Windows·lint 3개 작업도 2026-08-06 전량 통과했습니다.
다만 GitHub 호스팅 Windows 러너는 Linux 컨테이너 기반 전체 Compose 스택을
대신하지 못합니다.

Windows용 `scripts/validate_windows.ps1`은 의존성·테스트·Compose 빌드와 기동,
healthy 대기, Alembic, 스키마 드리프트, FastAPI `status=healthy` 응답을 한 번에
검증하도록 보강했습니다. 2026-08-11 macOS에서는 Docker Desktop 번들 CLI로
Compose 정적 구성을 검증했지만 PowerShell과 Windows 호스트가 없어 변경된
스크립트를 실기 실행하지 못했습니다. 실제 Windows Docker Desktop 실행은 남아
있으며 절차는 `docs/ops/cross_platform_guide.md`를 따릅니다.

---

## 7. 컷오버 판정

**보류합니다.** 남은 조건입니다.

| 항목 | 필요한 조치 | 주체 |
| --- | --- | --- |
| Windows 검증 | Windows Docker Desktop에서 `scripts/validate_windows.ps1` 전체 통과 | 담당자 |

ChromaDB 기준선과 G3 성능 목표는 해소했습니다. 남은 컷오버 차단 조건은 Windows
호스트 Docker Compose 전체 스택 실기 검증입니다.

---

## 8. 재현 절차

```bash
cp .env.example .env
# .env의 SECRET_KEY와 MEILI_MASTER_KEY를 개발용 무작위 값으로 교체
docker compose up -d db redis
uv sync --all-groups
uv run python scripts/verify_migration.py
uv run python scripts/verify_model_compatibility.py
uv run alembic current
uv run python scripts/check_schema_drift.py
uv run uvicorn src.app.main:app --port 8000
uv run python scripts/benchmark_latency.py \
  --base-url http://127.0.0.1:8000 \
  --output data/benchmarks/phase7_latency.json
```

기존 Django 운영 DB에는 `alembic upgrade head`를 실행하지 않습니다.
Windows 전체 스택은 PowerShell에서 다음 명령으로 검증합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_windows.ps1
```

---

## 9. 관련 문서

- [`docs/design/REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) — Phase 7 정의와 P95 목표 근거
- [`docs/design/sse_first_token_20260805.md`](../design/sse_first_token_20260805.md) — 최초 원인 해석 정정과 최종 G3 측정
- [`docs/design/original_test_parity_20260804.md`](../design/original_test_parity_20260804.md) — 원본 테스트 재현 현황
- [`docs/ops/cross_platform_guide.md`](cross_platform_guide.md) — Windows 검증 절차
