# 착수 지시: 쌍대 검정에 판정용 표본 기준을 반영합니다

> **작성일**: 2026-08-10
> **착수 예정**: 2026-08-11
> **상태**: 완료. 판정용·보고용 이중 집계와 판정 어긋남 경고 반영
> **선행 근거**: [`servc_holdout_serving_gap_20260810.md`](../design/servc_holdout_serving_gap_20260810.md)
> **선행 인수인계**: [`2026-08-10_servc_tuning_handoff.md`](2026-08-10_servc_tuning_handoff.md) 2.6
> **예상 소요**: DB 없이 진행하는 1~4단계 **1시간 20분**, 쿼리 최적화 포함 시 **1시간 50분**

---

## 0. 한 문장

**쌍대 검정 도구가 모델이 배우지 않은 구간까지 채점하고 있습니다.** 표본을
자르지 말고 **판정용(학습 범위 내)과 보고용(전량)을 나란히 출력**하도록 고칩니다.

---

## 1. 착수 전 확인 (5분)

```bash
git checkout main
git pull --ff-only
git log --oneline -1        # 2ac7dca 이후여야 합니다
.venv/bin/python scripts/audit_paired_sample_filter_gap.py
```

마지막 명령이 아래를 출력하면 문맥이 맞습니다. DB 접속이 필요 없습니다.

```
paired_quantile_vs_huber_2025.parquet
  표본 8,995건 / 학습 범위 밖 60건 (0.667%)
  판정이 뒤집힙니다: 전량 'challenger 우세' -> 범위 내 '판별 불가'
```

작업 브랜치를 새로 팝니다.

```bash
git checkout -b feat/paired-sample-filter
```

**주의**: `main` 은 주 저장소에 체크아웃돼 있습니다. 격리 트리에서 작업한다면
`git worktree` 상태를 먼저 확인하십시오.

---

## 2. 설계 결정 (이미 내렸습니다. 다시 논의하지 마십시오)

### 2.1 표본을 자르지 않습니다

**`collect()` 에 범위 필터를 넣지 마십시오.** 표본을 자르면 보고용 수치를 낼
수 없게 되고, `eval_servc_api_path.py` 를 공유하는 다른 스크립트까지 조용히
바뀝니다.

대신 **전량을 그대로 뽑고 출력 단계에서 두 조건으로 나눕니다.**

| 용도 | 표본 | 무엇에 쓰나 |
| --- | --- | --- |
| **판정** | 학습 범위 내 (`70 <= actual <= 110`) | 승격 여부. t 와 최소 감지 차이 |
| **보고** | 전량 | 서비스 성능 기준선 |

근거는 `servc_holdout_serving_gap_20260810.md` 6장입니다. 요약하면, 범위 밖은
어떤 후보든 같은 방식으로 틀리므로 우열이 드러나지 않고(0.667% 가 쌍대 평균차의
37% 를 만듦), 반면 사용자는 그 건들도 겪으므로 보고에서 빼면 안 됩니다.

### 2.2 판정 문구는 범위 내 기준으로 답니다

지금 스크립트는 t 하나로 판정을 출력합니다. 앞으로는 **범위 내 t 로 판정**하고,
전량 수치는 참고로 함께 보입니다. 두 조건의 판정이 갈리면 그 사실을 명시적으로
출력해야 합니다 (`audit_paired_sample_filter_gap.py` 의 뒤집힘 경고와 동일).

### 2.3 필터 상수는 import 합니다

```python
from src.ml.dataset import MAX_WINNING_RATE, MIN_WINNING_RATE
```

하드코딩하면 학습 필터가 바뀔 때 평가만 옛 기준으로 남습니다. 이 작업의 원인이
바로 그런 종류의 어긋남입니다.

---

## 3. 코드 변경 지점

### 3.1 `scripts/compare_servc_models_paired.py`

| 위치 | 변경 |
| --- | --- |
| import 부 | `MIN_WINNING_RATE`, `MAX_WINNING_RATE` 추가 |
| `main()` 의 records 수집 후 | `actual` 로 마스크를 만들어 두 조건 계산 |
| 출력부 | 판정 지표(MAE·제곱오차·구간 폭·피복률)를 두 조건으로 병기 |
| 요약 판정 | 범위 내 t 로 결론. 전량과 갈리면 경고 |

