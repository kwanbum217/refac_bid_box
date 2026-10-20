# 핸드오프 인수인계 — 마이페이지, 공고 상세 지연 해소, 충남 1235 원문 재검증

> **작성일**: 2026-10-09
> **작성**: Claude 코디네이터 (Orca Run `run_1ef4bc53249a`)
> **기준 커밋**: `fe3cdfd9` (이 문서가 들어가는 작업 커밋의 부모)
> **직전 인수인계**: [handoff_20261007_ui_qual_close.md](handoff_20261007_ui_qual_close.md)
> **원문 검토 보고서**: [qual_chungnam_2026_1235_hwpx_review_20261009.md](../analysis/qual_chungnam_2026_1235_hwpx_review_20261009.md)

---

## 0. 다음 세션이 가장 먼저 할 일

개발 스택은 이 세션 종료 때 `docker compose down` 으로 내렸다. 볼륨은 지우지 않았다. 컴퓨터를 켠 뒤 Docker Desktop 을 띄우고 `docker compose up -d` 로 다시 올린다. 소켓이 없으면 `open -a Docker` 후 `docker info` 가 될 때까지 기다린다.

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 인수인계 병합 커밋의 CI 가 원격 `main` 에서 녹색인지 확인 | 없음 |
| 2 | 로그인 상태로 브라우저에서 마이페이지와 공고 상세를 한 번 열어 화면 확인 | 스택 기동 |
| 3 | 충남 별표 2·3·4 등록 여부를 사용자에게 받기(6절) | 사용자 결정. 승인 전 `evaluation_rules.py` 수정 금지 |

---

## 1. 이 세션에서 병합한 것

네 건 모두 `--no-ff` 병합, 원격 반영, CI 통과를 확인했다.

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| M3 낙찰 기관·개찰일시 인덱스 | `a9d28dc6` | `bid_results` `ix_bid_results_inst_dt (dminstt_nm, rl_openg_dt)`, 마이그레이션 `e4f5a6b7c8d9`, G1 기준선 갱신 | 빌더 cmd, 리뷰 muse pass, 전량 6,808 통과. CI Windows 잡이 외부 HTTP 500 으로 1회 실패 후 재실행 통과 |
| M2 마이페이지 | `358d0645` | `GET /accounts/mypage/` 조회 전용. 사이드바 사용자 영역·헤더 진입 링크. `me_profile`·`_serialize` 재사용 | 리뷰 pass, 전량 6,808 통과. 템플릿 개수 13, OpenAPI 기준선 경로 53·작업 60 갱신 |
| M4 유사 공고 최신순 | `1f7b20ee` | 유사 공고 `ORDER BY bid_ntce_dt DESC, id DESC`, `bid_announcements` `ix_bid_ann_inst_cat_dt (dminstt_nm, category, bid_ntce_dt)`, 마이그레이션 `f5a6b7c8d9e0`, G1 기준선 갱신 | 리뷰 pass, 전량 6,815 통과 |
| M1 충남 1235 원문 재검증 | `fe3cdfd9` | 검토 보고서 신규, 원 문서 정정 3건, 현황판 `source_commit` 갱신 | 리뷰가 빌더 정정 1건을 fail 판정, 코디네이터가 `9a35c150` 으로 바로잡음 |

운영 DB 는 현재 alembic head `f5a6b7c8d9e0` 이다. 두 인덱스는 사용자 승인과 리뷰 통과 뒤 적용했다(13초, 122초).

---

## 2. 공고 상세 지연 실측

원인은 `src/app/services/bid_queries.py` `get_announcement_detail` 의 기관 과거 낙찰 5건 조회였다. 기관 등치 단일 인덱스로 그 기관 낙찰 행 전부를 읽고 filesort 했다.

| 측정 | 적용 전 | 적용 후 |
| --- | --- | --- |
| 공고 상세 GET, 처음 여는 공고 | 4.6 / 9.3 / 29.2초 | 0.031~0.098초 (기관 6곳) |
| 기관 과거 낙찰 5건 쿼리, 콜드 | 7.329초 (경기도 화성시) | 4~12ms, Backward index scan |
| 유사 공고 5건, 최신순 정렬 | 정렬 없음(공고명순). 정렬만 넣으면 일자 인덱스 역스캔 4,655행 | 4~35ms, 6~7행 |

