# cmd 워커 토큰 절약 A/B 측정 (포니테일·스킬 탐색 끄기)

> **작성일**: 2026-11-13
> **측정자**: 코디네이터(Claude Opus 5.5). 측정 대상 에이전트는 cmd `deepseek/deepseek-v4.1-flash`
> **기준 커밋**: `2cf35705` (하니스 `scripts/token_ab_cmd.py`)
> **결론**: 효과 미검출. 1차 6회에서 보인 큰 절감은 2차 확증 9회에서 뒤집혔고 합산 과업 내 순열 검정 p=0.54 입니다. 워커 런처 기본값은 바꾸지 않습니다.

---

## 1. 설계

| 항목 | 값 |
| --- | --- |
| 실행 | `cmd -p <과업> --output-format json --max-turns 80 --trust --yolo --no-session`, 실행마다 임시 워크트리와 워커 정책 파일 배치 |
| 조건 | baseline, no_skills(`--no-skills`), ponytail(`--skill` 공식 `skills/ponytail/SKILL.md`), ponytail_no_skills(둘 다) |
| 과업 | 2026-11-13 병합 과업 3개를 빌더 커밋 직전에서 재수행: report_asof(`8c86a7bc`), cmd_launch_skill_flags(`1281c026`), bench_cookie_all(`1ede4ea8`). 병합본 시험 파일을 숨은 시험으로 판정 |
| 1차 | 조건 4 × 과업 3 × 2회 = 24회(유효 23), 시드 42 |
| 2차 확증 | baseline·ponytail_no_skills × 과업 3 × 3회 = 18회(유효 18), 시드 7 |
| 지표 | cmd 결과 줄 `usage`(input·output·cacheRead·cacheWrite), 실행 시간, 추가 줄 수, 숨은 시험 통과 |

---

## 2. 결과

| 묶음 | baseline 평균 총 토큰 | ponytail_no_skills 평균 총 토큰 | 숨은 시험 실패 |
| --- | --- | --- | --- |
| 1차 | 3.78M | 1.24M (p=0.059) | 0 / 0 |
| 2차 | 1.89M | 3.54M (p=0.13, 반대 방향) | 1 / 6 |

| 과업(1·2차 합산 중앙값) | baseline | ponytail_no_skills | 배율 |
| --- | --- | --- | --- |
| bench_cookie_all | 1.83M | 1.19M | 0.65 |
| cmd_launch_skill_flags | 0.99M | 0.88M | 0.90 |
| report_asof | 3.75M | 3.81M | 1.02 |

과업 안에서 조건 표지를 섞는 순열 검정(20,000회)은 단측 p=0.54, 평균 배율 ×1.04 입니다.

---

## 3. 해석과 함정

| 항목 | 내용 |
| --- | --- |
| 회차 간 편차 | 같은 조건·과업에서도 총 토큰이 2배 이상 흔들립니다(report_asof baseline 1차 중앙값 8.56M, 합산 3.75M). 조건당 6회로는 이 편차를 넘는 효과만 보입니다 |
| 품질 | 2차에서 ponytail_no_skills 의 숨은 시험 실패가 6건으로 몰렸습니다. 절감을 위해 품질을 잃을 수 있다는 신호입니다 |
| 기본 부담 | 단어 하나 응답에도 입력 약 19K 토큰이 듭니다. 과업 비용 대부분은 캐시 읽기와 입력입니다 |
| 32K 상한 | cmd 에는 컨텍스트 상한이나 자동 압축 시점 옵션이 없어 시험하지 못했습니다 |
| 권고 | 워커 런처 기본값 유지. 재시험은 과업당 10회 이상, 과업을 길이별로 층화해서 합니다. 원자료는 `.cache/token_ab_cmd/run_20261113*`(Git 미추적) |