`records` 에 이미 `actual` 이 들어 있으므로 (`164행` 부근) 추가 조회가 없습니다.

```python
frame = pd.DataFrame(records)
inside = frame["actual"].between(MIN_WINNING_RATE, MAX_WINNING_RATE)
n_out = int((~inside).sum())
if n_out:
    print(f"학습 범위 밖 {n_out:,}건({n_out / len(frame) * 100:.3f}%)은 판정에서 제외합니다.")
```

### 3.2 잔차 저장에 `actual` 을 유지하십시오

`data/analysis/servc_residuals/paired_*.parquet` 은 이미 `actual` 을 담고
있습니다. **이 컬럼을 빼지 마십시오.** 사후 재계산이 이것에 의존합니다.

### 3.3 (선택) 쿼리 최적화 — `scripts/eval_servc_api_path.py:55-70`

현재 표본 추출이 매우 무겁습니다. 2026-08-10 에 DB 경합과 겹쳐 **40분을
기다려도 응답이 없었습니다.**

| 문제 | 지금 | 고칠 방향 |
| --- | --- | --- |
| 인덱스 미사용 | `func.year(BidResult.rl_openg_dt) == year` | `rl_openg_dt >= '<year>-01-01'` AND `< '<year+1>-01-01'` 범위 조건 |
| 전체 정렬 | `.order_by(func.rand(seed))` | 연도 범위로 대상을 줄인 뒤 정렬. 그래도 무거우면 `MOD(id, k)` 해시 표본 검토 |

**범위 조건은 부수 효과로 SQLite 호환성도 좋아집니다** (`func.year` 는 SQLite 에
없습니다). 테스트에서 이 함수를 직접 태울 수 있게 됩니다.

무작위성의 재현성(같은 seed = 같은 표본)은 유지해야 합니다. 과거 측정과 표본이
달라지면 기준선 비교가 끊깁니다.

---

## 4. 검증

### 4.1 DB 없이 (여기까지 반드시 오늘 안에)

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/validate_agent_rules.py
.venv/bin/python scripts/audit_paired_sample_filter_gap.py
```

새 단위 테스트를 추가하십시오. 최소 두 가지입니다.

| 테스트 | 확인 |
| --- | --- |
| 범위 밖 행이 판정 집계에서 빠지는가 | 인위 표본에 `actual=50` 을 섞어 판정 n 이 줄어드는지 |
| 두 조건 판정이 갈릴 때 경고가 나오는가 | 뒤집히는 표본을 만들어 출력 문자열 확인 |

### 4.2 DB 필요 (여유 있을 때)

```bash
.venv/bin/python scripts/compare_servc_models_paired.py \
    --base servc_institution_v1 --challenger servc_institution_v1 --samples 300
```

같은 모델을 양쪽에 넣으면 **평균차가 정확히 0** 이어야 합니다. 이것이 배선
검증입니다. 표본이 작아도 됩니다.

**DB 상태를 먼저 보십시오.** 2026-08-10 20:15 기준 19건의 장기 쿼리가 물려
있었고 최장 59분이었습니다.

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.app.core.db import SessionLocal
from sqlalchemy import text
s=SessionLocal()
rows=[dict(r._mapping) for r in s.execute(text('SHOW PROCESSLIST')).all()]
busy=[d for d in rows if d.get('Command')!='Sleep' and (d.get('Time') or 0)>5]
print(f'5초 이상 쿼리 {len(busy)}건')
s.close()"
```

**다른 섹션의 쿼리를 KILL 하지 마십시오.** 자기 쿼리만 `Info` 로 식별해
`KILL QUERY <id>` 합니다.

---

## 5. 완료 기준

| # | 기준 |
| --- | --- |
| 1 | 쌍대 검정이 판정용·보고용 수치를 함께 출력한다 |
| 2 | 판정 결론이 범위 내 t 로 나온다 |
| 3 | 두 조건이 갈리면 경고가 출력된다 |
| 4 | 필터 상수를 `dataset.py` 에서 import 한다 |
| 5 | 전체 테스트 통과 + 규칙 검증 6/6 |
| 6 | 4.2 배선 검증 완료 **또는** 미검증임을 문서에 명시 |

