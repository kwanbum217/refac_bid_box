# 2026-08-11 다중 섹션 작업 인수인계

> **작성일**: 2026-08-11
> **Orca Run**: `run_e41fdb3038c5`
> **main**: `8f628fc`
> **상태**: Claude 섹션 Task 4건 전부 완료. 병합은 하나도 수행하지 않음

---

## 1. 요약

Claude 섹션은 전날 실패한 브라우저 E2E를 이어받아 마무리하고, 용역(Servc) 모델 후속 두 건과 검색 성능 개선 한 건을 수행했습니다. 네 Task 모두 검증을 마쳤으나 **`main` 병합은 사용자 승인 대기 상태**입니다.

같은 시각 GPT 섹션과 Codex 섹션이 비ML 문서·설정 작업을 별도 브랜치에서 수행했습니다.

---

## 2. 완료 Task

| Task | 제목 | 결과 |
| --- | --- | --- |
| `task_61b9e8986b2c` | 브라우저 필터 전면 E2E와 깊은 페이지 지연 규명 | 312회 측정 오류 0. 원인 확정 |
| `task_c1f1556549af` | S1 물품(Thng) 특징 값 감사 | 34특징 중 17개 상수. 결함 성립 |
| `task_37f8ed149678` | S2 분위 모델 hyperparams 통로와 재측정 | 통로 개설. 리프 63 유지, 용량 상향 기각 |
| `task_3f3136ce6b40` | S3 정렬 목록 깊은 페이지 지연 개선 | TTFB 1156ms 에서 4ms |

---

## 3. 병합 대기 (전부 미병합)

| 순번 | 브랜치 | 커밋 | 내용 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | `kwanbum217/claude-deep-page-pagination` | `48bf5a9` | `MAX_LIST_PAGE=1000` 상한 | 테스트 799 passed, 규칙 6/6 |
| 2 | `kwanbum217/claude-quantile-releaf` | `139f023` | 분위 하이퍼파라미터 통로 | pre-commit 6/6 통과 |
| 3 | `kwanbum217/claude-thng-feature-audit` | `9b9be33` | 물품 감사 문서·스크립트 | 워크트리 해제됨 |

**병합 순서 주의**: 3번을 병합하며 `docs/README.md` 인덱스를 수정하면 GPT 섹션의 `4aa15bc`(브랜치 `docs-mlops-index-sync`)와 같은 파일을 건드립니다. 먼저 병합된 쪽을 기준으로 나중 것을 올리십시오.

---

## 4. 브라우저 E2E 결과

### 측정

| 항목 | 결과 |
| --- | --- |
| 필터 매트릭스 16케이스 290회 | HTTP 200 100%, 오류 0, 빈 결과 0 |
| 깊은 페이지 제외 전 케이스 P95 | 9.7 ~ 122.2ms |
| 실제 문서 내비게이션 22회 | P50 70.4ms (TTFB 15.6ms + 파싱·렌더 약 52ms 고정) |
| 유일한 이상치 공고 `page=100000` | P50 1005.9ms / P95 1478.8ms |

전날 보고된 "API P95 1048ms 대 브라우저 78ms" 간극은 **표본 편향**이었습니다. 전날 브라우저 12회가 깊은 페이지를 밟지 않았을 뿐입니다.

### 원인

Meilisearch 를 직접 호출해 분리했습니다.

| 조건 | `processingTimeMs` |
| --- | --- |
| offset 1,999,980, 정렬 없음 | 3 |
| offset 0, 정렬 있음 | 1 |
| offset 20,000, 정렬 있음 | 17 |
| offset 1,999,980, 정렬 있음 | 995 |

앱 코드나 MySQL 이 아니라 **Meilisearch 의 정렬 적용 깊은 offset 특성**입니다.

---

## 5. S3 깊은 페이지 개선

`MAX_LIST_PAGE = 1000` 상한을 두고, 상한 밖 요청은 Meilisearch 도 MySQL fallback 도 호출하지 않습니다. 마지막 페이지에서 다음 링크를 감춰 상한을 화면에 노출합니다.

| 케이스 | 변경 전 TTFB | 변경 후 |
| --- | --- | --- |
| 공고 `page=100000` P50 | 1156ms | 4ms |
| 공고 `page=100000` P95 | 1218ms | 5ms |
| 지역 정렬 깊은 페이지 | 922ms | 4ms |
| 낙찰 깊은 페이지 | 149ms | 5ms |

page 1/2/1000 은 잡음 범위 내 무변화입니다. keyset 방식은 정렬 키 수치형 색인과 `filterableAttributes` 확장 후 823만 문서 재색인이 선행되어야 하고 페이지 번호 주소와 `start_index` 계약을 깨므로 기각했습니다.