측정은 앱을 프로세스 안에서 띄운 TestClient 기준이며 브라우저 렌더링은 포함하지 않는다. 페이지 로드 뒤 호출되는 `POST /api/v1/predictions/predict-price` 는 0.05~1.3초로 이번 범위에서 손대지 않았다.

---

## 3. 충남 2026-1235 원문 재검증

`0cbd7145` 의 결론 세 가지는 유지된다. 최저평점 조항 원문 부재, 배점(5억)·산식(고시금액) 축 분리, 낙찰하한율 짝 80.495%/84.245%.

원 문서 정정은 개정판 `제7절 그밖에 사항` 추가, `15.03` 을 `15.025` 로, 원시 grep 방법 서술 세 가지다. 빌더는 세 번째를 "section0.xml 에 평탄화 사본 문단이 있다" 고 적었으나 틀렸다. 인덱스 1 문단은 대비표를 품은 래퍼라 `iter()` 계수가 이중이 될 뿐이고, 원시 grep 합계(4/3/5)는 정확하다. 열 귀속만 `hp:cellAddr` `colAddr` 로 판정한다.

---

## 4. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| 운영 DB `alembic upgrade` 는 승인 없으면 Modify Shared Resources, 리뷰 전이면 Blind Apply 로 막힌다 | 승인 받고 리뷰 pass 뒤 적용 |
| G1 기준선은 빌더가 손으로 고치면 안 된다 | 빌더 브랜치 위 코디네이터 브랜치에서 `verify_migration.py --generate-schema-baseline` 으로 재생성 |
| strict 증거만 남기면 병합 훅이 전량 시험 증거 부재로 거부 | `premerge_full_suite_gate.py --record` 를 병합 대상 HEAD 에서 실행 |
| 템플릿을 바꾼 브랜치의 strict 게이트 3 이 `css_build`, `css_diff` 미검증으로 실패 | `--verify 'npm run build:css'`, `--verify 'git diff --exit-code -- src/app/static/css/tailwind.css'` |
| 증거 파일 두 개가 저장소 공용 | 병합은 한 건씩 기록 후 병합 |
| 옛 main 위 브랜치에 최신 `source_commit` 을 적으면 이력에서 못 찾는다 | 코디네이터 브랜치에 main 을 먼저 병합 |
| `.gitignore` 의 `node_modules/` 는 심볼릭 링크를 잡지 못한다 | 공용 `info/exclude` 에 `/node_modules` 추가 |

---

## 5. 하지 않은 것

- 회원정보 수정 기능은 만들지 않았다. 마이페이지는 조회 전용이다.
- `predict-price` 지연(0.05~1.3초)은 손대지 않았다.
- 충남 별표 2·3·4 를 `evaluation_rules.py` 에 등록하지 않았다.
- 주 저장소 원래 브랜치 `kwanbum217/quant-score-input` 은 이미 병합된 상태로 남겨 두었다. 삭제하지 않았다.

---

## 6. 사용자 결정 대기

| 항목 | 내용 |
| --- | --- |
| 충남 별표 2·3·4 등록 | 배점=5억, 계수=고시금액의 의도적 분리가 원문으로 확정됐다. 규칙 7·8 하의 등록·미등록 정책 결정 |
| 충남 별표 5 구간별 하한율 | 5억 미만 87.995% / 이상 80.495% 이중 산식은 코드에 이미 구간값으로 들어가 있다. 별도 조치 필요 여부 |
| HWPX 추출물 등록 | 줄 단위 인용이 필요하면 HWPX 기반 추출물을 `derived_from` 으로 등록 |

---

## 7. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_1ef4bc53249a` | Task 8건(빌더 4, 리뷰어 4) 모두 `completed`, 워커 터미널 전부 회수 |
| 워크트리 | 주 저장소만 남음. 이번 작업 브랜치 전부 삭제 |
| 배경 프로세스 | 상시 감시기 `orca_worker_watch.py --watch`, 자동 승인 감시기 모두 종료 |
| Docker | `docker compose down` (볼륨 유지) |
