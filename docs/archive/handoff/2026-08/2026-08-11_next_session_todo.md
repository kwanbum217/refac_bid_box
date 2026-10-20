# 토큰 리셋 후 착수 목록

> **작성일**: 2026-08-11
> **기준 상태**: `main` `530b6d0`, `origin` 동기화 완료, 미커밋 없음
> **갱신**: 2026-08-11 15:15. 오후 작업 반영
> **방침**: 용역(Servc) 우선

---

## 0. 세션 시작 시 먼저 할 것

| 순서 | 명령 | 이유 |
| --- | --- | --- |
| 1 | `orca orchestration check --ack <delivery_id>` | 큐에 Claude 발신 공지가 남아 알림이 반복됩니다 |
| 2 | `export PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin` | Docker CLI 가 기본 PATH 에 없습니다 |
| 3 | `docker compose up -d db redis meilisearch` | 볼륨 3종 보존돼 재색인 없이 붙습니다 |
| 4 | db 가 `healthy` 될 때까지 대기 | 준비 전에 pytest 를 돌리면 50건 실패로 오판합니다 |

---

## 1. 착수 후보 (우선순위 순)

### A0. 하한율 결측 메커니즘 재분해 — 최우선

2025-01 원천 체제 전환으로 `sucsfbidLwltRate` 값 존재율이 96.3% 에서 56.8% 로 떨어졌고 현재 38.3% 입니다. 학습에 쓰는 `lwlt_rate` 의 원천입니다.

기존 진단은 결측의 99.1% 를 제도적 부재로 설명했습니다(`servc_lwlt_missing_mechanism_20260810.md`). **전환 이후 표본으로 다시 분해해 같은 비율이 나오는지 확인하십시오.** 다르면 결측의 성격이 바뀐 것이고 `lwlt_rate_missing` 지시자 하나로는 부족합니다.

근거는 `servc_2025_source_regime_shift_20260811.md` 입니다. 권장: Opus 5 / effort high. 판정이 갈리는 지점입니다.

### A1. 제도 플래그 특징 추가 실험

미사용 플래그 다섯 개가 현행 잔차에 세 연도 일관된 편향을 남깁니다. `indstrytyLmtYn` 은 집단 간 편향 폭 0.42%p(t +19.4 / -10.5) 입니다.

단 `prdctClsfcLmtYn` 과 `rbidPermsnYn` 은 2025-01 전환이 있어 그대로 넣으면 두 체제를 한 수준으로 섞습니다. 체제 지시자와의 상호작용이 유력하며, 기존 `is_post_regime_shift` 는 2026-05-26 경계라 별도 지시자가 필요합니다.

근거는 `servc_unused_rawdata_field_audit_20260811.md` 입니다. 권장: Opus 5 / effort high.

### A2. 건설(Cnstwk) parquet 재생성 — 용역 아님, 방침 확인 필요

`dataset_Cnstwk.parquet` 이 구형 12컬럼 스키마라 `lwlt_rate` 를 포함한 제도 필드 16개가 통째로 빠져 있습니다. DB 공고 테이블에는 **2019~2026 전 연도에 하한율이 사실상 100%** 있습니다.

| parquet | 행 수 | 컬럼 | `lwlt_rate` |
| --- | ---: | ---: | --- |
| Servc | 917,629 | 28 | 있음 |
| Cnstwk | 1,358,882 | 12 | **없음** |
| Thng | 784,266 | 12 | 없음 |

1,358,882행 전체가 회수 대상입니다. **다만 용역이 아니므로 사용자 방침 확인이 선행되어야 합니다.**

권장: Opus 5 / effort medium. 재생성 자체는 절차적이고, 판정은 재학습 후 기존 검정망으로 합니다.

### B. Codex `docs-env-contract` 미커밋 수습

작업 트리 `/Users/kwanbum/orca/workspaces/refac_bid_box/docs-env-contract`, 브랜치 `kwanbum217/docs-env-contract`, 커밋 `cd727d8` + 미커밋 7개 파일.

미커밋 파일: `src/app/core/config.py`, `docker-compose.yml`, `.env.example`, `docs/ops/environment_variables.md`, `tests/conftest.py`, `tests/test_security_config.py`, `tests/test_worker_compose.py`

내용은 `SECRET_KEY` 필수·32자 검증, production 보안 기본값 차단, healthcheck 및 healthy 의존성입니다.

**미수행 검증**: 전체 pytest, `validate_agent_rules.py`, compose 실기동. 이어받으면 최신 `main` `1cb7679` 반영 후 이 셋을 먼저 돌리십시오.

주의: `config.py` 가 병합된 검색 경로의 `_meili_enabled()` 와 계약이 닿습니다.

권장: Opus 5 / effort medium. 남의 미검증 변경이라 무엇이 나올지 모릅니다.

### C. 물품(Thng) 후속 — 재생성 검증까지 완료, 연기 상태

재생성물이 `data/feature_store_rebuild_20260811/dataset_Thng.parquet` 에 있습니다. 756,702행 x 28컬럼으로 G2 문서 예측과 전부 일치했습니다. 원본은 건드리지 않았습니다.

