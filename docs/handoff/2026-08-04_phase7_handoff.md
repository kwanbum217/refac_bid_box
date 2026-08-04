# Phase 7 인수인계서

> **작성일**: 2026-08-04
> **작성 세션**: Claude (재현율 + Phase 7 담당)
> **상태**: Phase 7 부분 완료, 컷오버 보류
> **다음 담당자**: 이 문서만 읽고 이어받을 수 있도록 작성했습니다

---

## 0. 먼저 알아야 할 것

**이 저장소에는 다른 Claude 세션이 동시에 작업 중입니다.** 모델 학습
(용역 예측 모델 하이퍼파라미터 탐색, 참가자 수 특징 조사)을 담당합니다.

| 절대 하지 말 것 | 이유 |
| --- | --- |
| `git add -A` / `git add .` | 다른 세션의 미완성 파일이 딸려 들어갑니다 |
| `src/ml/*`, `src/app/api/v1/predictions.py` 수정 | 학습 세션 영역입니다 |
| `data/model_files/*` 수정 | 승격 산출물입니다 |
| `scripts/tune_servc_*`, `scripts/*_servc_*` 수정 | 학습 세션 작업 중 |
| 컨테이너 임의 종료 | 학습이 DB 를 쓰고 있을 수 있습니다 |

미추적 파일이 보여도 커밋하지 말고 그대로 두십시오. 필요한 파일만
경로를 명시해 `git add` 하십시오.

Redis 를 내려야 한다면 `SHUTDOWN NOSAVE` 를 쓰십시오.

---

## 1. 지금까지 끝난 것

### 1.1 원본 테스트 재현 (완료)

원본 `bid_box` 테스트 이름 기준 **93.1% (122/131)**. 남은 9건은 이식본에
대응 개념이 없는 구조적 제외 대상입니다.

근거: [`docs/design/original_test_parity_20260804.md`](../design/original_test_parity_20260804.md)

**이 항목은 더 할 일이 없습니다.** 남은 9건을 이름만 맞춰 채우면 아무것도
검증하지 않는 테스트가 남습니다.

### 1.2 Phase 7 검증 (부분 완료)

| 목표 | 결과 |
| --- | --- |
| G1 데이터 무손실 | 통과 (원본 ChromaDB 스냅샷 분리 보존 후 재검증) |
| G3 예측 API P95 100ms | 통과 (1.4ms) |
| G3 SSE 전체 P95 20초 | 통과 (13.19s) |
| G3 SSE 첫 토큰 P95 3초 | **미달 (11.06s)** |
| G2 Windows 검증 | **미수행** |

전체 보고서: [`docs/ops/phase7_cutover_report_20260804.md`](../ops/phase7_cutover_report_20260804.md)

### 1.3 발견해서 고친 결함 3건

| 결함 | 커밋 |
| --- | --- |
| 낙찰결과 상세 낙찰률 자리에 bound method 출력 | `10e0e9f` |
| 연월 기간 표현이 무시되어 전 기간 집계 (침묵하는 오답) | `6251975` |
| 통계 집계 340만 행 풀스캔 | `6251975` |

---

## 2. 다음 담당자가 할 일 (우선순위 순)

### 우선순위 1 — 담당자 결정이 필요한 것

SSE 목표와 운영 추론 환경은 비용·품질 결정이 필요합니다. ChromaDB 기준선은
후속 검토에서 원본을 직접 대조해 해소했습니다.

#### 2.1 ChromaDB 기준선 정정 (해소)

원본 `bid_box/chroma_db`도 활성 컬렉션은 `bidding_kb` **1개**였습니다.
19개는 삭제된 컬렉션의 UUID 디렉토리를 잘못 센 값입니다. 원본은 임베딩
10건이고 운영 데이터는 재구축된 500건입니다.

```bash
.venv/bin/python scripts/verify_migration.py
```

원본 10건은 `data/backups/chroma_source/`에 별도 보존하며 manifest의 모든
SHA256과 논리 기준선(1개 컬렉션 / 10건)을 검증합니다. 운영 `chroma_db/`는
KB 갱신으로 확장할 수 있지만 `bidding_kb` 컬렉션이 비어 있으면 실패합니다.

#### 2.2 SSE 첫 토큰 목표

