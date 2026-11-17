# 홈 웹 피드백 반영 (2026-11-17)

> 작성일: 2026-11-17
> 대상: `src/app/templates/index.html`, `src/app/services/home_summary.py`, `src/app/services/bid_preferences.py`

---

## 1. 요약

| 항목 | 이전 | 이후 |
| --- | --- | --- |
| 상단 지표 | 4개(정확도, 365일, 입찰 중, 내 조건) | 2개(정확도, 365일) |
| 하단 바로가기 | 4개(`data-home-shortcut`) | 삭제 |
| 입찰 중 공고 | 지표 카드 숫자만 | 하단 좌측 패널: 건수 + 마감 구간 막대 |
| 내 조건 입찰 중 | 지표 카드 숫자만 | 하단 우측 패널: 건수 + 마감 임박 5건 + 더보기 |
| 다크 모드 | 홈에 `dark:` 변형 없음 | 배경·글자·테두리·카드 전반 적용 |

히어로와 모델 정확도 카드는 그대로 두었습니다.

---

## 2. 서비스 변경

### 2.1 마감 구간 집계

`home_summary._open_deadline_buckets` 가 입찰 중 공고를 KST 날짜 기준 네 구간으로
GROUP BY 한 번에 셉니다.

| 구간 키 | 라벨 | 조건 |
| --- | --- | --- |
| `today` | 오늘 마감 | `bid_clse_dt < 내일 00:00` |
| `d1_3` | 1~3일 | `내일 00:00 <= bid_clse_dt < 4일 뒤 00:00` |
| `d4_7` | 4~7일 | `4일 뒤 00:00 <= bid_clse_dt < 8일 뒤 00:00` |
| `d8_plus` | 8일 이후 | `8일 뒤 00:00 <= bid_clse_dt` |

구간 질의는 `_count_open_servc` 와 같은 조건 함수 `_open_servc_filters` 를 쓰므로
네 구간 합은 `open_count` 와 항상 같습니다. 구간은 worker 예열 캐시
(`home:summary:servc_counts:v1`)의 `open_deadline_buckets` 키에 함께 저장되고,
요청 경로는 새 집계를 하지 않습니다. 마감 구간이 없는 옛 캐시는 건수만 쓰고
막대 없이 숫자만 보여 줍니다.

### 2.2 내 조건 목록

`bid_preferences.list_open_servc_matching(db, prefs, limit=5, now=None)` 을 추가했습니다.
`count_open_servc_matching` 과 같은 조건 함수 `_open_matching_conditions` 를 공유해
목록과 건수가 서로 다른 공고를 고를 수 없습니다.

- 정렬: `bid_clse_dt` 오름차순(마감 임박 순), 동률은 `id` 오름차순
- 캐시: 건수와 같은 10분 정책, `now` 를 넘기면 캐시 생략
- 반환: 화면과 캐시가 바로 쓸 수 있는 dict 목록(공고 PK, 공고명, 수요기관, 마감 표시, D-day)

### 2.3 더보기 링크의 지역 파라미터

공고 목록의 `region` 파라미터는 `bid_queries.normalize_region_code` 로 정규화한 뒤
`_participation_region_match_clause` 로 참가가능지역을 봅니다. 관심 조건의
`region_code` 도 저장 시 같은 정규화를 거치고 같은 절로 비교됩니다. 즉 두 값은
같은 코드 체계와 같은 의미이므로 더보기 링크에 `region` 도 함께 넘깁니다.

---

## 3. 화면 변경

- 상단 지표 영역: `md:grid-cols-2` 로 정확도와 최근 365일만 배치
- 하단 2열 영역: `lg:grid-cols-2`
  - 좌측 `data-home-panel="open"`: 큰 숫자와 `div` 폭 백분율 막대(새 라이브러리 없음)
  - 우측 `data-home-panel="matching"`: 최대 5건 목록, 6건 이상이면 `lic`·`region` 을 담은 더보기
- `data-home-shortcut` 마크업은 모두 제거
- 다크 모드: `h-card` 는 `harness.css` 가 뒤에 로드되어 유틸리티로 덮을 수 없으므로
  `tailwind.input.css` 에 `.dark .h-card` 규칙을 추가했습니다. 나머지 색은 템플릿에
  `dark:` 변형을 붙였습니다.

---

## 4. 시험

| 시험 | 변경 |
| --- | --- |
| `tests/test_home_feedback_20261117.py` | 신규. 요구 (a)~(f) 고정 |
| `tests/test_home_revamp_20261111.py` | 상단 지표 2개·하단 패널·바로가기 삭제 단정으로 수정, `test_home_renders_top_metrics_and_bottom_panels` 로 이름 변경 |
| `tests/test_home_counts_fix_20261114.py` | 예열 반환·캐시 값에 `open_deadline_buckets` 추가 반영 |
| `tests/test_ui_ssr.py` | 홈 렌더 단정을 새 구조로 수정 |
| `tests/test_home_list_parity.py` | `test_index_page_renders_one_screen_home` 의 홈 렌더 단정만 새 구조로 수정(코디네이터 승인) |
| `tests/test_responsive_templates.py` | 변경 없음 |
| `tests/test_scheduled_tasks.py` | 변경 없음 |

---

## 5. 범위 밖 시험

`tests/test_home_list_parity.py::test_index_page_renders_one_screen_home` 은 이전 홈
구조(지표 4개·바로가기 4개)를 단정해 실패했습니다. 이 파일은 처음에는 쓰기 허용
범위 밖이었고, 코디네이터 승인 뒤 홈 렌더 단정 부분만 새 구조로 고쳤습니다.
다른 시험은 건드리지 않았습니다.
