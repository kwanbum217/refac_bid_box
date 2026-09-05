# X4 세대 디렉터리와 LIVE 포인터 구현 결과

> **작성일**: 2026-09-05
> **Task**: `task_eeb664fda353` (선행 `task_881836d431ef` 반려 재작업) / `task_x5_live_pointer_impl`
> **상태**: 구현 및 재검증 완료
> **선행 설계**: `docs/analysis/task_5e66c4c224d4.md`
> **선행 커밋**: `6da7a9b` (`feat: 세대 디렉터리와 LIVE 포인터 기반 모델 승격·롤백 원자성 구현`)

---

## 1. 개요 및 목적

선행 구현(`902a046`)은 서빙 경로의 디렉터리 부재 구간을 제거했으나 파일별 `os.replace`로 인한 세트 원자성 결함이 있었으며, 1차 세대 디렉터리 구현(`task_881836d431ef`)에서는 동일 버전 재승격 시 현재 서빙 중인 세대를 제자리에서 `shutil.rmtree`로 파일 단위 삭제하는 결함이 발견되어 반려되었습니다.

본 재작업(`task_eeb664fda353`)은 `docs/analysis/task_5e66c4c224d4.md` 설계 및 코디네이터 지침을 철저히 준수하여 다음 불변조건을 완벽히 달성했습니다:
1. **제자리 삭제 금지 및 고유 세대 식별자**: `generate_generation_id`를 도입하여 세대 디렉터리명에 타임스탬프와 고유 토큰을 결합(`generations/<version>_<timestamp>_<token>/`). 동일 버전이 다시 승격되거나 롤백되더라도 기존 공개 세대 경로와 결코 충돌하지 않습니다.
2. **원자적 세트 전환**: 새 세대를 항상 완전히 새로운 경로에 온전히 완성한 뒤에만 `publish_live`를 통해 `LIVE` 파일의 원자적 `os.replace`로 공개합니다. 전환이 완결된 후에만 이전 세대를 정리(`_prune_generations`)합니다.
3. **프로세스 킬 안전성**: `publish_live` 직전에 프로세스가 중단(SIGKILL, OOM 등)되더라도 `LIVE` 파일은 직전의 온전한 세대를 가리키고 있으며, 현재 서빙 세트는 손상되지 않습니다.
4. **단일 공급원 해석기**: `src/ml/model_registry.py`의 `resolve_serving_tree` 함수가 `LIVE` 파일과 세대 트리를 검증하여 유효한 경로를 단일하게 해석합니다.
5. **G1 무손실 및 레거시 호환**: `LIVE` 파일이 없는 원본 4개 모델은 슬롯 루트를 그대로 읽으며, 슬롯 루트의 기존 파일은 삭제하거나 덮어쓰지 않습니다.

---

## 2. 채택 아키텍처 및 레이아웃

```text
data/model_files/<model>/                 # 서빙 슬롯 (불변 이름 유지)
  LIVE                                    # 한 줄: 세대 디렉터리 식별자 (os.replace 로 원자 교체)
  generations/<gen_id>/                   # 불변 세대 트리 (<version>_<timestamp>_<token>)
    model.bin
    metadata.json
    model_q*.bin                          # 분위 모델 (있을 때만)
  model.bin                               # LIVE 가 없을 때만 읽는 레거시 경로 (보존)
  metadata.json                           # 레거시 메타데이터 (보존)
```

### 2.1 LIVE 포인터 규약
- 일반 텍스트 파일이며 심볼릭 링크나 junction을 사용하지 않습니다.
- 내용은 개행을 포함한 고유 세대 식별자(`v_YYYYMMDD_HHMMSS_000_YYYYMMDD_HHMMSS_token\n`)입니다.
- 임시 파일(`.LIVE_<pid>_<uuid>.tmp`)에 기록 후 동일 슬롯 내에서 `os.replace`하여 원자적으로 전환합니다.
- `LIVE`가 가리키는 대상 디렉터리가 불완전하거나 유효하지 않은 경우 fail-closed 원칙에 따라 레거시 슬롯 루트로 안전하게 폴백합니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 주요 변경 내용 |
| --- | --- |
| `src/ml/model_registry.py` | `LIVE_FILENAME`, `GENERATIONS_DIRNAME`, `resolve_serving_tree` 정의, 점(`.`) 접두 디렉터리 필터링, `discover_models` 및 `get_served_version`에 단일 해석기 적용 |
| `src/ml/promotion.py` | `generate_generation_id`, `publish_live`, `_prune_generations` 추가. 제자리 `shutil.rmtree` 제거 및 충돌 방지 세대 경로에 사전 완성 후 원자 교체. `rollback`도 고유 세대 ID 기반 원자 교체로 개편. `load_serving_metrics` 및 `_metadata_version`에 `resolve_serving_tree` 적용 |
| `scripts/promote_model.py` | `_read_metadata`에 `resolve_serving_tree`를 적용하여 CLI `status`에서 정확한 서빙 버전 표출 (코디네이터 사전 승인) |
| `tests/test_promotion_gate.py` | 동일 버전 재승격 도중 프로세스 킬 시뮬레이션 회귀 테스트(`test_same_version_repromotion_kill_preserves_serving_set`) 및 rename 실패 회귀 테스트(`test_same_version_repromotion_staging_replace_failure_preserves_serving_set`) 추가, 킬 창 시뮬레이션 및 다중 파일 세트 원자성 검증 |
| `tests/test_promotion_cli.py` | `_serving_version`에 `resolve_serving_tree` 적용, 롤백 LIVE 교체 실패 주입 테스트 갱신, 분위 아티팩트 보존 검증 |

---

## 4. 검증 결과

### 4.1 단위 및 회귀 테스트

| 검증 항목 | 명령 | 결과 |
| --- | --- | --- |
| 승격 게이트 및 CLI 테스트 (회귀 테스트 포함) | `uv run pytest tests/test_promotion_gate.py tests/test_promotion_cli.py -q` | 31 passed |
| 전체 테스트 스위트 (data_assets 제외) | `uv run pytest tests/ -q -m 'not data_assets'` | 3670 passed, 41 skipped |
| 정적 타입 검사 | `uv run mypy src` | 0 errors (93 source files) |
| 에이전트 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 passed |
| 단일 특징 소스 보존 | `git diff src/ml/features.py` | 변경 없음 (diff 0) |

---

## 5. 크로스 플랫폼 설계 근거 (Windows 및 Docker)

1. **심볼릭 링크 배제**: Windows 환경에서 개발자 모드나 관리자 권한 없이 심볼릭 링크 생성이 실패하며, Docker virtiofs/osxfs 바인드 마운트에서 호스트-컨테이너 간 링크 교체가 깨질 수 있으므로 일반 파일의 `os.replace` 방식을 채택했습니다.
2. **동일 볼륨 원자 교체**: 스테이징 디렉터리를 서빙 디렉터리와 동일한 볼륨(`serving_dir/.promote_staging_*`)에 생성하여 `generations/<gen_id>`로 이동할 때 POSIX `rename(2)` 및 Windows `MoveFileEx`가 즉시 수행되도록 보장했습니다.
3. **슬롯 디렉터리 경로 유지**: 기존 컨테이너 내부 프로세스가 서빙 슬롯 경로(`data/model_files/<model>/`)를 마운트하고 있어도 디렉터리 핸들이 유실되지 않고 내부 파일 포인터만 원자적으로 교체됩니다.
