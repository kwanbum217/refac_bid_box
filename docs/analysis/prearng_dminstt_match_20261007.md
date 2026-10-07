# 예비가격-공고 수요기관명 연결과 매칭률 측정

> **작성일**: 2026-10-07
> **작성자**: Orca builder (task_91cda2d6d7b5)
> **범위**: `bid_prearng_prices.dminstt_nm` 을 `bid_announcements` 의 (공고번호, 정규화 차수, category) 로 잇는 조회 작성과 매칭률 측정
> **코드 변경**: `scripts/link_prearng_dminstt.py`, `tests/test_link_prearng_dminstt.py`
> **DB 변경**: 없음. 운영 DB 는 읽기 전용 조회만 수행했고 대량 갱신은 실행하지 않았다.
> **근거**: [prearng_price_collection_feasibility_20261006.md](prearng_price_collection_feasibility_20261006.md) 7.1·12장, [handoff_20261006_web_feedback_session_close.md](../ops/handoff_20261006_web_feedback_session_close.md) 1장 11번
> **선행**: 8번 예비가격 소급 수집(`bid_prearng_prices` 353,012건, 3장)

---

## 1. 결론 요약

| 질문 | 판정 | 근거 |
| --- | --- | --- |
| 조인 키 (공고번호, 정규화 차수, category) 로 연결되는가 | **연결됨** | 매칭률 99.9751%([실측]) |
| 차수 정규화가 결과를 바꾸는가 | **바꾸지 않음** | 두 원장 모두 3자리 zero-pad 로 이미 일치([실측]) |
| 남은 미매칭의 원인은 무엇인가 | **공고 원장에 없는 공고** | 미매칭 88건 표본이 최근 공고, 차수·업종 불일치 아님([실측]) |
| 지금 대량 갱신을 실행했는가 | **미실행** | dry-run 만 수행. 반영은 `--execute` 로 별도 판단 |

---

## 2. 조인 키 정의

`bid_prearng_prices` 는 API 응답에 수요기관명이 없어 `dminstt_nm` 이 비어 있다. 공고 원장에서 세 키로 찾아 채운다.

| 키 | 좌(`bid_prearng_prices`) | 우(`bid_announcements`) | 정규화 |
| --- | --- | --- | --- |
| 공고번호 | `bid_ntce_no` | `bid_ntce_no` | 그대로 |
| 차수 | `bid_ntce_ord` | `bid_ntce_ord` | 숫자만 남겨 `000` 3자리 |
| 업무구분 | `category` | `category` | 그대로 |

- 차수 정규화는 `normalize_ord()` 로 구현했고, SQL 식 `LPAD(COALESCE(CAST(CAST(NULLIF(TRIM(col),'') AS UNSIGNED) AS CHAR),'0'),3,'0')` 과 같은 규칙이다.
- `bid_announcements` 는 `bid_ntce_no` 에 인덱스가 있어 공고번호로 구동된다.
- 채울 값은 수요기관명이 있으면 `dminstt_nm`, 없으면 `ntce_instt_nm` 후보이나 이번 범위는 `dminstt_nm` 만 본다.

---

## 3. 매칭률 측정 (운영 DB 읽기 전용)

| 항목 | 값 |
| --- | ---: |
| 전체 `bid_prearng_prices` | 353,012 |
| 매칭 | 352,924 |
| 미매칭 | 88 |
| **매칭률** | **99.9751%** |
| 수요기관명 확보(매칭 + `dminstt_nm` 비어있지 않음) | 352,924 (99.9751%) |

측정 질의(읽기 전용):

```sql
SELECT COUNT(*) AS total,
       SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS matched
FROM bid_prearng_prices p
LEFT JOIN bid_announcements a
  ON a.bid_ntce_no = p.bid_ntce_no
 AND a.bid_ntce_ord = p.bid_ntce_ord
 AND a.category = p.category;
```

- 차수를 정수로 캐스팅해 정규화한 변형 질의도 매칭 352,924 로 **동일**했다. 두 원장의 차수 표기가 이미 일치한다.
- 매칭된 352,924건은 모두 원장 `dminstt_nm` 이 채워져 있어 그대로 채울 수 있다.

---

## 4. 미매칭 88건 분석

| 항목 | 값 |
| --- | ---: |
| 미매칭 총계 | 88 |
| 업종 | 전부 `Servc` |
| 차수 분포 | `000` 중심, 일부 `001`·`002` |
| 표본 | `R26BK01688309`, `R26BK01689290`, `R26BK01692508` 등 최근 공고 |

- 표본의 공고번호가 `bid_announcements` 에 아예 없다. 차수·업종 불일치가 아니라 **공고 원장 수집 범위 밖 공고**다.
- 즉 조인 키 결함이 아니므로, 이 88건은 발주처 분포 표본에서 빠질 뿐이다(전체의 0.0249%).

### 4.1 원장 건전성 점검([실측])

| 점검 | 값 | 해석 |
| --- | ---: | --- |
| `bid_announcements` 전체 행 | 5,531,220 | - |
| `dminstt_nm` 이 비어 있는 행 | 9 | 사실상 전부 채워져 있음 |
| (공고번호, 차수, category) 중복 그룹 | 0 | 조인 팬아웃 없음 |

- 중복 키가 0 이므로 조인 시 행 수가 늘어나지 않고, 채울 값도 유일하다.

---

## 5. 산출물

| 파일 | 내용 |
| --- | --- |
| `scripts/link_prearng_dminstt.py` | 조회·측정·갱신기. 기본 dry-run, `--execute` 시 갱신 |
| `tests/test_link_prearng_dminstt.py` | 조인 키 정규화·매칭 규칙 픽스처 시험 10건, 운영 DB 미접속 |
| 본 문서 | 매칭률 측정과 미실행 사실 기록 |

### 5.1 실행 결과

```
$ uv run python scripts/link_prearng_dminstt.py
전체 353012건 | 매칭 352924건 | 미매칭 88건 | 매칭률 99.9751% | 수요기관명 확보 352924건(99.9751%)
dry-run: 운영 DB 를 변경하지 않았습니다. 반영하려면 --execute 를 주십시오.
```

- **대량 갱신은 실행하지 않았다.** 352,924건 `UPDATE` 는 10번 과제(사정률 분포 주입) 착수 시점에 사용자 판단으로 반영한다.

---

## 6. 다음 단계

- `--execute` 로 `dminstt_nm` 을 채우면 `institution_sajeong_rate_stats` 의 institution·region scope 재집계가 가능해진다(현재 category 1행뿐).
- 갱신 후 재집계는 `rebuild_institution_sajeong_rate_stats`(창 1,095일) 경로이며 10번 과제 범위다.
- 88건 미매칭은 공고 원장에 추가 수집되면 자연히 해소된다. 억지 매칭(공고명 유사도)은 채택하지 않는다.

---

## 7. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_link_prearng_dminstt.py -q` | 10 passed |
| `uv run python scripts/link_prearng_dminstt.py` | dry-run 정상 출력 |
| `uv run mypy src` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