전 세션에서 별건으로 남긴 `opengdt is not sortable` 은 **진단 당시 curl 오타**였고 운영 경로 영향은 없습니다.

---

## 6. S1 물품 특징 감사

물품 34개 특징 중 **17개가 고유값 1개인 상수**입니다(`lwlt_rate`, `lwlt_rate_missing`, `tech_ablt_evl_rt`, `bid_prce_evl_rt`, `tot_prdprc_num`, `drwt_prdprc_num` 과 범주 11종 전부).

원인은 시각 역전입니다. 빌더에 제도 필드를 넣은 커밋 `646d460` 이 14:48, parquet 생성이 13:08 이라 parquet 이 구형 12컬럼 스키마로 남았습니다. 서빙은 DB `raw_data` 에서 실값을 넘기므로 용역 `inst_sample_cnt` 와 같은 형태의 train/serve skew 이되 방향이 반대입니다.

영향은 작습니다. 해당 특징군의 LightGBM 분기 이득이 전체의 0.0090%, 예측 절대차 평균 0.0378%p(MAE 2.8958 의 1.3%)로 성능 손실보다 기회 손실입니다.

### 코디네이터 직접 검증

| parquet | 행 수 | 컬럼 | `lwlt_rate` |
| --- | --- | --- | --- |
| Servc | 917,629 | 28 | 있음 |
| Thng | 784,266 | 12 | 없음 |
| Cnstwk | 1,358,882 | 12 | 없음 |

DB 공고 테이블의 하한율 커버리지입니다.

| 카테고리 | 2019~2025 | 2026 |
| --- | --- | --- |
| Cnstwk | 99.0~100% | 100% |
| Thng | 0% | 70.6% |
| Servc | 97.8~100% | 100% |

**건설(Cnstwk)은 1,358,882행 전 연도에 하한율이 사실상 100% 있는데 구형 12컬럼 parquet 탓에 전부 버려지고 있습니다.** 물품은 2026년 이전이 0%라 재생성해도 회수량이 거의 없습니다. 물품 감사를 지시했으나 건설에서 더 큰 구멍이 나온 셈입니다.

사용자 방침이 용역 우선이므로 건설 재생성은 연기했습니다. 위 수치가 있으므로 재조사 없이 착수할 수 있습니다.

미검증 항목: 워커가 보고한 물품 재생성 회수분 "3.64%(28,547건), 전부 홀드아웃 구간" 은 코디네이터가 따로 재지 않았습니다.

---

## 7. S2 분위 모델 재측정

`_train_quantile_models` 가 `hyperparams` 를 받지 못해 분위 모델이 카테고리와 무관하게 리프 63 에 고정돼 있던 구조를 해소하고, `QUANTILE_HYPERPARAM_KEY = "lightgbm_quantile"` 로 점 추정 키와 분리했습니다. `objective` 와 `alpha` 는 분위별로 정해지므로 이 통로로 받아도 무시합니다.

현행 목적함수에서 리프 31/63/127/255 를 검증연도 2023/2024/2025 세 분할로 재측정한 결과입니다.

| 검증연도 | 리프 63 구간 폭 | 127 | 255 |
| --- | --- | --- | --- |
| 2023 | 1.6317 (최소) | +1.4~3.7% | +5~10% |
| 2024 | 1.6833 (최소) | 동일 방향 | 동일 방향 |
| 2025 | 1.8250 (최소) | 동일 방향 | 동일 방향 |

부호가 갈리는 칸이 없어 **용량 상향을 기각**했습니다. 127 이 이기는 유일한 칸은 하한율 결측 집단 피복률 +0.25~1.06%p 인데, 이는 전역 등각 배율이 보유 집단(90.3~91.1%, 과잉)과 결측 집단(88.0~88.7%, 과소)에 잘못 배분되는 문제이며 집단별 배율은 이미 기각된 접근이라 운영 쌍대로 보내지 않았습니다.

### 범위 검증

| 확인 | 결과 |
| --- | --- |
| Servc 단독 측정 | 통과. 스크립트 인자와 실행 프로세스 모두 `dataset_Servc.parquet` |
| 다른 카테고리 조치 | 없음 |
| 통로 일반화 | 통과 |

---

## 8. 다음 세션에서 가장 먼저 볼 것

**기존 조사보고서의 "하한율 결측 집단 피복률 80.32%" 는 저장소 어디에도 근거가 없습니다.**

