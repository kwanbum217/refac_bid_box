# 운영 문서 정합성 및 공급망 정책 1인 작업 일치화 (task_4ff8fb0ca9cd)

> **작성일**: 2026-09-05
> **브랜치**: kwanbum217/wave-u-c012
> **태스크**: task_4ff8fb0ca9cd
> **진단 항목**: C-01 (운영 문서-코드 정합성 잔여 4건), C-02 (공급망 정책 1인 작업 일치화)

---

## 1. 개요 및 목적

본 문서는 2026-09-04 외부 진단 보고서에서 지적된 잔여 결함 2개 영역을 해결하고 그 근거를 기록합니다.

1. **C-01 잔여 4건 정합**: 코드는 이미 구현·검증되었으나 운영 문서(`current_state_facts.yaml`, `CURRENT_STATE.md`)에 `active`(진행/개선 추진/병합 후 확인 대기)로 남아있던 4개 항목을 실제 코드 및 CI 설정 실측을 바탕으로 `closed` 상태로 바로잡습니다.
2. **C-02 공급망 정책 1인 작업 일치화**: `docs/ops/supply_chain_policy.md` 및 관련 공급망 문서에 남아있던 다인 조직 전제(플랫폼 팀 소유, PR 본문 사유 기재, PR 단위 코드 리뷰)를 저장소의 1인 개발 규약([`AGENTS.md`](../../AGENTS.md) 6장)과 일치시킵니다. 차단 임계값, 심각도 기준, fail-closed 입력 계약 등 보안 게이트 강도는 일체 완화하지 않고 100% 유지합니다.

---

## 2. C-01 잔여 4건 실측 및 판정 근거