**6번을 미룬 채 병합해도 됩니다.** 다만 미검증 상태로 새 승격 판정을 내리지
마십시오.

---

## 6. 하지 말아야 할 것

| 금지 | 이유 |
| --- | --- |
| 이 작업 전에 새 쌍대 검정을 돌려 승격 판단 | 또 이상치가 섞인 판정을 얻습니다 |
| `collect()` 에 범위 필터 삽입 | 2.1 참조. 보고용 수치를 잃고 공유 스크립트가 바뀝니다 |
| 필터 상수 하드코딩 | 2.3 참조. 이 작업의 원인이 그것입니다 |
| 기록된 운영 기준선(1.4050 등)을 범위 내 수치로 덮어쓰기 | 그것들은 보고용(전량)입니다. 새 수치는 별도 항목으로 |
| `quantile(0.5)` 롤백 | 판별 불가일 뿐 악화가 아니며 두 해 방향이 일관합니다 |

---

## 7. 이어지는 과제

이 작업이 끝나면 다음 순위는 이렇습니다.

| 순위 | 과업 | 비고 |
| ---: | --- | --- |
| 1 | 공사 전용 모델 학습 | **사용자 결정 필요.** 1,358,882행, 라우팅은 준비됨 |
| 2 | 하한율 보유인데 낙찰률 51% 인 38건의 정체 | 데이터 품질. 제도적으로 성립하지 않는 조합 |
| 3 | 학습 필터 `[70,110]` 자체의 타당성 | `MIN_WINNING_RATE` 의 근거가 코드에 없습니다 |
| 4 | 물품 승격본 운영 경로 재측정 | 2026-08-06 승격 이후 미측정 |

3번은 이 작업과 짝입니다. 평가를 학습 기준에 맞췄는데 **그 학습 기준 자체가
임의값이면** 정상 건을 버리고 있을 수 있습니다.

---

## 8. 실행 결과 (2026-08-12)

### 8.1 산출물

| 산출물 | 결과 |
| --- | --- |
| [`scripts/compare_servc_models_paired.py`](../../scripts/compare_servc_models_paired.py) | 전량 보고와 학습 범위 내 판정을 순수 함수로 분리하고, 두 조건의 요약·쌍대 지표와 어긋남 경고를 함께 출력합니다. |
| [`tests/test_paired_sample_filter.py`](../../tests/test_paired_sample_filter.py) | 범위 밖 표본의 판정 제외와 전량·범위 내 판정 어긋남을 인위 최소 표본으로 검증합니다. |
| [`scripts/audit_paired_sample_filter_gap.py`](../../scripts/audit_paired_sample_filter_gap.py) | 기존 parquet 감사 도구를 재실행해 2025년 8,995건 중 60건(0.667%)이 범위 밖이며 판정이 뒤집히는 것을 재확인했습니다. |

학습 범위는 `src/ml/dataset.py`의 `MIN_WINNING_RATE`와
`MAX_WINNING_RATE`를 가져와 사용하며, 쌍대 t 판정 기준 `T_THRESHOLD = 2.0`은
변경하지 않았습니다. 범위 밖 표본 수와 비율은 0건일 때도 항상 출력합니다.

### 8.2 검증과 남은 위험

| 검증 | 결과 |
| --- | --- |
| `uv run pytest tests/ -q` | 821건 통과, 4건 건너뜀, 격리 트리의 알려진 데이터 자산 테스트 2건 실패 |
| `uv run python scripts/validate_agent_rules.py` | 6/6건 통과 |
| `uv run ruff check .` | 통과 |
| `uv run python scripts/audit_paired_sample_filter_gap.py` | 2025년 8,995건 중 범위 밖 60건(0.667%), 전량 `challenger 우세`에서 범위 내 `판별 불가`로 뒤집힘 재현 |

격리 작업 트리에 `data/model_files/*/model.bin`이 없어 실제 서빙 모델을 불러오는
4.2 배선 검증은 수행하지 않았습니다. 또한 기존 쌍대 parquet은 당시
`predict_optimal_price`의 자동 대체 동작 때문에 base와 challenger가 실제로 같은
모델이었을 가능성을 배제할 수 없으므로, 모델 출처 결함 수정과 실제 모델 기반
종단 재검증 전에는 기존 측정치로 승격 판단을 내려서는 안 됩니다.