현재 P95 11.06s, 목표 3s. **애플리케이션 최적화로는 도달 불가**입니다.

측정 근거 (질의별 검색/LLM 분리):

| 질의 | 검색 | LLM 첫 토큰까지 |
| --- | --- | --- |
| 적격심사 기준이 어떻게 되나요 | 51ms | 6,924ms |
| 2025년 물품 낙찰 평균 낙찰률 | 1,996ms | 6,235ms |
| 공사 부문 최근 낙찰 동향 | 51ms | 7,797ms |
| 수요기관별 낙찰 금액 상위 | 62ms | 10,101ms |
| 용역 계약 방법 | 65ms | 7,279ms |

5건 중 4건은 검색이 50~65ms 입니다. 검색을 0으로 만들어도 첫 토큰은
6.2초 아래로 안 내려갑니다. **DB 최적화를 더 하지 마십시오. 의미가 없습니다.**

선택지 (담당자 결정):

| 방안 | 효과 | 비용 |
| --- | --- | --- |
| 목표 재설정 (첫 토큰 P95 12초) | 현 상태 충족 | 체감 개선 없음 |
| 더 작은 로컬 모델 | 프리필 단축 | 답변 품질 저하 |
| GPU 추론 환경 | 대폭 단축 | 인프라 비용 |
| 클라우드 LLM 복귀 | 1~3초 | 비용, 외부 의존 |

참고: 3초 목표는 Gemini 기준이었다가 Ollama 전환 때 재설정된 값입니다
(`REFACTORING_DESIGN.md` Phase 7 주석, 2026-08-01). LLM 백엔드는
기본 Ollama `gemma4:e4b`, **임베딩 모델은 교체 금지**입니다.

#### 2.3 Windows 검증 (G2)

macOS 는 전부 통과했습니다. Windows 환경이 없어 미검증입니다.
절차는 [`docs/ops/cross_platform_guide.md`](../ops/cross_platform_guide.md).

Windows 머신에서 `make dev` 와 `make test` 가 macOS 와 동일하게
동작하는지만 확인하면 됩니다.

### 우선순위 2 — 후속 검증에서 완료된 것

#### 2.4 재학습·승격·롤백 경로 검증 (완료)

용역 모델 917,629행 학습, Champion 승격, 운영 경로 비교, 백업 롤백까지
실행됐습니다. 이후 하이퍼파라미터 후보 `num_leaves=255`는 운영 구간 폭이
11.2% 넓어져 기각하고 현행 63으로 되돌렸습니다.

일반 전 주기 계약은 `tests/test_retrain_pipeline_e2e.py`,
`tests/test_mlops_pipeline.py`, `tests/test_serving_feature_parity.py`로 다시
검증합니다. 상세 근거는 `docs/handoff/2026-08-04_servc_serving_handoff.md`입니다.

#### 2.5 등각예측 구간 서빙 경로 연결 (완료)

API 응답과 상세 화면에 90% 등각예측 구간이 연결됐습니다. API 경로 200건
실측 피복률은 93.00%이고, 구형 모델은 구간 필드를 `None`으로 반환해 점 추정
호환성을 유지합니다.

---

## 3. 환경 재현 절차

### 3.1 `uv` 환경 정합성

기존 `.venv`는 scikit-learn 1.6.1이라 1.8.0에서 직렬화한 모델 3종과
호환되지 않습니다. `uv.lock`을 기준으로 환경을 동기화해야 합니다. `uv`가
설치되지 않은 머신에서는 먼저 공식 설치 절차로 설치하십시오.

```bash
uv sync --all-groups
uv run python scripts/verify_model_compatibility.py
uv run pytest tests/ -q
```

macOS 에 GNU `timeout` 도 없습니다.

### 3.2 스택 기동

```bash
open -a Docker                       # 데몬이 내려가 있으면
docker compose up -d db redis
docker compose ps                    # db healthy 확인
.venv/bin/python -m alembic current  # 적용 상태만 읽기 전용 확인
.venv/bin/python scripts/check_schema_drift.py
```

기존 Django 운영 DB에는 `alembic upgrade head`를 실행하지 마십시오. 신규 빈
DB만 `make migrate-up`을 사용하며 기존 DB는 이미 stamp된 상태를 확인합니다.

### 3.3 검증 실행

