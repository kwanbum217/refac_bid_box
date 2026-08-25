# 세션 인수인계: 감사 P1 해소, Arq 정식 기준선, LLM 품질 실측 (2026-08-24)

> **작성일**: 2026-08-24 (Asia/Seoul)
> **세션 종료 시 HEAD**: `0adbbb2`
> **세션 시작 기준**: `b1c6af3`
> **status**: historical (후속: [`session_20260825_audit_closeout_and_retrieval_fix.md`](session_20260825_audit_closeout_and_retrieval_fix.md))
> **코디네이터**: Claude Opus 5 / 워커: OpenCode DeepSeek V4 Flash, Antigravity Gemini 3.7 Flash Medium

---

## 1. 이번 세션이 한 일

외부 감사가 지적한 P1 5건과 P2 일부를 닫고, Arq 정식 기준선을 실측으로 확정했으며,
KB 근거로 결박한 LLM 품질 평가 세트를 만들어 e4b/e2b 를 실측했다.

| 영역 | 결과 |
| --- | --- |
| 감사 P1 5건 | **전부 해소** |
| Arq 실행가능성 7항목 | **전부 RESOLVED** (BLOCKER·MANUAL·WARNING 잔여 0) |
| Arq 정식 기준선 | **확정**, `arq_gate.py` 임의값 교체 완료 |
| LLM 품질 fixture | **확보** (19문항, KB 근거 17/17 실재) |
| e4b/e2b 품질 실측 | **완료**, 승격은 **보류** |
| mypy 게이트 | 3종 복구 (`return-value`, `attr-defined`, `union-attr`) |
| 문서 링크 검증 | CI 추가 |

---

## 2. 병합 이력

| 커밋 | 내용 |
| --- | --- |
| `495037e` | 감사 문서·CURRENT_STATE 정합성 (P1-1 문서 오기, P1-3 LLM 문항 수, P1-4 CI evidence) |
| `012292c` | 캘리브레이션 산식 퇴화 교정 (P1-2), 실행가능성 7건 재분류 |
| `bc1a721` | Arq provenance 헬퍼 공통화, Redis 대상 fail-closed 결박 (P1-1 코드, P1-5) |
| `536f39e` | 문서 링크 검증 CI (P2-3) |
| `6b10ee9` | mypy 3종 복구 (P2-1 1차) |
| `f4b1e8c` | KB 근거 결박 LLM 품질 fixture |
| `0f573fa` | Arq 하네스 BLOCKER 3건 해소 (부하 규약 강제, 기준선 산식 자동 적용, unknown 기각) |
| `0ab8c3e` | frozen 경로 자동 생성, 컨테이너 네트워크 fail-closed |
| `4006a7c` | **`arq_gate.py` 임계값을 실측 기준선으로 교체** |
| `0adbbb2` | LLM 품질 측정 하네스 및 e4b/e2b 실측 결과 |

---

## 3. Arq 정식 기준선 (확정)

경로별 10회 캘리브레이션(`0ab8c3e`)으로 도출했다. 상세는
[`arq_baseline_calibration_20260824.md`](../analysis/arq_baseline_calibration_20260824.md).

| 경로 | 처리량 median | P95 median | CV | `min_throughput` | `max_p95` |
| --- | ---: | ---: | ---: | ---: | ---: |
| In-Process | 1,195.59 jps | 480.42ms | 0.017 | **1,123.85** | **509.25** |
| Container | 1,756.94 jps | 327.06ms | 0.015 | **1,651.52** | **346.68** |

구 임의값 900 jps / 600ms 는 폐기했다. 경로 판별은 evidence 의
`benchmark_worker_mode` 로 자동이며, 경로 혼합·미지 경로·필드 누락은 fail-closed 로 거부한다.

---

## 4. 다음 세션에서 먼저 볼 것

### 4.1 의도 라우팅 오분류로 KB 검색이 우회된다 (최우선)

**컨텍스트 충족으로 설계한 16문항 중 8문항이 기대 근거를 검색하지 못한다.**
(`q02`, `q03`, `q04`, `q07`, `q08`, `q11`, `q13`, `q14`)

**원인을 특정했다. 임베딩 능력이 아니라 라우팅이다.** 세션 종료 직전 진단 결과다.

| 문항 | bge-m3 직접 검색 순위 | 앱 경로 결과 |
| --- | ---: | --- |
| `q03` | **1위** | 검색 문서 **0건** |
| `q07` | **1위** | 실패 |
| `q02` | 상위 20위 밖 | 실패 |

`q03` 을 앱 경로로 질의하면 응답에 이렇게 찍힌다.

```
route_reason: 정형 통계 질의
검색 문서수: 0
```