기록된 값은 87.95%, 이번 재측정은 88.02 / 88.21 / 88.68% 입니다. 이 80.32% 는 "결측 집단만 유독 나쁘다" 는 서사의 근거였고 분포 예측 계열(LightGBMLSS, NGBoost) 도입 논거의 출발점이었습니다. **근거가 사라졌으므로 해당 방향의 기대값을 다시 따져야 합니다.**

재현에 성공한 인용 수치는 `conformal_scale` 1.151263, 운영 MAE 1.4159 에서 1.4050(t=-2.89), 집단별 t(+4.20 / -8.90) 입니다. 구간 폭 1.6706 과 피복률 89.56% 는 격리 트리에 `model.bin` 이 없어 운영 경로 재계산이 불가했습니다.

---

## 9. 사용자 결정 대기

1. 병합 3건의 승인 여부와 순서
2. 분포 예측 계열 도입 여부. 신규 의존성이므로 `AGENTS.md` 금지 3 에 따라 사전 합의 필요하며, 8장 때문에 기대값 재검토가 선행되어야 합니다
3. 연기 항목: 건설 parquet 재생성, 물품 후속

---

## 10. 타 섹션 상태

### GPT 섹션

브랜치 `docs-mlops-index-sync` 에 커밋 `4aa15bc`. `docs/README.md` 의 "MLOps 알림 구현 미착수" 표기를 완료 상태로 수정. push 및 병합 미수행.

전 시각 상태 보고에서 "Docker 중지 상태" 라고 했으나 사실과 달라 정정을 발송했습니다. 실제로는 4개 컨테이너가 가동 중이었습니다.

### Codex 섹션

작업 트리 `/Users/kwanbum/orca/workspaces/refac_bid_box/docs-env-contract`, 브랜치 `kwanbum217/docs-env-contract`. 커밋 `cd727d8` 과 **미커밋 변경**이 있습니다.

미커밋 소유 파일: `src/app/core/config.py`, `docker-compose.yml`, `.env.example`, `docs/ops/environment_variables.md`, `tests/conftest.py`, `tests/test_security_config.py`, `tests/test_worker_compose.py`.

적용 내용은 `SECRET_KEY` 필수 및 32자 검증, production 보안 기본값 차단, app/redis/meilisearch healthcheck 와 healthy 의존성입니다. 보안·Compose 테스트 9 passed, Ruff 통과, YAML 정적 파싱 통과이나 **전체 pytest, `validate_agent_rules.py`, Docker compose 실재기동은 미수행**입니다.

Codex 가 발견한 미수정 결함: `scripts/validate_windows.ps1:31` 이 health 응답을 `ok` 로 기대하지만 `src/app/api/v1/health.py` 는 `healthy` 를 반환합니다.

주의: Codex 소유 `src/app/core/config.py` 는 파일이 겹치지 않지만 **계약이 닿아 있습니다.** S3 의 `bid_queries.py` 가 `_meili_enabled()` 로 그 설정에 의존하므로, 검색 관련 설정 키의 이름이나 기본값이 바뀌면 병합 시점에 어긋날 수 있습니다.

---

## 11. 환경과 재개 시 함정

| 항목 | 내용 |
| --- | --- |
| Docker | app / db / redis / meilisearch 4개. 종료는 `docker compose down` |
| Docker CLI | PATH 에 없습니다. `/Applications/Docker.app/Contents/Resources/bin` 를 추가하십시오 |
| Meilisearch 볼륨 | `refac_bid_box_meilisearch_data` 에 8,235,757 문서 보존. 잘못 내리면 재색인 비용 발생 |
| 브라우저 자동화 | Puppeteer 번들 Chromium 은 `spawn -88` 로 실패합니다. 시스템 Chrome 을 `executablePath` 로 지정하십시오 |
| UI 측정 | 목록 페이지는 로그인 필수입니다. 임시 계정을 만들면 반드시 삭제하고 사용자 4명 기준선 복귀를 확인하십시오 |
| curl 한글 질의 | 미인코딩 UTF-8 은 uvicorn 이 400 으로 거부합니다. `--data-urlencode` 를 쓰십시오 |
| Orca Run 바인딩 | 전날 Run 은 그 코디네이터 터미널에 묶여 `consumer_fenced` 로 이어붙일 수 없습니다. 새 Run 을 만드십시오 |
| Orca 메시지 | `check` 는 `--ack <delivery_id>` 를 주지 않으면 같은 배치를 계속 재배달합니다 |

---

## 12. 데이터 무손실 확인

| 항목 | 값 |
| --- | --- |
| `bid_announcements` | 5,461,126 행 (불변) |
| 사용자 계정 | 4명 (임시 계정 원복 완료) |
| `django_session` | 0 건 |
| Meilisearch 문서 | 8,235,757 (재색인 없음) |