```bash
uv run python scripts/verify_migration.py
uv run python scripts/verify_model_compatibility.py
uv run pytest tests/ -q
uv run python scripts/validate_agent_rules.py
```

2026-08-04 macOS 격리 작업 트리 기준 결과는 `631 passed / 2 skipped`,
에이전트 규칙 `6/6`입니다.

### 3.4 벤치마크 (서버 기동 필요)

```bash
uv run uvicorn src.app.main:app --port 8000 &
uv run python scripts/benchmark_latency.py \
  --base-url http://127.0.0.1:8000 \
  --output data/benchmarks/phase7_latency.json
```

TestClient 로는 재지 마십시오. 인프로세스 호출이라 네트워크와 이벤트 루프
경합을 건너뛰어 체감치가 나오지 않습니다.

---

## 4. 이 저장소의 규칙 (위반 시 되돌려야 함)

| 규칙 | 내용 |
| --- | --- |
| 브랜치 | `main` 에서 직접 커밋 금지. 항상 작업 브랜치 |
| 병합 | `git merge --no-ff`. **Pull Request 만들지 말 것** (1인 작업) |
| 병합 전 | 전량 테스트 통과 + `validate_agent_rules.py` 통과 |
| 이모지 | 코드 주석, 커밋 메시지, 문서에 사용 금지 |
| 언어 | 응답과 문서는 한국어 존댓말. 코드/변수명은 영어 |
| 라이브러리 | 신규 추가 전 사전 합의 |
| DB | 기존 테이블/컬럼명·타입 변경 금지 (인덱스 추가는 허용) |
| 특징 | 학습·추론 특징 생성은 `src/ml/features.py` 단일 함수만 |

---

## 5. 작업 요령 (겪어보고 정리한 것)

**성능 주장에는 실측을 붙이십시오.** 이 프로젝트는 추정치로 "개선됨" 이라
쓰는 것을 금합니다. 인덱스를 추가했으면 EXPLAIN 과 전후 밀리초를 남기고,
효과가 없으면 기각하고 그 근거도 남기십시오
(보고서 4.3 이 기각 사례입니다).

**테스트를 추가하면 일부러 깨뜨려 보십시오.** 프로덕션 코드를 되돌렸을 때
그 테스트가 실패하는지 확인해야 실제로 방어하는 테스트입니다. 이번에
낙찰률 수정과 인덱스 모두 이 방식으로 확인했습니다.

**모델 내용에 의존하는 값을 테스트에 박지 마십시오.** 재학습 승격 때마다
깨져서 결국 계약을 못 지키게 됩니다. `tests/test_predictions_api.py` 의
list-models 테스트가 구조만 보는 예입니다.

**병렬 세션 때문에 테스트가 실패하면** 해당 파일만 단독 재실행해서
격리 확인하십시오. 전량 실행 중 다른 세션이 모델 파일을 바꾸면
`KeyError: 'scenario_mode'` 같은 실패가 납니다.

---

## 6. Git 상태 확인과 병렬 세션 격리

Phase 7 연월 파싱·통계 인덱스 수정은 `051ab01`에서 `main`에 병합됐습니다.
고정된 상태를 문서에 복사하지 말고 시작할 때 아래를 실행하십시오.

```bash
git status --short --branch
git log --oneline -5
git worktree list
```

병렬 세션은 같은 디렉토리에서 브랜치를 바꾸지 말고 세션별 `git worktree`를
사용합니다. 작업 브랜치는 전량 테스트 통과 후 `--no-ff`로 `main`에
병합합니다.

---

## 7. 관련 문서

| 문서 | 내용 |
| --- | --- |
| [`docs/ops/phase7_cutover_report_20260804.md`](../ops/phase7_cutover_report_20260804.md) | Phase 7 측정치와 판정 |
| [`docs/design/original_test_parity_20260804.md`](../design/original_test_parity_20260804.md) | 원본 테스트 재현 현황 |
| [`docs/design/prediction_without_amount_20260804.md`](../design/prediction_without_amount_20260804.md) | 금액 미공개 공고 예측 차단 결정 |
| [`docs/design/FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md) | 화면 재현 결정과 의도적 차이 |
| [`AGENTS.md`](../../AGENTS.md) | 규칙 정본 |
