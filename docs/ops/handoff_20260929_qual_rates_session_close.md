# 인수인계: 2026-09-29 적격심사 기준비율 세션 종료

> **작성일**: 2026-09-29
> **Run**: `run_e751823d2424`
> **기준 커밋**: `main` `d2cdf4d2` 위에 빌더 `8c0d1095` 를 `--no-ff` 로 병합
> **인수 대상**: 다음 코디네이터
> **source_commit**: 이 병합 커밋에서 `d2cdf4d2` 로 갱신

---

## 0. 다음 세션 첫 작업

이 세션 끝에서 프로젝트 컨테이너를 멈췄습니다. 데이터를 지우지 않았습니다.
사용자가 환경을 올리라고 하면 볼륨 없이 기동합니다.

```sh
docker compose up -d db redis meilisearch app worker
```

**새 구현을 시작하지 마십시오.** 아래 두 결정은 사용자 답이 오기 전입니다.

1. Meilisearch 재색인. 하면 개정 전 공고가 적격심사 분석 필터에 들어갑니다.
2. 기관별, 지역별, 물품 산식 구현. 자료 폴더의 표는 대조표이고 확정 레지스트리가 아닙니다.

---

## 1. 이 세션이 끝낸 것

| 항목 | 결과 |
| --- | --- |
| Windows 명령 실재성 테스트 | `tests/test_orca_command_reality_gate.py` 만 수정. 병합 `d2cdf4d2`, `origin/main` 반영 |
| 일반용역 기준비율 | 빌더 `8c0d1095`. 독립 리뷰 pass. Level 1 11개 통과. 전량 5807 passed, 40 skipped, 3 deselected |

기준비율 변경 파일은 네 개입니다.

- `src/app/services/evaluation_rules.py`
- `tests/test_evaluation_rules_pre.py`
- `tests/test_evaluations_api.py`
- `tests/test_evaluations_realuse_scenarios.py`

가격점수 산식, 개정 전 두 벌, 기술용역 규칙, DB 스키마, Meilisearch 는 그대로입니다.

---

## 2. 고시 원문 수치

정본은 조달청 게시판 HWPX 입니다.

- 제2026-260호: https://www.pps.go.kr/kor/bbs/view.do?key=00030&bbsSn=2605220029
  시행 2026-05-26, 그날 이후 최초 공고
- 제2026-390호: https://www.pps.go.kr/kor/bbs/view.do?key=00030&bbsSn=2607240033
  시행 2026-07-27, 그날 이후 최초 공고. 파일명의 7.24 는 부칙 시행일과 다릅니다

| 구간 | 시설 | 보험 | 여객, 소프트웨어 대상 | 그 외 별표 |
| --- | ---: | ---: | ---: | ---: |
| 2026-05-26 이상 2026-07-27 미만 | 0.93 / 89.995 | 0.88 / 47.995 | 0.91 / 87.995 | 0.90 |
| 2026-07-27 이후, 공고일 없음 | 0.93 / 89.995, 식별자 ATTACH_01 유지 | 0.88 / 47.995 | 0.93 / 89.995, 식별자 ATTACH_03 와 ATTACH_04 | 0.90 |

공고일 2026-07-26 은 260호 벌입니다. 경계는 포함입니다.
가격점수는 `P = B - k * abs(기준비율 - x) * 100` 이고 `k` 는 사용자 입력입니다.

---

## 3. 조율 기록

| 항목 | 값 |
| --- | --- |
| 빌더 Task | `task_3ef843c585ad`, 모델 `deepseek/deepseek-v4.1-flash` |
| 리뷰 Task | `task_baed4f00462f`, 모델 `opencode/muse-spark-1.3-contributor-free` |
| 리뷰 판정 | 네 항목 모두 결함 없음. `rates_match_notice`, `pre_regimes_untouched`, `no_reindex_or_schema`, `routing_boundary` |
| 워크트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-qual-rates` |
| 이전 테스트 수정 워크트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-i1` |

빌더 완료 보고가 창 식별자 불일치로 한 번 거절된 뒤, 같은 내용의 완료 보고가 도착했습니다. 거절은 코드 결함이 아닙니다. 커밋 `8c0d1095` 를 정본으로 봤습니다.

쓰지 말 것: `run_b406a154bbad` 은 consumer_fenced. `run_3c767f3e99f7` 은 테스트 수정이 끝난 Run 입니다.

---

## 4. 시작하지 않은 것

- 검색 색인 재구축
- 기관별, 시도별 입찰가격 산식
- 상한 절삭(플리어)
- `ATTACH_12` 부터 `ATTACH_14` 낙찰하한율의 별표 출처 보강
- `EvaluationRule` 에 계수 `k` 를 넣는 변경

지방계약예규의 용역 기준비율은 규모 구간별 88% 이고, 시도별로 산식이 갈리지 않습니다.
물품은 가격 산식이 아니라 가격을 뺀 배점을 10% 안에서 조정합니다.
자료 폴더의 1,065행 대조표는 기관마다 숫자가 다르지만, 판정이 미확인인 행이 다수입니다.
