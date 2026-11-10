# 적격심사 배지·색인 문서의 첨부 판별 갈래 미반영 (I-data F-04)

> 작성일: 2026-11-09
> 범위: 목록·홈 '적격심사 분석' 배지, Meilisearch 색인 문서, 갈래 분류 후 색인 갱신

---

## 1. 원인
판정 단일 함수 `is_qualification_analyzable(row, attachment_regime)` 는 이미 갈래를 인자로 받았고,
DB 대체 필터(`src/app/services/bid_queries.py:591-593`)와 `/api/v1/evaluations/analyze`
(`src/app/api/v1/evaluations.py:2280`)는 저장된 갈래를 넘겼습니다. 그러나 아래 세 경로는
`attachment_regime` 을 빠뜨려 같은 공고를 다르게 판정했습니다.

| 경로 | 수정 전 | 결과 |
| --- | --- | --- |
| `src/app/api/ui.py:235` | 갈래 없이 `qualification_analyzable_ids(page_obj.object_list)` 호출 | 목록 배지 누락 |
| `src/app/services/home_context.py:266` | 갈래 없이 홈 배지 계산 | 홈 카드 배지 누락 |
| `src/app/services/search_index.py:101` | 문서 생성 시 `is_qualification_analyzable(row)` | Meilisearch `qualification_analyzable=false` 색인으로 `qual=1` 필터 누락 |

운영은 `MEILI_ENABLED=true` 이므로 목록 필터가 색인 문서 값을 사용합니다. '2억미만 1억이상'
띠 용역 공고는 갈래가 없으면 규칙 판별이 차단되어, 상세 분석에서는 계산되는 공고가 목록
배지·필터에서 빠지거나 반대로 노출되는 불일치가 생겼습니다.

## 2. 변경
- `src/app/api/ui.py`: 목록 공고 묶음마다 `lookup_attachment_regimes` 를 한 번 호출해 `qualification_analyzable_ids` 에 전달합니다. 공고별 단건 질의는 없습니다.
- `src/app/services/home_context.py`: 홈 화면 공고 묶음 단위로 갈래를 한 번 조회합니다.
- `src/app/services/search_index.py`: `announcement_document` 가 `attachment_regime` 을 받고, `_build_announcement_batch` 가 배치당 한 번 조회한 갈래를 넘깁니다. 새 공개 함수 `upsert_announcement_documents` 는 지정한 공고 문서만 기존 upsert 경로로 다시 씁니다.
- `scripts/classify_band_regime.py`: 새로 `CLASSIFIED` 로 저장된 공고 키를 모아 실행 끝에 `upsert_announcement_documents` 로 색인 문서를 갱신합니다. `MEILI_ENABLED=false` 면 `search_index` 가 건너뛰며, 색인 실패는 판별 결과 저장을 되돌리지 않고 요약에 남깁니다.
- 판정 로직은 복제하지 않았고, 다섯 경로 모두 기존 단일 함수를 그대로 씁니다.

## 3. 운영 영향
`bid_announcement_regime` 에서 `CLASSIFIED` 이면서 `Servc` 공고와 키가 맞는 행의 갈래별 건수입니다.

| 갈래 | 건수 | 판정 변화 |
| --- | --- | --- |
| `MOIS_ACADEMIC` | 76 | 차단 해제, 배지·필터 대상에 새로 포함(예: `R25BK01150429`) |
| `MOIS_TECH` | 2 | 차단 해제. 단 `contract_regime != NATIONAL` 조건을 통과할 때 |
| `PPS` | 3 | 차단 해제. 첨부 근거가 별표 1 학술연구를 지목할 때(3건 모두 `sucsfbidMthdAppStd` 확인) |
| `MOIS_OTHER`·`LOCAL`·`UNSPECIFIED*` | 8 | 기존과 동일(차단 유지) |

갈래가 붙은 81건이 배지·필터·색인에서 분석 API 와 같은 방향으로 판정됩니다. 실제로 분석
대상으로 뒤집히는 건수는 규칙 시행일과 예정가격 기준액 보유 여부에 따라 81건보다 작을 수 있습니다.

## 4. 병합 후 필요한 운영 조치
기존 색인 문서에는 갱신 전 판정이 남아 있으므로 병합 후 전체 재색인을 한 번 실행합니다.
이후 일일 `band_regime_daily` 실행은 새로 분류된 공고의 문서를 같은 실행에서 갱신합니다.
```sh
docker compose exec app env MEILI_TIMEOUT_SECONDS=30 python3 scripts/sync_search_index.py
```
