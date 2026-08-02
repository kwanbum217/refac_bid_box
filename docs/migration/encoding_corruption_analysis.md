# 인코딩 손상 데이터 분석

> **작성일**: 2026-08-02
> **버전**: v1.0.0
> **상태**: 복구 불가 확정, 표시 계층에서 제외 처리 완료
> **결론**: 건설(Cnstwk) 낙찰 결과 1,244,778행의 문자열이 복구 불가능하게 손상됨. **용역(Servc)·물품(Thng)은 무손상.**

---

## 1. 손상 범위

`bid_results` 한 테이블, 건설 카테고리에만 집중되어 있습니다.

| 카테고리 | 전체 | 손상 | 비율 | 기간 |
| --- | ---: | ---: | ---: | --- |
| Cnstwk (건설) | 1,254,295 | **1,244,778** | 99.2% | 2008-12-17 ~ 2025-05-23 |
| Servc (용역) | 889,933 | 0 | 0% | 2012-12-18 ~ 2025-04-07 |
| Thng (물품) | 858,026 | 0 | 0% | 2011-04-26 ~ 2026-07-31 |

`bid_announcements` 는 **전 카테고리 손상 0건**입니다 (1,839,088행).

손상 컬럼은 `bidwinnr_nm`(낙찰업체명), `dminstt_nm`(수요기관명), `bid_ntce_nm`(공고명) 세 개이며, 금액·낙찰률·일자 등 수치 컬럼은 온전합니다.

---

## 2. 복구 가능성 검토

### 2.1 원본 프로젝트 DB — 같은 DB 입니다

원본 `bid_box` 의 접속 설정(`config/settings.py:172-176`, `.env`)은 다음과 같습니다.

```
DB_HOST=127.0.0.1
DB_PORT=3307
DB_NAME=procurement
```

이식본 `DATABASE_URL` 과 **완전히 같은 데이터베이스**입니다. 서버에 다른 스키마도 없습니다(`information_schema`, `mysql`, `performance_schema`, `procurement`, `sys`, `test`).

원본 프로젝트에 접속해 가져올 별도의 온전한 DB 는 존재하지 않습니다.

### 2.2 parquet 덤프 — 이미 손상된 상태

`bid_box/data/exports/` 의 parquet 을 직접 열어 확인했습니다.

| 파일 | 상태 |
| --- | --- |
| `bid_results_thng.parquet` | 정상 (`주식회사 예동산업`, `경상북도 문경시`) |
| `bid_results_servc.parquet` | 정상 |
| `bid_results_cnstwk.parquet` | **손상** (`����ȸ�� ���ѰǼ�`) |

즉 손상은 복원 스크립트(`scripts/restore_from_parquet.py`)가 만든 것이 아니라 **parquet 을 만들기 이전에 이미 발생**했습니다. 재적재해도 같은 값이 들어옵니다.

### 2.2.1 구글 드라이브 백업본 — 로컬본과 동일한 파일

`drive.google.com/drive/folders/1jmYv50RteshWJCklEPlaeX0sGxGejs_J` 의 parquet 6개를 로컬본과 대조했습니다.

| 파일 | 크기 (드라이브 = 로컬) | 수정시각 |
| --- | ---: | --- |
| `bid_results_cnstwk.parquet` | 132,072,206 | 2026-03-22T23:45:45Z |
| `bid_results_servc.parquet` | 111,960,586 | 2026-03-21T18:32:35Z |
| `bid_results_thng.parquet` | 34,753,142 | 2026-03-22T23:45:54Z |
| `bid_announcements_thng.parquet` | 57,380,540 | 2026-03-22T23:45:32Z |
| `bid_announcements_servc.parquet` | 37,474,229 | 2026-03-21T18:26:31Z |
| `bid_announcements_cnstwk.parquet` | 34,237,665 | 2026-03-21T18:25:07Z |

6개 모두 크기와 수정시각이 일치합니다. 드라이브 백업본은 로컬과 같은 파일이며, 손상되지 않은 별도 사본이 아닙니다.

### 2.3 바이트 수준 — 원본 정보가 소실됨

parquet 값의 코드포인트입니다.

```
'����ȸ�� ���ѰǼ�'
[0xfffd, 0xfffd, 0xfffd, 0xfffd, 0x238, 0xfffd, 0xfffd, 0x20, ...]
```

`0x238`, `0x5bd`, `0x1fc` 같은 값은 CP949 바이트쌍이 UTF-8 로 잘못 디코드된 흔적입니다. 예를 들어 `회` 의 CP949 바이트 `C8 B8` 은 UTF-8 2바이트로 해석되어 U+0238 이 됩니다. 이런 값은 역산이 가능합니다.

문제는 **U+FFFD(치환 문자)** 입니다. UTF-8 로 유효하지 않은 바이트열은 디코더가 U+FFFD 하나로 뭉개버렸고, 원래 바이트가 무엇이었는지 정보가 남아 있지 않습니다. 위 예시에서 14자 중 10자가 U+FFFD 입니다.

`주식회사` 의 CP949 는 `C1 D6 BD C4 C8 B8 BB E7` 인데, 이 중 `C1`, `C4`, `BB`, `E7` 이 U+FFFD 로 사라졌습니다. 남은 바이트만으로는 원문을 복원할 수 없습니다.

