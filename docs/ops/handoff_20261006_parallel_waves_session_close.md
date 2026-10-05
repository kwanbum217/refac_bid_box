# 핸드오프 인수인계 — 낙찰하한율 원문 정정·조달청 평탄·지방계약 입력 화면 병렬 세션

> **작성일**: 2026-10-06
> **작성**: Claude 코디네이터 (run_c6cbadfe4a2b)
> **기준 커밋**: `f51b5460` (main, origin 동기화. 이 문서는 그 다음 병합으로 들어감)
> **직전 인수인계**: [handoff_20261005_band_lwlt_session_close.md](handoff_20261005_band_lwlt_session_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

직전 인수인계 0장의 "기존 LOCAL 36개 규칙 구간별 하한율 점검" 은 이 세션에서 끝났습니다(`c198bbe6`, 1장). 이 문서를 처음 쓸 때 0장에 둔 결정 3건은 같은 세션에 사용자가 결정해 처리했습니다(2026-10-06).

| 항목 | 결정 | 처리 |
| --- | --- | --- |
| GENERAL 6개 규칙(인천·제주·강원·경북 04·경남·서울) 공고 실측 하한율 | 10억 미만 3개 구간만 반영(87.745 / 86.745 / 85.495), 10억 이상 보류 | 브랜치 `kwanbum217/g1-lwlt-measured` 커밋 `b021c15b`, 리뷰 pass, 이 문서 병합 직후 병합 |
| 단순노무 5개, 경북 SW·폐기물 | 보류 유지(공고 표본 0~2건) | 변경 없음 |
| 사용자 B·k 입력 시 조달청 평탄 표시 불일치 | 표시만 실제 적용과 일치 | `4ada3ca0` 병합 |

다음 세션의 남은 결정은 GENERAL 6개 규칙의 10억 이상 구간입니다. 공고 실측이 서울·인천은 77.995/72.995, 그 외는 87.745 로 갈려([local_lwlt_announcement_measure_20261005.md](../analysis/local_lwlt_announcement_measure_20261005.md) 6.1절) 시·도별 값으로 넣을지, 원문 확보까지 보류할지 정해야 합니다.

세션 시작 시 확인합니다.

```bash
docker compose ps
gh run list --branch main --limit 6
```

---

## 1. 이번 세션에서 main 에 병합된 것

| 커밋 | 내용 |
| --- | --- |
| `f379a6b4` | 평탄 하향 단절 처리(평탄 점수 < 필요점수면 통과 상한 절단), `/predictions` 규모 구간·세종 평탄 끝단 시험 |
| `5ca61b48` | `/predictions` 규모 구간 대체 안내(`uncertainty_warning`), 구간별 낙찰하한율을 `/evaluations` 와 일치 |
| `08d1bbbd` | 지방계약 사용자 입력 화면 현황·설계 [local_user_input_ui_20261005.md](../design/local_user_input_ui_20261005.md) |
| `c198bbe6` | 기존 LOCAL 규칙 낙찰하한율 원문 정정 20개(대표값 9, 구간 하한율 11 중 7개는 10억·30억 분할), 대조표 [local_lwlt_audit_20261005.md](../analysis/local_lwlt_audit_20261005.md) |
| `52d2cb2d` | 조달청 하한율·평탄 근거 공백 조사 [pps_lwlt_basis_20261005.md](../analysis/pps_lwlt_basis_20261005.md). 89.995 는 고시 별표가 아니라 첨부 「분야별 낙찰하한율 안내」 에 인쇄됨 |
| `ddff0d6d` | 원문 미기재 14개 규칙 근거 조사 [local_lwlt_sources_supplement_20261005.md](../analysis/local_lwlt_sources_supplement_20261005.md). 경기 보험 47.995 는 INSURANCE 기본값 |
| `511f1f2e` | 조달청 PRE/POST 평탄 77구간 반영. `pps_flat_zone_for`(rule_id + 5억 축·고시금액 축), 평가·예측 경로 배선 |
| `91fb1f9f` | LOCAL 14개 규칙 하한율 공고 실측 [local_lwlt_announcement_measure_20261005.md](../analysis/local_lwlt_announcement_measure_20261005.md). 조달청 발주 164건 제외 |
| `f51b5460` | 입찰 상세(Jinja)에 지방계약 차단 4종 사유·안내 매핑, 기준비율·용역 세부유형·비가격 정량점수 입력, 재요청 페이로드 |
| `35b05e29` 외 3건 | 현황판 `source_commit` 갱신 전용 병합 |

모든 병합은 strict Level 1 게이트, 독립 리뷰 pass, 병합 전 전량 시험 증거를 거쳤습니다. 병합 전 전량 시험은 6,380~6,474 passed 범위였습니다.

---

## 2. 사용자 결정 (2026-10-05~06)

| 항목 | 결정 |
| --- | --- |
| 기존 LOCAL 하한율 점검 | 다음 과업으로 넘기기로 했다가 같은 세션에 병렬로 앞당겨 완료 |
| 구간별 하한율 결함(충남 별표 5) | 구간별 하한율 지원 후 병합 |
| 입력 화면 | Jinja 상세 화면만 구현. React 는 범위 밖 |
| 조달청 평탄 | 평탄만 반영, 하한율·통과점수는 그대로. 반영에 필요한 배선은 코디네이터가 범위 확장 승인 |
| 원문 미기재 하한율 | 나라장터 공고 실측 조사(DB raw_data). 코드 반영은 0장 1번 결정 대기 |
| 리뷰어 | kilo `space-bunny-alpha` 가 OpenRouter 에서 사라져 opencode `muse-spark-1.3-contributor-free` 로 교체 |

---

## 3. 확정된 사실 (재조사 불필요)

- 구간별 하한율: `PriceBand.lwlt_rate` 가 있으면 공고 하한율이 없을 때 추정가격 구간 값을 쓰고, 구간 값이 서로 다른데 추정가격을 모르면 `LWLT_RATE_UNRESOLVED` 로 막습니다. 공고 하한율은 항상 우선입니다. `/predictions` 도 같은 해석을 씁니다.
- 조달청 평탄 축 판별(`pps_axis_side`)은 B·k 값이 규칙 축 사전의 어느 쪽 값과 같은지로 역추론합니다. 두 쪽 값이 같은 규칙은 0건이고, 사용자 B·k 입력이 어느 쪽과도 다르면 평탄을 적용하지 않습니다(리뷰 확인).
- 별표 6 보험, 일반 띠 3개(`ATTACH_12·13·14`), 기술용역에는 평탄이 없습니다. 일반 띠 3개는 단일 별표 귀속이 불가합니다.
- 공고 실측 모집단은 시·도 발주 공고만입니다. 조달청 발주 계약(약 164건)은 제외했습니다.

---

## 4. 남은 일

| 우선 | 항목 | 비고 |
| --- | --- | --- |
| 1 | 0장 결정 3건 | |
| 2 | 입력 화면 실제 브라우저 확인 | 로그인 필요 화면이라 운영 DB 시험 계정 없이 렌더 HTML 만 확인(입력 3종 렌더, 인라인 JS 구문, 콘솔 오류 없음). 입력 후 재요청 흐름은 끝단 시험·리뷰에만 의존 |
| 3 | React 화면 | 여전히 `/predictions/predict-price` 를 호출해 LOCAL 입력이 없음. 설계 문서 6.1 (a)안 |
| 4 | 조달청 평탄 제2026-390호 재사용 12칸 원문 재대조 | P1 리뷰 residual |
| 5 | 통과 구간 이분의 응답 필드화, `/predictions` 구간 대체의 응답 필드화 | 지금은 사유 문구로만 안내 |
| 6 | 원문 미확보 4곳(LH, 한전KPS, 전력연구원, 도로공사 현행판) | 사용자 몫 |

---

## 5. 이번 세션 조율 함정

- **빌더가 `worker_done.json` 을 쓰지 않는 경우가 있습니다.** F1·N1 빌더가 Orca 메시지만 보내고 보고서 파일을 빠뜨려 게이트 6 이 실패했습니다. 코디네이터가 보고서를 만들지 않고, 원 Task 경로에 보고서만 쓰는 짧은 Task(`--no-commit-notice`, 원 Capsule report_schema 준수)를 붙였습니다. `worker_done` 수신 직후 파일 실재부터 확인합니다.
- **현황판 `source_commit` 은 병합 4건마다 갱신합니다.** 허용 간격 5를 넘기면 `validate_agent_rules.py` 가 실패해 푸시가 막힙니다. 푸시하지 않은 로컬 병합을 되돌리는 `reset --hard` 는 자동 모드가 거부합니다. 갱신 전용 브랜치를 병합하는 것이 안전한 경로입니다.
- **리뷰 반복은 판정 범위로 끊습니다.** Y1 보고서는 리뷰 4회 동안 매번 새 지적이 나왔습니다. 재리뷰 Capsule 에 "지적 사항 교정 여부와 이번 diff 만 결함, 나머지는 residual_risks" 를 적자 수렴했습니다. 교정 빌더에는 같은 유형을 문서 전체에서 한 번에 점검하게 합니다.
- **stealth 모델은 예고 없이 사라집니다.** 리뷰어가 "No endpoints found" 로 멈췄고 감시기는 잡지 못했습니다. 이미 `review_done.json` 을 쓴 F1 리뷰(pass)는 그 파일을 근거로 썼고 Dispatch 는 `worker-stop` 했습니다(그 Task `task_feccc201f449` 는 blocked 로 남음). N1 은 muse-spark 로 재리뷰했습니다.
- **리뷰어가 빈 응답으로 멈추면 `orca terminal send` 로 재개 지시를 넣습니다.** 진행 표시(`esc interrupt`) 부재로 판정합니다.
- **완료 통보를 늦게 처리하면 다음 Dispatch 가 회수 감사에 막힙니다.** 배경 대기가 다른 일 중에 끝났으면 바로 `check` 합니다.
- 셸 `&` 로 띄운 대기는 알림이 오지 않습니다. 이 세션에 두 번 반복했습니다.
- 워크트리 삭제 전에 `EXT/` 원문과 `.orca/capsules/<task>/` 보고서를 주 저장소로 복사합니다.

---

## 6. 종료 시점 상태

- main 은 이 문서 병합 커밋이며 origin 과 동기화. 작업 브랜치 0, 워크트리는 주 저장소 하나.
- Orca Run `run_c6cbadfe4a2b` 의 Task 39개 중 38개 completed, 1개(`task_feccc201f449`, F1 리뷰) blocked. 모델 소멸로 중지했고 리뷰 판정은 `.orca/capsules/task_feccc201f449/review_done.json`(pass).
- 워커 산출물과 원문은 주 저장소 `.orca/capsules/` 에 보존(gitignore 대상).
- Docker compose 기동 상태 유지(worker 상시 가동 결정).
