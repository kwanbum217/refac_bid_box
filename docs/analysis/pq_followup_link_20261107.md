# 비예가(PQ) 공고의 후속 가격입찰 공고 연결 구현과 회귀 측정

> **작성일**: 2026-11-07
> **작업**: Orca Task `task_3917fae3e979` (builder, `run_d3fa8d51ba74`). 조사 문서 `docs/analysis/pq_followup_match_20261107.md` 5절 결정을 코디네이터 권장안(사용자 승인)대로 구현했다. 그 문서는 `kwanbum217/pq-followup` 브랜치에 있어 이 워크트리에는 없고, 원문은 Task Capsule 디렉터리에 있다.
> **정본 사양**: Task Capsule (`ORCA_TASK_CAPSULE_V2`)
> **선행 문서**: `docs/analysis/pq_followup_match_20261107.md` 5절 결정 1~6, [non_pred_price_211_20261107.md](non_pred_price_211_20261107.md) 5절 결정 5
> **범위**: 공고 상세 한 화면. DB 스키마·행 수·계산 규칙·원장은 바꾸지 않았다.

---

## 1. 구현 요약

비예가(`NON_PRED_PRICE`)로 계산이 차단되는 공고의 차단 카드 아래에 `후속 가격입찰 공고` 목록을 붙였다.

| 항목 | 결정 | 구현 |
| --- | --- | --- |
| 연결 구현 여부 | 구현(B, 링크만) | 상세 화면 목록. 계산·판정에는 쓰지 않는다 |
| 매칭 키 | `raw_data.bfSpecRgstNo` 정확 일치 하나만 | 이름·기관·추정가격 보조 규칙 없음 |
| 1:N 분할 발주 | 모두 목록으로 표시 | 후보를 전부 돌려준다. 대표 1건 선택 없음 |
| 기초금액 | 노출하지 않음 | 목록에 금액 필드 자체를 넣지 않는다 |
| 예정가격 | 노출하지 않음 | 후속 공고 상세에서 각자 본다 |
| 링크 테이블·배치 | 만들지 않음 | 요청 시점 조회만 한다 |
| 매칭 실패 | 현행 유지 | 목록이 비면 안내 한 줄만 보여 준다 |

### 1.1 후보 질의

`raw_data` JSON 을 SQL 에서 `LIKE`·`JSON_EXTRACT` 로 전체 검색하지 않는다. 다음 조건으로 후보를 좁힌 뒤 파이썬에서 `bfSpecRgstNo` 를 비교한다.

- 현재 공고와 같은 `dminstt_nm`·`category`
- `bid_ntce_dt` 가 현재 공고일 이상, 365일 미만
- `similar_announcement_latest_filter` 로 같은 공고번호·분야의 최신 차수만
- 자기 자신 제외, 최대 300건 (공고일 내림차순)

파이썬 필터는 두 가지다.

1. 현재 공고의 `raw_data.bfSpecRgstNo` 가 비어 있지 않다.
2. 후보의 `raw_data.bfSpecRgstNo` 가 현재 값과 정확히 같다.

비예가 차단이 아닌 공고에서는 이 질의를 실행하지 않는다.

### 1.2 화면

- 위치: AI 투찰 금액 분석기의 `계산 차단` 카드 안, 공고 공개값 아래
- 소제목: `후속 가격입찰 공고`
- 목록 항목: 공고명(상세 링크), 공고일, 마감일
- 목록이 비면 `아직 연결된 후속 공고가 없습니다` 한 줄
- 기초금액·예정가격·계산값은 넣지 않는다

---

## 2. 실측

운영 DB 에 `SET SESSION TRANSACTION READ ONLY` 로 접속해 `get_announcement_detail` 을 대상별 3회 실행하고 중앙값을 기록했다. 수정 전은 이 Task 의 코드 변경을 적용하기 전 같은 스크립트 실행값이다.

| 대상 | 구분 | 후속 건수 | 수정 전 중앙값(ms) | 수정 후 중앙값(ms) | 증감(ms) |
| --- | --- | ---: | ---: | ---: | ---: |
| R26BK01394277 | 비예가 PQ(1:N 3건) | 3 | 57.8 | 64.9 | +7.1 |
| R26BK01441376 | 비예가 PQ | 1 | 36.8 | 34.9 | -1.9 |
| R26BK01676127 | 비예가 PQ | 1 | 33.2 | 32.3 | -0.9 |
| R26BK01816026 | 일반 공고 | 0 | 75.8 | 37.0 | -38.8 |
| R26BK01816025 | 일반 공고 | 0 | 35.2 | 41.4 | +6.2 |

비예가 공고의 증가는 최대 7.1ms 로, 차단 기준 200ms 를 넘지 않는다. 일반 공고는 후보 질의를 실행하지 않으므로 증감은 측정 잡음 범위다.

매칭 결과는 조사 문서 2.3절과 일치한다.

| PQ 공고 | 후속 공고 | 비고 |
| --- | --- | --- |
| R26BK01394277 | R26BK01477406, R26BK01477544, R26BK01477556 | 3건 분할 발주 전부 표시 |
| R26BK01441376 | R26BK01529402 | 1:1 |
| R26BK01676127 | R26BK01787350 | 1:1 |

### 2.1 후보 질의 EXPLAIN

```text
id | select_type | table               | type  | key                      | key_len | rows | Extra
---+-------------+---------------------+-------+--------------------------+---------+------+--------------------------------
1  | SIMPLE      | bid_announcements   | range | ix_bid_ann_inst_cat_dt   | 854     | 311  | Using index condition; Backward index scan
1  | SIMPLE      | bid_announcements_1 | ref   | bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq | 202 | 1 | Using where; Not exists
```

바깥 질의는 `(dminstt_nm, category, bid_ntce_dt)` 인덱스 범위 스캔이고 `type` 은 `ALL` 이 아니다. 안쪽 `NOT EXISTS` 는 공고번호·차수 유니크 인덱스로 1행만 본다.

---

## 3. 변경 파일

| 파일 | 변경 |
| --- | --- |
| `src/app/services/bid_queries.py` | `is_non_pred_price_blocked`, `get_followup_announcements` 추가. `get_announcement_detail` 이 `followup_bids` 를 함께 돌려준다 |
| `src/app/api/ui.py` | 상세 화면 컨텍스트에 `show_followup_bids` 를 넣는다 |
| `src/app/templates/bids/detail.html` | 차단 카드 안 `후속 가격입찰 공고` 목록과 빈 목록 안내 |
| `tests/test_pq_followup_link_20261107.py` | (a)~(e) 시험 추가 |
| `docs/analysis/pq_followup_link_20261107.md` | 이 문서 |

`src/app/api/v1/bids.py`, `src/app/schemas/bids.py`, `src/app/static/css/tailwind.css` 는 손대지 않았다.

- REST 상세 응답(`GET /api/v1/bids/{pk}`)은 이번 범위 밖이다. 응답 키 집합을 단언하는 기존 시험(`tests/test_backend_rest_fixes.py`)이 있어 필드를 더하지 않았다. 화면(SSR)만 후속 공고 목록을 보여 준다.
- 새 tailwind 클래스를 쓰지 않아 `tailwind.css` 는 바뀌지 않았다(`git diff --exit-code` 통과).

---

## 4. 검증

| 항목 | 결과 |
| --- | --- |
| `uv run pytest tests/test_pq_followup_link_20261107.py tests/test_npp_message_20261107.py tests/test_detail_recommendations.py -q` | 통과 |
| `uv run mypy src` | 통과 |
| `npm ci` / `npm run build:css` | 통과, `tailwind.css` 변경 없음 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