### 2.3.1 DB 저장 바이트 — 치환 문자가 물리적으로 기록됨

"접속 charset 때문에 깨져 보이는 것" 이라면 원시 바이트는 온전할 수 있으므로, `HEX()` 로 저장 바이트를 직접 확인했습니다.

```sql
SELECT bidwinnr_nm, HEX(bidwinnr_nm) FROM bid_results
WHERE category='Cnstwk' AND bidwinnr_nm LIKE '%<U+FFFD>%' LIMIT 1;
```

```
표시값 : '����ȸ�� ���ѰǼ�'
HEX    : EFBFBD EFBFBD EFBFBD EFBFBD C8B8 EFBFBD EFBFBD 20
         EFBFBD EFBFBD EFBFBD D1B0 C7BC EFBFBD
```

`EF BF BD` 는 U+FFFD 의 UTF-8 표현입니다. 컬럼 charset 은 `utf8mb4` 이고, **치환 문자가 디스크에 그대로 기록**되어 있습니다. 표시 문제가 아니라 저장 시점에 이미 원본 바이트가 사라진 상태입니다.

14자 중 10자가 U+FFFD 입니다(약 71% 소실). `C8B8`, `D1B0`, `C7BC` 는 살아남은 오디코딩 흔적이지만, 소실분을 메울 수 없어 단어 복원이 불가능합니다.

**따라서 DB 에서 parquet 을 다시 만들어도 같은 `EF BF BD` 가 그대로 나갑니다.** 현재 DB 는 깨끗한 원본이 아니라 손상된 결과물입니다.

### 2.4 `raw_data` 백업 — 비어 있음

손상 행 1,244,778건 전부 `raw_data` 가 JSON `null` 입니다. parquet 복구분(`collected_at` 2026-03-12)이 원본 API 응답을 함께 싣지 않았습니다.

---

## 3. 결론

| 경로 | 가능 여부 |
| --- | --- |
| 원본 프로젝트 DB 에서 복사 | 불가 (같은 DB) |
| parquet 재적재 | 불가 (parquet 이 이미 손상) |
| 바이트 역산 | 불가 (U+FFFD 로 정보 소실) |
| `raw_data` 에서 복원 | 불가 (JSON null) |
| **G2B API 재수집** | **가능하나 대규모 작업** |

실제 복구가 가능한 유일한 경로는 조달청 API 재수집입니다. `.env` 에 `serviceKey` 가 있고 `collect_bids` 가 기간 단위 수집을 지원하므로 기술적으로는 가능하지만, 2008년~2025년 건설 낙찰 124만건을 다시 받아야 합니다.

---

## 4. ML 학습 데이터 관점

용역(Servc) 예측 모델을 만든다면 **손상의 영향을 받지 않습니다.**

| 항목 | Servc |
| --- | --- |
| 행 수 | 889,933 |
| 기간 | 2012-12-18 ~ 2025-04-07 (약 12.3년) |
| 인코딩 손상 | 0건 |
| 낙찰률(`sucsf_bid_rate`) 결측 | 110,521건 (12.4%) |
| 낙찰금액 결측 | 1,004건 (0.1%) |

10년치 요건을 충족합니다. 학습 시 유의할 것은 인코딩이 아니라 낙찰률 결측 12.4% 입니다.

건설(Cnstwk) 모델을 만들 때는 문자열 특징(업체명·기관명 임베딩)을 쓸 수 없습니다. 수치 특징은 온전하므로 그 범위에서는 학습이 가능합니다.

---

## 5. 적용한 처리

복구가 불가능하므로 표시 계층에서 제외합니다.

| 대상 | 처리 |
| --- | --- |
| RAG 순위 집계 (`structured_data.py`) | 손상값을 순위에서 제외. SQL 단계에서 U+FFFD 를 걸러내고 파이썬 휴리스틱으로 잔여분 처리 |
| RAG 표본 공고 | 건너뛸 수 없으므로 `CORRUPTED_TEXT_FALLBACKS` 안내 문구로 대체 |
| 사전 집계 스냅샷 (`ranking_snapshots.py`) | 집계 시점에 제외. 제외 발생 여부를 `rank=0` 슬롯에 기록 |
| 대시보드 기관 순위 | `_is_readable_agency_name` 추가 (업체 순위는 이미 처리되어 있었음) |
| SSR 화면 / bids API | 기존 `display_*` 속성으로 이미 처리됨 |

제외하면 집계 모수가 달라지므로 **답변에 안내를 답니다.**

> 일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다. 표시된 순위는 판독 가능한 값 기준입니다.

손상값이 없는 질의에는 안내를 붙이지 않습니다. 검증은 `tests/test_ranking_snapshots.py` (25건).

---

## 6. 참조

- 레이턴시 개선: [`../ops/latency_benchmark.md`](../ops/latency_benchmark.md)
- 복원 스크립트: [`../../scripts/restore_from_parquet.py`](../../scripts/restore_from_parquet.py)
- 무손실 검증: [`db_migration_runbook.md`](db_migration_runbook.md)
