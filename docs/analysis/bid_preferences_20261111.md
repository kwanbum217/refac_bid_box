# 회원 관심 업종·지역 저장과 매칭 공고 수 (2026-11-11)

## 목적
새 메인 페이지의 '사용자에 해당되는 입찰 건수' 를 그리려면 회원별 관심 조건이 필요합니다.
기존 계정·회사 프로필 테이블은 바꾸지 않고 신규 테이블 `account_bid_preferences` 만 추가합니다(G1).

| 항목 | 정의 |
| --- | --- |
| `user_id` | `accounts_customuser.id` 참조, 사용자당 1행(UNIQUE), CASCADE |
| `license_codes` | 관심 업종(면허) 코드 목록(JSON). 공고 탐색 업종 필터와 같은 코드 정의 |
| `region_code` | 관심 지역 코드, 기본 빈 문자열. 공고 탐색 지역 필터와 같은 코드 정의 |

콜레이션은 `utf8mb4_unicode_ci` 를 명시합니다. 마이그레이션 `d6e7f8a9b0c1` 의
down_revision 은 `c5d6e7f8a9b0` 이고, 테이블이 이미 있으면 건너뜁니다.

## 셈 조건
`src/app/services/bid_preferences.py` 의 `count_open_servc_matching` 이 셉니다.

| 조건 | 값 |
| --- | --- |
| 분야 | `category = 'Servc'` |
| 마감 | `bid_clse_dt >= now` (KST 현재 시각) |
| 차수 | 최신 차수만(`bid_queries.latest_announcement_filter`) |
| 업종 | 관심 코드 중 하나라도 `bid_announcement_license_limits` 참가자격에 포함 |
| 지역 | `bid_announcement_participation_regions` 가 관심 지역과 일치 |
| 스캔 범위 | `bid_ntce_dt >= now - 90일` (ix_bid_ann_cat_dt) |

업종·지역이 모두 비면 0 을 돌려주고, 호출자는 `BidPreferenceView.is_empty` 로 메인에
입력 안내를 띄웁니다. 결과는 조건별로 10분 캐시합니다(기준 시각을 넘기면 캐시 생략).

## 공고 탐색 필터와의 정합 근거
업종·지역 코드 정규화는 `bid_queries.normalize_license_codes` 와 `normalize_region_code`
를 그대로 씁니다. 지역 조항은 `_participation_region_match_clause` 를 import 해 재사용하고,
업종 조항은 `list_announcements` 안에 인라인이라 같은 식을 서비스에 두었습니다.
`tests/test_bid_preferences_20261111.py` 가 `list_announcements` 결과와 대조합니다.

## 마이페이지
수정 화면은 공고 탐색 `list.html` 과 같은 그룹 체크박스·지역 select 를 쓰고, 저장은
회사 프로필 저장과 같은 트랜잭션에서 `save_bid_preferences` 로 합니다. 마이페이지는
저장된 업종 그룹 라벨과 지역 라벨을 읽기 전용으로 보여 줍니다.
