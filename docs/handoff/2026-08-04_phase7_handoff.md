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
| G1 데이터 무손실 | 통과 (단, 아래 4.1 확인 필요) |
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

### 우선순위 1 — 담당자 결정이 필요한 것 (에이전트가 진행 불가)

아래 셋은 **실행이 아니라 결정**이 필요해 진행하지 않았습니다. 결정을
받아오는 것이 먼저입니다.

#### 2.1 ChromaDB 컬렉션 수 불일치

`AGENTS.md` 와 `SKILLS.md` 는 **19개 컬렉션**이라 하는데 실측은
**1개 컬렉션 / 임베딩 500건**입니다.

```bash
python scripts/verify_migration.py   # 실측 확인
```

원본 DB 유실과 parquet 복구 이력이 있어 그때 축소된 것인지, 문서가 초기
계획값을 그대로 둔 것인지 불명입니다. **G1 은 협상 대상이 아니므로 이것이
정리되기 전에는 컷오버 근거로 쓸 수 없습니다.**

- 데이터가 정본이면 → `AGENTS.md`, `SKILLS.md` 문구 정정
- 문서가 정본이면 → 유실 조사 및 복구

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
절차는 [`docs/ops/cross_platform_guide.md`](cross_platform_guide.md).

Windows 머신에서 `make dev` 와 `make test` 가 macOS 와 동일하게
동작하는지만 확인하면 됩니다.

### 우선순위 2 — 에이전트가 진행 가능한 것

#### 2.4 재학습 전 주기 검증

Phase 7 항목 중 유일하게 미수행이고 결정이 필요 없는 것입니다.
DB 집계 → 데이터셋 구성 → 학습 → 평가 → Champion 승격 → 핫스왑까지
한 바퀴 돌려 확인합니다.

**단, 다른 세션이 모델 학습 중이면 충돌합니다.** 시작 전에
`git log --oneline -5` 와 `git status` 로 학습 세션 활동을 확인하고,
활동 중이면 이 항목은 건너뛰십시오.

관련 테스트: `tests/test_retrain_pipeline_e2e.py`, `tests/test_mlops_pipeline.py`

#### 2.5 등각예측 구간 서빙 경로 연결

이전 세션에서 등각예측(conformal prediction) 보정 배율을 측정했으나
**서빙 경로에 연결되지 않았습니다.** 측정만 되고 실제 응답에는 반영되지
않은 상태입니다.

이것도 `src/ml/` 영역이라 학습 세션과 겹칩니다. 확인 후 진행하십시오.

---

## 3. 환경 재현 절차

### 3.1 주의: `uv` 가 이 환경에 없습니다

`AGENTS.md` 는 uv 를 표준이라 하지만 실제로는 설치돼 있지 않습니다.
**`.venv/bin/python` 을 직접 쓰십시오.**

```bash
.venv/bin/python -m pytest tests/ -q
```

macOS 에 GNU `timeout` 도 없습니다.

### 3.2 스택 기동

```bash
open -a Docker                       # 데몬이 내려가 있으면
docker compose up -d db redis
docker compose ps                    # db healthy 확인
python -m alembic upgrade head
```

### 3.3 검증 실행

```bash
.venv/bin/python scripts/verify_migration.py          # G1
.venv/bin/python -m pytest tests/ -q                  # 612 passed / 2 skipped
.venv/bin/python scripts/validate_agent_rules.py      # 6/6
```

### 3.4 벤치마크 (서버 기동 필요)

```bash
.venv/bin/python -m uvicorn src.app.main:app --port 8000 &
.venv/bin/python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000
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

## 6. 현재 Git 상태

```
main:   ca577a8 merge: 원본 테스트 재현율 93.1% 달성 및 낙찰률 렌더링 결함 수정 병합
브랜치: fix/phase7-date-parsing-and-stats-index (6251975, 미병합)
```

작업 브랜치는 전량 테스트 통과 후 `--no-ff` 로 `main` 에 병합하면 됩니다.

---

## 7. 관련 문서

| 문서 | 내용 |
| --- | --- |
| [`docs/ops/phase7_cutover_report_20260804.md`](../ops/phase7_cutover_report_20260804.md) | Phase 7 측정치와 판정 |
| [`docs/design/original_test_parity_20260804.md`](../design/original_test_parity_20260804.md) | 원본 테스트 재현 현황 |
| [`docs/design/prediction_without_amount_20260804.md`](../design/prediction_without_amount_20260804.md) | 금액 미공개 공고 예측 차단 결정 |
| [`docs/design/FRONTEND_DECISION.md`](../design/FRONTEND_DECISION.md) | 화면 재현 결정과 의도적 차이 |
| [`AGENTS.md`](../../AGENTS.md) | 규칙 정본 |