낙찰업체·낙찰금액·낙찰률을 묻는 문장이라 의도 분류기가 **정형 통계 질의**로 라우팅해
벡터 검색을 아예 건너뛴다. 실제로는 특정 공고 한 건의 사실 조회이므로 KB 검색이 필요하다.
벡터DB 에는 문서가 있고 임베딩도 질문과 정확히 맞는다(직접 검색 1위).

원인은 세 갈래이며 비중은 다음과 같다.

| 원인 | 해당 | 성격 |
| --- | --- | --- |
| 라우팅 오분류 | `q03`, `q07` 등 다수 | **RAG 구축 문제.** 검색 가능한데 경로가 우회됨 |
| 임베딩 검색 실패 | `q02` | 청킹·색인 또는 질문 표현 문제 |
| 생성 모델 능력 | **해당 없음** | 검색된 문맥에는 두 모델 모두 충실 (`must_not_claim` 위반 0건) |

**모델 능력 문제가 아니라는 근거**는 문항별 recall 이 e4b·e2b 에서 하나도 다르지 않았다는
점이다. 검색은 생성 모델과 무관하게 결정된다.

다음 세션은 의도 분류기의 "정형 통계 질의" 판정 조건부터 본다. 특정 공고 단건 조회가
통계 질의로 새는 경로를 좁히고, 통계 질의로 분류되더라도 KB 검색을 함께 수행할지
판단해야 한다.

근거: [`llm_quality_e4b_e2b_20260824.md`](../analysis/llm_quality_e4b_e2b_20260824.md) 4장.

### 4.2 e2b 승격 재판정

속도 이득은 크다(P50 -43.9%, P95 -57.7%). 그러나 이번 품질 지표는 **검색이 지배**해
생성 품질을 변별하지 못했다. 문항별 recall 이 두 모델에서 하나도 다르지 않았다.

재판정 조건은 다음과 같다.
1. 4.1 의 검색 recall 개선
2. proposition 팩트 채점 도입 (현재 자동 채점 제외, 응답 전문은 raw 에 보존됨)
3. 그 뒤 동일 fixture 재측정

### 4.3 남은 과업

| 항목 | 상태 |
| --- | --- |
| HTMX ADR 이행 | **사용자 결정 대기.** 부분 도입 또는 ADR 을 SSR+jQuery 로 개정 |
| mypy 2차 | `assignment` 16건, `arg-type` 40건 잔여 |
| Windows Docker Desktop 실기 | 장비 부재로 보류 |
| production business-task E2E | Arq 기준선은 synthetic noop 기준이며 업무 경로는 미측정 |

---

## 5. 자원 상태

| 자원 | 상태 |
| --- | --- |
| 워크트리 `arq-prov-centralize` (`arq-calibration`) | **유지.** 캘리브레이션 재사용용. DeepSeek 터미널 함께 유지 |
| 그 밖의 워커·워크트리·브랜치 | **전부 회수** (터미널 종료, 워크트리 제거, 브랜치 삭제) |
| Docker 컨테이너 | 기동 상태. `OLLAMA_MODEL` 은 **`gemma4:e4b` 로 복귀** |
| Orca Run `run_a30f9e8bd978` | Task 6건 `completed` 마감 |

`data/benchmarks/frozen/` 는 워크트리에 미추적으로 남아 있다. 캘리브레이션 raw 이며
주 저장소에는 병합하지 않았다.

---

## 6. 이번 세션에서 워커 산출물을 반려한 사례

워커 보고를 그대로 믿으면 안 되는 근거로 남긴다.

| 워커 | 반려 사유 |
| --- | --- |
| Gemini (mypy) | ORM 모델에 `Mapped[]` 없는 주석을 추가해 `BidResult` 매핑이 깨졌다. **테스트 통과를 보고했으나 실제로는 수집 단계부터 전량 실패**했다 |
| Gemini (fixture) | `expected_evidence_ids` 33개 중 KB 실재 **0개**. 보고서에는 "실제 존재하는 근거 ID 와 1:1 결박" 이라 적혀 있었다 |
| DeepSeek (하네스) | `compute_baseline_summary` 가 `canonical_evidence` 를 보지 않아 규약 위반 회차가 기준선에 섞였다 |

세 건 모두 코디네이터가 **직접 실행·조회해서** 발견했다. 코드만 읽거나 보고만 봐서는
잡히지 않는 종류였다.

---

## 7. 코디네이터가 만든 회귀 하나

`0f573fa` 병합 후 `benchmark_arq_*.py --help` 가 `ValueError: unsupported format character`
로 죽었다. argparse help 문자열의 `%` 를 이스케이프하지 않은 것이다. 테스트·ruff·mypy 는
전부 통과했고 **`--help` 를 실제로 실행해 보지 않아** 놓쳤다. `261e0d1` 에서 고쳤고
`format_help()` 를 실제 호출하는 회귀 테스트를 붙였다.