| 항목 ID | 이전 상태/주장 | 실제 코드/CI 상태 | 판정 근거 (파일 경로 및 줄 번호) | 갱신 후 상태/주장 |
|---|---|---|---|---|
| `confirmation_token_redis` | `active` / 확인 토큰 소비 기록은 프로세스 지역 집합이고 Redis TTL 이전을 추진합니다. | Redis 원자적 단일 소비(`client.set(..., ex=ttl, nx=True)`)로 완전 구현되어 fail-closed 처리됨. | [`src/app/services/automation_tokens.py:39-68`](../../src/app/services/automation_tokens.py#L39-L68) | `closed` / 확인 토큰 소비 기록은 Redis TTL 원자적 단일 소비(SET NX EX)로 완료 상태를 유지합니다. |
| `ci_windows` | `active` / CI Windows job은 continue-on-error 없이 정규 게이트로 통과 중이며 병합 후 결과 재확인을 진행합니다. | `.github/workflows/ci.yml`의 `cross-platform-test` 매트릭스에 `windows-latest`가 정규 게이트로 포함되어 있으며, `continue-on-error`가 전혀 없음 (0건). | [`.github/workflows/ci.yml:194,231-233`](../../.github/workflows/ci.yml#L194), [`docs/ops/ci_contract.md:19,48-53`](../../docs/ops/ci_contract.md#L19) | `closed` / CI Windows job은 continue-on-error 없이 정규 게이트로 통과 상태를 유지합니다. |
| `row_reconciliation` | `active` / 행 수 판정은 하한 검사이며 성장 데이터와 이행 원본 reconciliation은 미구현으로 개선을 추진합니다. | `verify_reconciliation()` 및 `_count_rows_by_cutover()`가 `MIGRATION_CUTOVER_TS` 기준으로 이행 원본과 성장분을 분리 대조하도록 완전 구현됨. | [`scripts/verify_migration.py:10-12,64-67,690-711,713-853,1018-1028`](../../scripts/verify_migration.py#L690-L711), [`tests/test_g1_reconciliation.py:1-357`](../../tests/test_g1_reconciliation.py#L1-L357) | `closed` / 행 수 판정은 하한 검사 및 성장 데이터와 이행 원본 reconciliation 분리 대조로 완료 상태를 유지합니다. |
| `promotion_status_check` | `active` / promote_model.py status의 레지스트리 차단 동작은 병합 후 검증을 진행합니다. | `scripts/promote_model.py`의 `cmd_status()`가 `paired_verdict.json` 기각 및 아티팩트 부재 시 승격 불가 및 차단을 처리하며, 단위 테스트 슈트로 검증 완료됨. | [`scripts/promote_model.py:88-141`](../../scripts/promote_model.py#L88-L141), [`tests/test_promotion_gate.py:245-272`](../../tests/test_promotion_gate.py#L245-L272) | `closed` / promote_model.py status의 레지스트리 차단 동작은 쌍대 기각 검증 통과 상태를 유지합니다. |

---

## 3. C-02 공급망 문서 1인 작업 규약 일치화

### 3.1 변경 원칙 및 불변 조건

- **1인 작업 규칙 정합**: [`AGENTS.md`](../../AGENTS.md) 6장에 명시된 "1인 작업, Pull Request 미생성, main 직접 병합 금지, 작업 브랜치에서 검증 후 `git merge --no-ff`로 병합" 규칙에 따라 다인 조직 전제(플랫폼 팀 소유, PR 본문 기록, PR 코드 리뷰)를 제거하였습니다.
- **예외 기록 및 추적성 유지**: PR 리뷰가 없는 대신, `.github/vulnerability-allowlist.yml`의 필수 4대 필드(`id`, `package`, `reason`, `expires_on`) 기재와 작업 브랜치 커밋 메시지 기록을 의무화하였습니다. 이는 CI 스캔 전 단계인 `scripts/check_vulnerability_allowlist.py`로 자동 검증됩니다.
- **보안 강도 유지 (완화 절대 금지)**:
  - 스캔 도구 3종(pip-audit, npm audit, Trivy)의 차단 임계값(`CRITICAL`, `HIGH`)은 변경 없이 그대로 유지됩니다.
  - `continue-on-error`, `|| true`, 스캔 누락 통과 금지 원칙은 동일하게 집행됩니다.
  - 판정 스크립트([`scripts/filter_npm_audit.py`](../../scripts/filter_npm_audit.py), [`scripts/filter_trivy_results.py`](../../scripts/filter_trivy_results.py))의 Fail-Closed 입력 계약 검증은 불변입니다.

### 3.2 문서별 반영 내역

1. [`docs/ops/supply_chain_policy.md`](../../docs/ops/supply_chain_policy.md):
   - 버전 1.3.0 → 1.3.1 갱신.
   - 소유 주체: `플랫폼 팀` → `1인 개발 담당자`.
   - 제2장: "한 번에 너무 많이 막으면 팀이 게이트를 끄게 된다" → "한 번에 너무 많이 막으면 작업 흐름이 마비되므로"로 중립화.
   - 제3.3장: PR 본문 기록 요구 → `.github/vulnerability-allowlist.yml`의 사유·만료일 필드 및 작업 브랜치 커밋 메시지 기록으로 대체.
   - 제6장: 플랫폼 팀 승인 및 PR 코드 리뷰 필수 조항을 1인 작업 책임 및 추적성 기계 강제 조항으로 정정.
   - 제7장: v1.3.1 변경 이력 추가.
2. [`docs/ops/supply_chain.md`](../../docs/ops/supply_chain.md):
   - 최종 갱신일: 2026-09-05.
   - 보고 전용 서술 제거 및 3개 스캔 정규 차단 게이트 운영 명시.
   - 1인 작업 체계에 맞춘 PR 부재 및 allowlist/커밋 메시지 기반 예외 관리 규약 명시.
3. [`docs/ops/ci_supply_chain.md`](../../docs/ops/ci_supply_chain.md):
   - 제3.2장에 1인 작업 예외 관리 원칙 준수 항목 명시.

---

## 4. 검증 결과

1. **규칙 정합성 검증 (`scripts/validate_agent_rules.py`)**:
   - 명령: `python3 scripts/validate_agent_rules.py --quiet`
   - 결과: 통과 (20/20 PASS)
   - 세부 확인:
     - `CURRENT_STATE 판정 사실 원장 검증`: 33개 판정 사실 정합성 통과.
     - `CURRENT_STATE 기계 상태 원장 정합성`: 33개 과업 상태 원장과 문서 앵커 정합성 통과.
     - `CURRENT_STATE 6.1 상태 모순 검사`: 8개 미해결 항목 모순 없음 통과.
2. **공급망 예외 목록 계약 검증 (`scripts/check_vulnerability_allowlist.py`)**:
   - 명령: `uv run python scripts/check_vulnerability_allowlist.py`
   - 결과: 통과 (`공급망 예외 목록 검사 통과: 4건 (전부 사유와 유효한 만료일 보유)`)