실익은 하한율이 아니라 `ntce_kind_nm`(고유 3), `bid_methd_nm`(고유 7) 두 컬럼입니다. 전 기간 100% 채워집니다. 하한율 유효분 14,766건은 전부 홀드아웃이라 학습 80% 에 0건이므로 기여를 측정할 수 없습니다.

주의: 용역에서 중요도 1위였던 `clsfc_nm` 은 물품에서 0% 입니다.

#### 원래 항목

감사 결과 34특징 중 17개가 상수. 원인은 구형 12컬럼 parquet. 다만 물품은 DB 하한율이 2026 이전 0%, 2026 년 70.6% 라 재생성 회수량이 작습니다.

미검증 수치: 워커 보고의 "회수분 3.64%(28,547건), 전부 홀드아웃 구간" 은 코디네이터가 재지 않았습니다.

### D. 적격심사제 계열 피복률 — 지금은 조치 금지

| 칸 | 건수 | 피복률 | t |
| --- | ---: | ---: | ---: |
| P.Q비대상 기술용역 | 101 | 86.14% | -1.12 |
| P.Q대상 기술용역 | 72 | 86.11% | -0.95 |
| 수기심사(총점입력) | 272 | 86.76% | -1.58 |

**t 가 전부 -1.6 미만이라 유의하지 않습니다.** 다음 재학습 후 같은 스크립트로 재측정해 부호가 유지되는지만 확인하십시오. 지금 손대면 잡음을 좇습니다.

### E. 완료 섹션 자원 정리 — GPT 작업 종료 후

Orca 좌측 목록에 끝난 섹션의 워크트리·브랜치가 남아 활성 섹션과 구분되지 않습니다. **GPT 의 G1·G2·G3 가 전부 끝난 뒤** 한 번에 정리하십시오. 활성 트리가 하나라도 있으면 하지 마십시오.

정리 대상(전부 `origin/main` 에 완전 병합 확인됨)입니다.

| 워크트리 | 병합 커밋 |
| --- | --- |
| `claude-thng-feature-audit` | `2054ead` |
| `claude-quantile-releaf` | `db96317` |
| `claude-servc-tuning` | 2026-08-10 병합 |
| `fix-search-api-timeout` | `8f628fc` |
| `docs-mlops-index-sync` | `1cb7679` |
| `docs-env-contract` | `23b63f9` |

`claude-deep-page-pagination` 은 트리가 이미 해제됐고 브랜치만 남아 있습니다.

절차는 `orca-section-coordination` 스킬 7장을 따르십시오. `git branch -d` 가 거부하면 병합되지 않았다는 뜻이므로 `-D` 로 강제하지 마십시오.

권장: Opus 5 / effort low. 절차적 작업입니다.

---

## 2. 하지 말 것

| 항목 | 이유 |
| --- | --- |
| LightGBMLSS, NGBoost 도입 | 2026-08-11 기각. `servc_interval_coverage_recheck_20260811.md` |
| `asignBdgtAmt`, `cntrctCnclsMthdNm` 특징 추가 | 기존 `base_amount`, `cntrct_mthd_nm` 과 100% 동일. 중복 |
| 잔차 후처리 계열 재시도 | 다섯 축 전부 기각됨 |
| 분위 `num_leaves` 127/255 | 세 분할 전부에서 63 최소 |
| `quantile` alpha 조정 | 분할 변동 안이었음 |

착수 전 `servc-model-tuning` 스킬의 기각 목록을 먼저 읽으십시오.

---

## 3. 미해결로 남긴 것

`servc_loss_function_20260807.md` 8.3 의 "구간 폭 1.6706 / 피복률 89.56%" 가 2026-08-11 재측정 1.6385 / 89.47% 와 정확히 일치하지 않습니다. 표본 시점 차이로 보이나 확정하지 않았습니다.

---

## 4. 재개 시 함정

| 항목 | 내용 |
| --- | --- |
| pytest 조기 실행 | db `healthy` 전에 돌리면 50건 실패. 컨테이너 준비를 먼저 확인 |
| 격리 트리 검증 예외 | `test_model_bin_files_exist`, `test_chroma_db_exists` 실패는 정상. 주 저장소에서 단독 재실행 |
| 운영 경로 스크립트 | `model.bin` 을 읽으므로 격리 트리에서 동작하지 않습니다. 주 저장소에서만 실행 |
| Orca Run 바인딩 | 이전 Run 은 그 코디네이터 터미널에 묶여 `consumer_fenced`. 새 Run 생성 |
| Orca 메시지 | `--ack <delivery_id>` 없이는 같은 배치가 계속 재배달됩니다 |
| Puppeteer | 번들 Chromium 이 `spawn -88` 로 실패. 시스템 Chrome 을 `executablePath` 로 지정 |
| curl 한글 질의 | 미인코딩 UTF-8 은 uvicorn 이 400 으로 거부. `--data-urlencode` 사용 |
| UI 측정 | 목록 페이지는 로그인 필수. 임시 계정은 반드시 삭제하고 사용자 4명 복귀 확인 |
