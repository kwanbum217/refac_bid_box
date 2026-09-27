# CI 게이트 보강 설계 3건 (D-14, D-15, D-16)

> **작성일**: 2026-09-27
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **근거**: 외부 분석 보고서 대조([`external_report_audit_20260927.md`](external_report_audit_20260927.md))에서 규모 M 으로 판정한 세 항목. 조사 워커 3대(cmd GLM-5.3 Flash)의 설계서를 코디네이터가 요약했다. 원본 설계서는 Orca Capsule 디렉터리(`task_056956855d78`, `task_8b10674ec4a9`, `task_768fd91fe52e`)에 있다
> **상태**: 설계만 완료. 구현은 사용자 결정 뒤 별도 Task

---

## 1. 요약

| ID | 권장안 | 규모 | 선행 조건 |
| --- | --- | --- | --- |
| D-14 성능 회귀 CI | 결정적 단위 지표를 추적 기준선 JSON 과 대조하는 게이트 테스트 + CI 전용 스텝. 시간 지표는 관측과 파탄 상한만 | M | 없음 |
| D-15 스키마 서명 CI | MySQL 8 전용 잡에서 `alembic upgrade head` 후 ORM 관리 19테이블 한정 서명 대조 | M | **로컬에서 빈 DB 마이그레이션 결과와 운영 기준선 일치 확인이 먼저**(불일치면 그것이 별도 과제) |
| D-16 `scripts/` 커버리지 | 전역 게이트는 그대로 두고 조율 도구 6종에 개별 하한(실측 -2~3%p) | M | 없음 |

---

## 2. D-14 성능 회귀 CI

- HTTP P95 게이트는 규약(600 표본, 워밍업, 주변 부하 기록)과 러너 성능 편차 때문에 CI 판정에 쓸 수 없다.
- **판정 지표(결정적)**: OpenAPI 경로 49·오퍼레이션 56, 특징 맵 키 97개 집합 해시, `unservable_features(TRAINING_FEATURES) == []`, 홈 컨텍스트 질의 수 상한.
- **관측 지표(시간)**: 특징 구축 시간(실측 평균 0.01ms)은 기록하고 파탄 상한만 둔다.
- 구현: `data/benchmarks/perf_unit_baseline.json`, `tests/test_perf_unit_gate.py`, `docs/ops/latency_gate_protocol.md` 9장, `ci.yml` cross-platform 잡 전용 스텝.

---

## 3. D-15 스키마 서명 CI

- 스키마 기준선 `data/backups/schema_signature_baseline.json` 은 git 추적 파일이라 CI 체크아웃만으로 대조할 수 있다.
- 기준선 37테이블 = ORM 19 + Django 잔여 16 + `alembic_version` + `servc_inst_verify`. Django 잔여는 이식 대상이 아니므로 대조에서 뺀다.
- 구현: `scripts/verify_migration.py` 에 `--signature-scope {full,managed}`(기본 full), 단위 테스트, `ci.yml` 에 `g1-schema-signature` 잡(기존 ngram 잡과 같은 MySQL 다이제스트), 문서 갱신.
- **단계 0 이 관문이다.** 빈 DB 에 마이그레이션 15건을 올린 결과가 운영 기준선과 다르면 게이트보다 그 차이의 해소가 먼저다.

---

## 4. D-16 `scripts/` 커버리지

- `scripts/` 65,497줄은 `src/` 37,429줄의 1.75배라 전역 source 에 넣으면 희석되어 `src` 80% 게이트가 깨진다(계약 테스트 `tests/test_scripts_coverage_gate.py` 와도 상충).
- 기존 전량 pytest 단계에 `--cov=scripts.<모듈>` 만 더해 측정 비용 없이 개별 하한을 건다.

| 스크립트 | 실측 | 초기 하한 |
| --- | --- | --- |
| `orca_taskctl.py` | 80.16% | 78 |
| `orca_model_router.py` | 86.73% | 84 |
| `orca_level1_gate.py` | 77.38% | 74 |
| `orca_auto_approve.py` | 85.80% | 83 |
| `validate_agent_rules.py` | 85.93% | 83 |
| `benchmark_provenance.py` | 83.40% | 80 |

- 무테스트 2종(`orca_forbidden_artifacts.py`, `orca_codex_launch.py`)에 최소 테스트를 붙인다.
