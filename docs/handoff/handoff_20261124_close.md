# 2026-11-24 세션 인수인계

> **작성일**: 2026-11-24
> **최종 main**: 이 문서를 담은 병합 커밋(직전 `64577664`)
> **Orca Run**: `run_c1863d8691a3`
> **상태**: 빌더 1대 작업 중(TDD 1단계, 워크트리 `gate11`), Docker 5개 기동 중(app·worker 는 `64577664` 반영 재시작 완료)
> **운영 Meilisearch**: `bid_records` rankingRules = words, sort, typo, proximity, attribute, exactness
> **운영 DB 리비전**: `b8d9e0f1a2b3` (head)

---

## 0. 다음 세션 첫 할 일

| 순서 | 할 일 | 근거 |
| --- | --- | --- |
| 1 | TDD 1단계 Task `task_d0bb1ea117f6`(워크트리 `gate11`) 상태 확인. 끝났으면 리뷰 → 소급 결과 재확인 → 병합(사용자 승인 완료) | 5장 |
| 2 | `6ef2b7e6`, `64577664`, 이 문서 병합 커밋의 CI 결과 확인 | 7장 |
| 3 | 사용자 브라우저 확인: 메인 화면 속도, 키워드 검색 결과 최신순, 다크 모드 hover 색 변화 4곳 | 2장, 4장, 3장 |
| 4 | Docker Desktop 메모리 증설 여부를 사용자와 확인 | 4장 |
| 5 | Docker 가 내려가 있으면 `docker compose up -d` 후 준비 상태 확인 | `.agents/skills/web-platform-launch/SKILL.md` |

---

## 1. 이번 세션 병합 (모두 main 푸시)

| 영역 | 병합 커밋 | 빌더 커밋 | 결과 |
| --- | --- | --- | --- |
| KB 정상 색인 뒤 잔존 `result_` 문서 정리 | `3c070786` | `93f5a523` | 공고 원천 색인 성공 뒤에만 삭제. 리뷰 pass |
| Bootstrap 제거 뒤 `dark:*!` 접미사 정리 | `bfbda343` | `95c9873e` | 53곳 `!` 제거, `.dark .h-card` 와 겨루는 17곳 유지. 리뷰 pass |
| KB 수집일 폴백 건수 질의 상한 집계 | `eca7419c` | `7b73b917`, `35d7ab06` | `limit+1` 에서 세기 중단, 결과 동일. 리뷰 코드 결함 없음, 문서 서술은 재작업으로 정정 |
| 메인 관심 조건 집계 캐시 예열과 인덱스 | `a419f41d` | `cc695ca0`, `24a566b0` | 요청 경로는 캐시만 읽음, `ix_bid_ann_cat_clse` 운영 적용, G1 기준선 재생성. 리뷰 pass |
| 2026-11-24 세션 인수인계 | `f341b73d` | `56cc27ed` | 이 문서 초판, CURRENT_STATE source_commit 갱신 |
| 목록 검색 결과 Redis 300초 캐시 | `6ef2b7e6` | `d3b53d6d` | 검색 id 목록·다음 페이지 여부만 캐시, 행은 매번 DB. 리뷰 pass |
| Meilisearch 순위 규칙 sort 앞당김 | `64577664` | `4b654d1c`, `2094e63c` | 운영 색인 적용(재색인 없음), 전후 측정 기록. 리뷰 pass |

빌더는 OpenCode Go `deepseek-v4.1-flash`, 리뷰어는 OpenCode Go `glm-5.3-flash` 였다. 빌더 보고서 형식 문제로
빌더 Capsule 게이트 6 이 실패한 3건(`3c070786`, `bfbda343`, `eca7419c`)과 운영 DB 적용이 필요했던
`a419f41d` 는 코디네이터 Capsule strict 게이트와 전량 시험 증거로 병합했다. 브랜치마다
`refs/backup/<이름>-20261124` 를 남겼고 보고서는 `.orca/reports/` 에 있다.

---

## 2. 메인 화면 지연 원인과 조치

| 항목 | 내용 |
| --- | --- |
| 증상 | 사용자 브라우저에서 메인 렌더링이 매우 느렸다 |
| 원인 | 관심 업종·지역 입찰 중 건수·목록 집계가 캐시(10분) 만료 때 요청 안에서 즉시 실행됐다. `bid_clse_dt` 선두 인덱스가 없어 약 102만 행을 검사했고, Docker 기동 직후 차가운 버퍼 풀에서 평균 49.5초, 최대 60.5초(performance_schema 실측) |
| 겹친 요인 | 같은 시각 다른 워커의 공고 테이블 측정 질의(최대 69초) |
| 조치 1 | 요청 경로는 캐시만 읽고, 없으면 '집계 중'. worker 예열(10분 주기)이 신선 키(10분)와 보관 키(24시간)를 채운다 |
| 조치 2 | 인덱스 `ix_bid_ann_cat_clse(category, bid_clse_dt)` 운영 적용(43초, 사용자 승인). 서울 지역 조건 건수 질의 0.97초, 0.29초 |
| 재시작 확인 | 예열 0.55초, 저장된 관심 조건 2개 예열 성공(실패 0) |

---

## 3. 운영 메모

