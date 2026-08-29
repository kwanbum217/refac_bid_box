# 벤치마크 및 품질 평가 산출물 가이드

> **작성일**: 2026-08-29
> **버전**: v1.0.0
> 본 문서는 `data/benchmarks/` 디렉터리에 저장되는 벤치마크 및 LLM 품질 평가 산출물의 정본(Canonical) 판정 기준과 분류 체계를 정의합니다.

---

## 1. 개요

`scripts/measure_llm_quality.py` 하네스는 RAG 질의 경로의 응답 품질을 측정하고 정본 여부를 엄격히 검증하여 저장합니다. 정본(Canonical) 산출물은 사전에 합의된 정본 평가 셋(Fixture)과 완전한 측정 조건(무실패, 전량 측정, 3회 이상 반복, clean 트리, 모델 및 포트 결박)을 모두 충족해야 합니다.

---

## 2. 정본 Fixture 사양

현재 유효한 정본 Fixture 사양은 다음과 같습니다.

| 구분 | 사양 |
| --- | --- |
| 파일 경로 | `data/eval/llm_quality_fixture_v2.json` |
| 문항 수 | 32문항 |
| SHA256 해시 | `2c98c636a478cfc92870533513b4442704d8441bd217e303489c9bcf0752e483` |
| 버전 필드 | `2.0.0` (동일 버전 명칭이 존재하므로 내용 해시로만 정본 판정) |

---

## 3. Canonical 판정 게이트

정본(`canonical: true`)으로 인정받기 위해서는 다음 모든 게이트를 통과해야 합니다. 하나라도 미달 시 `canonical: false`로 기록되며 실패한 게이트 목록이 `canonical_failed_gates` 필드에 남습니다.

| 게이트 식별자 | 검증 내용 | 필수 조건 |
| --- | --- | --- |
| `fixture_sha256_canonical` | Fixture 파일 내용의 SHA256 해시 검증 | `CANONICAL_FIXTURE_HASHES` 등록 해시와 일치 |
| `limit_zero` | 문항 수 제한 적용 여부 | `--limit 0` (전체 문항 대상) |
| `item_count_full` | 측정된 문항 수의 완결성 | Fixture 전체 문항 수와 일치 |
| `repetitions_minimum` | 문항당 반복 측정 횟수 | `--repetitions` 3회 이상 |
| `no_request_failures` | HTTP 요청 실패 건수 | 0건 |
| `provenance_strict` | Provenance 엄격 모드 적용 | `--allow-unknown-provenance` 미사용 |
| `start_sha_known` / `end_sha_known` | 소스 Git SHA 식별 가능 여부 | `unknown`이 아닌 유효한 Commit SHA |
| `start_clean` / `end_clean` | 소스 트리 변경 여부 | 측정 시작 및 종료 시점 모두 `dirty: false` |
| `model_match_expected` | 서빙 모델 일치 여부 | `OLLAMA_MODEL` 환경변수와 `--expected-model` 일치 |
| `port_validated` | 서빙 포트 바인딩 검증 | `base_url`이 대상 컨테이너의 발행 포트와 일치 |

---

## 4. noncanonical 디렉터리 안내

`data/benchmarks/noncanonical/` 디렉터리는 정본 게이트를 충족하지 못했으나 디버깅, 비교 분석, 참조 목적으로 보존하는 산출물을 격리 보관하는 공간입니다.

- **대표 파일**: `data/benchmarks/noncanonical/blind_fixture_v1_20260828_reference.json`
  - **사유**: 2026-08-28 세션에서 v1 24문항 fixture로 측정된 참조용 결과(`canonical: false`).

---

## 5. 과거 측정 산출물 비교 기준

과거 세션에서 v1 fixture(24문항) 기반으로 측정된 산출물은 당시 기준의 기록으로 보존되며, 현행 정본(v2 32문항)과 직접적인 지표 비교가 불가합니다.

| 파일명 | 측정 모델 | 당시 기록 상태 | 현행 정본(v2)과의 관계 |
| --- | --- | --- | --- |
| `llm_quality_e2b_v3_20260825.json` | gemma4:e2b | `canonical: true` | v1 24문항 기준 기록 (현 정본과 직접 비교 불가, 원본 보존) |
| `llm_quality_e4b_v3_20260825.json` | gemma4:e4b | `canonical: true` | v1 24문항 기준 기록 (현 정본과 직접 비교 불가, 원본 보존) |
| `llm_quality_e2b_v4_20260826.json` | gemma4:e2b | `canonical: true` | v1 24문항 기준 기록 (현 정본과 직접 비교 불가, 원본 보존) |
| `llm_quality_e4b_v4_20260826.json` | gemma4:e4b | `canonical: true` | v1 24문항 기준 기록 (현 정본과 직접 비교 불가, 원본 보존) |