| 항목 | 내용 |
| --- | --- |
| 관심 조건 저장 직후 | 다음 예열까지 최대 10분 '집계 중' 이 보인다. 저장 직후 arq 예열은 범위 밖이라 넣지 않았다 |
| 다크 모드 hover | `base.html` 253·259·265행, `result_detail.html` 119행은 `!` 제거로 다크 모드 hover 색이 실제로 적용된다. 의도된 변화로 판단했다 |
| Meilisearch 설정 경로 | 1.14 는 `PATCH /indexes/<uid>/settings/ranking-rules` 를 받지 않는다. `PATCH /indexes/<uid>/settings` 에 `{"rankingRules": [...]}` 를 보낸다. `sync_search_index` 가 `configure_index` 로 같은 값을 다시 보낸다 |
| 워크트리 orca.capsule | 리뷰 뒤 같은 워크트리에서 코디네이터가 커밋하려면 `git config --worktree orca.capsule` 을 코디네이터 Capsule 로 바꿔야 한다(리뷰어 Capsule 은 쓰기 0이라 거부) |
| Docker 로그 시각 | `docker logs --timestamps` 시각이 실제보다 4일 늦게 찍혀 `--since` 필터가 동작하지 않았다. 로그는 줄 범위로 잘라 읽었다 |
| Orca 저장소 등록 | Orca 에는 옛 경로(`lanhchain_ai_vision`)로 등록돼 있어 `orca worktree create --repo path:` 가 `repo_not_found`. `--repo id:5e5adcaa-f18e-4582-adf8-2f0df100f331` 로 지정 |
| 워크트리 강제 삭제 | `orca worktree rm --force` 를 다른 명령과 묶으면 자동 권한이 거부했다. 미커밋 변경 0 확인 뒤 `--force` 없이 단독 실행하면 통과 |
| 빌더 보고 신뢰 | kb-count-perf 빌더가 'MySQL 재시작' 을 보고했으나 Uptime 연속·재시작 0회로 사실이 아니었다. 516초 질의 끊김(2013)의 원인은 미확인 |

---

## 4. 낙찰 결과·검색 지연 원인과 조치

| 항목 | 내용 |
| --- | --- |
| 증상 | 낙찰 결과 화면 822ms(전량 시험과 겹친 측정), 키워드 검색 조합은 1.0~2.2초 |
| 분해 | `list_results` 시간의 85~98% 가 Meilisearch 검색, id 로 행을 읽는 DB 조회는 9~12ms |
| 원인 1 | 처음 검색의 디스크 읽기. 색인 23.7GB(843만 건, 공고·낙찰 한 색인)가 Docker VM 메모리 17.5GB(Meilisearch 7.4GB)에 다 올라가지 못함. 적용 전 1회차 13~1,417ms, 2·3회차 2~81ms |
| 원인 2 | 기본 순위 규칙이 sort 를 proximity·attribute 뒤에 두어 키워드에 걸린 5만~14만 후보 전부에 근접도를 계산 |
| 조치 A | rankingRules 를 words, sort, typo, proximity, attribute, exactness 로 변경. 임시 색인(3만 건) 실측으로 재색인 없음 확인(1.4ms 대 문서 추가 4,023ms), 운영 적용 task 9.9ms. 2·3회차 중앙값 합 낙찰 127.0 -> 81.5ms(-36%), 공고 333.5 -> 127.5ms(-62%), 추정 총건수 불변, 결과 순서는 최신순 우선으로 바뀜(사용자 승인) |
| 조치 E | `_search_index_page` 결과(id, has_next)를 Redis `search_ids:v1:` 키로 300초 캐시. 실패 결과는 캐시하지 않음 |
| 남은 대책 | 처음 검색 지연은 Docker Desktop 메모리 증설이 근본 대책(사용자 설정). 색인 분리는 보류 |
| 상세 | `docs/analysis/meili_ranking_sort_first_20261124.md`, 측정 원본 `.orca/reports/meili_ranking_{before,after}_20261124.json`(gitignore 대상) |

---

## 5. TDD 도입 검토

| 항목 | 내용 |
| --- | --- |
| 현재 | TDD 규정 없음. 기능과 시험을 한 커밋에 내고 게이트(커버리지 80%, Level 1, 전량 증거)로 강제하는 '시험 동반' 방식 |
| 결정 | 정통 TDD(커밋 분리) 대신 '실패→통과 증명' 게이트 11 을 단계적으로 도입. 1단계 진행 승인 |
| 1단계 | 게이트 11 경고 모드 구현(새·수정 시험이 기준 코드에서 단언 실패, 브랜치에서 통과하는지 기록, 병합 차단 없음)과 오늘 병합 6건 소급 실행 기준선. Task `task_d0bb1ea117f6`, 빌더 OpenCode Go deepseek-v4.1-flash max |
| 2~4단계 | Capsule `tdd` 항목·고지문·리뷰 체크리스트(2), 2주 경고 모드 운영(3), feat·fix 차단 전환(4, 사용자 결정) |
| 면제 | 리팩터링·문서·CSS(계산 스타일 대조)·DB 마이그레이션(G1 게이트)·성능(측정 보고서)·조사 Task |

---

## 6. 남은 과업

| 구분 | 내용 | 근거 |
| --- | --- | --- |
| 후속 후보 | 관심 조건 저장 직후 그 조건만 arq 로 예열 | 3장 1행 |
| 사용자 결정 | Docker Desktop 메모리 증설(처음 검색 지연의 근본 대책) | 4장 |
| 보류 | Meilisearch 색인 분리(공고·낙찰), 검색 상한 searchCutoffMs | 4장 |
| 후속 후보 | KB 수집일 폴백 경로의 콜드 69초(상한 520,001건까지 최신 차수 판정) | `docs/analysis/kb_collected_count_perf_20261124.md` |
| 보류 | 압축·정적 캐시(M1·M2), 웹 워커 증설(H4), 부하 시험(M7), 지표·알람(M8) | 운영 서버 확정 뒤 |

---

## 7. CI 결과 (이 문서 작성 시점)

| 커밋 | 결과 |
| --- | --- |
| `3c070786`, `bfbda343`, `eca7419c`, `a419f41d`, `f341b73d` | 성공 |
| `6ef2b7e6`, `64577664` | 실행 중 |
