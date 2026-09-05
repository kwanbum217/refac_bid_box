# X4 세대 디렉터리와 LIVE 포인터 구현 결과

> **작성일**: 2026-09-05
> **Task**: `task_881836d431ef` / `task_x5_live_pointer_impl`
> **상태**: 구현 완료
> **선행 설계**: `docs/analysis/task_5e66c4c224d4.md`
> **선행 커밋**: `d454ca1` (`docs: X4 혼합 버전 반례의 최소 변경 설계를 기록한다`)

---

## 1. 개요 및 목적

선행 구현(`902a046`)은 서빙 경로의 디렉터리 부재 구간을 제거했으나, 파일별 `os.replace` 방식을 채택하여 승격 도중 프로세스 중단(SIGKILL, OOM 등)이나 다중 파일 교체 중 일부 실패 시 구 버전과 신 버전 파일이 섞여 읽히는 세트 원자성 결함이 존재했습니다.

본 작업은 `docs/analysis/task_5e66c4c224d4.md`에 확정된 설계를 그대로 구현하여 다음과 같은 불변조건을 달성했습니다:
1. **세트 원자성**: 완성된 파일 세트를 불변 세대 디렉터리(`data/model_files/<model>/generations/<version>/`)에 배치한 뒤 단일 파일(`LIVE`)의 `os.replace` 한 번으로 공개를 완결합니다. 승격과 롤백의 어느 시점에도 구 버전과 신 버전 파일이 섞여 읽히지 않습니다.
2. **서빙 경로 지속성**: 서빙 슬롯 디렉터리 이름(`data/model_files/<model>/`)은 교체 전 과정에서 단 한 순간도 사라지지 않습니다.
3. **단일 공급원 해석기**: `src/ml/model_registry.py`의 `resolve_serving_tree` 함수가 `LIVE` 파일과 세대 트리를 검증하여 유효한 경로를 단일하게 해석합니다.
4. **G1 무손실 및 레거시 호환**: `LIVE` 파일이 없는 원본 4개 모델은 슬롯 루트를 그대로 읽으며, 슬롯 루트의 기존 파일은 삭제하거나 덮어쓰지 않습니다.

---

## 2. 채택 아키텍처 및 레이아웃

```text
data/model_files/<model>/                 # 서빙 슬롯 (불변 이름 유지)
  LIVE                                    # 한 줄: 세대 디렉터리명 (os.replace 로 원자 교체)
  generations/<version>/                  # 불변 세대 트리
    model.bin
    metadata.json
    model_q*.bin                          # 분위 모델 (있을 때만)
  model.bin                               # LIVE 가 없을 때만 읽는 레거시 경로 (보존)
  metadata.json                           # 레거시 메타데이터 (보존)
```

### 2.1 LIVE 포인터 규약
- 일반 텍스트 파일이며 심볼릭 링크나 junction을 사용하지 않습니다.
- 내용은 개행을 포함한 세대 디렉터리 식별자(`v_YYYYMMDD_HHMMSS_000\n`)입니다.
- 임시 파일(`.LIVE_<pid>_<id>.tmp`)에 기록 후 동일 슬롯 내에서 `os.replace`하여 원자적으로 전환합니다.
- `LIVE`가 가리키는 대상 디렉터리가 불완전하거나 유효하지 않은 경우 fail-closed 원칙에 따라 레거시 슬롯 루트로 안전하게 폴백합니다.

---

## 3. 변경 파일 내역

| 파일 경로 | 주요 변경 내용 |
| --- | --- |
| `src/ml/model_registry.py` | `LIVE_FILENAME`, `GENERATIONS_DIRNAME`, `resolve_serving_tree` 정의, 점(`.`) 접두 디렉터리 필터링, `discover_models` 및 `get_served_version`에 단일 해석기 적용 |
| `src/ml/promotion.py` | `publish_live`, `_prune_generations` 추가, `_promote_unlogged` 및 `rollback`을 세대 디렉터리와 `publish_live` 기반으로 전면 개편, 슬롯 내부 파일 단위 루프(`_install_staging_into_serving`) 삭제, `load_serving_metrics` 및 `_metadata_version`에 `resolve_serving_tree` 적용 |
| `scripts/promote_model.py` | `_read_metadata`에 `resolve_serving_tree`를 적용하여 CLI `status`에서 정확한 서빙 버전 표출 (코디네이터 사전 승인) |
| `tests/test_promotion_gate.py` | 설계 7.1절 반례 테스트(킬 창 시뮬레이션, LIVE 교체 실패, 다중 파일 세트 원자성, 레거시 폴백 등) 추가 및 기존 테스트 갱신 |
| `tests/test_promotion_cli.py` | `_serving_version`에 `resolve_serving_tree` 적용, 롤백 LIVE 교체 실패 주입 테스트 갱신, 분위 아티팩트 보존 검증 |

---

## 4. 검증 결과

### 4.1 단위 및 회귀 테스트

| 검증 항목 | 명령 | 결과 |
| --- | --- | --- |
| 승격 게이트 및 CLI 테스트 | `uv run pytest tests/test_promotion_gate.py tests/test_promotion_cli.py -q` | 29 passed |
| 판정 증거 결속 및 챔피언 해결 | `uv run pytest tests/test_promotion_evidence_binding.py tests/test_champion_resolution.py -q` | 14 passed |
| 정적 타입 검사 | `uv run mypy src` | 0 errors (93 source files) |
| 에이전트 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | 20/20 passed |
| 단일 특징 소스 보존 | `git diff src/ml/features.py` | 변경 없음 (diff 0) |

---

## 5. 크로스 플랫폼 설계 근거 (Windows 및 Docker)

1. **심볼릭 링크 배제**: Windows 환경에서 개발자 모드나 관리자 권한 없이 심볼릭 링크 생성이 실패하며, Docker virtiofs/osxfs 바인드 마운트에서 호스트-컨테이너 간 링크 교체가 깨질 수 있으므로 일반 파일의 `os.replace` 방식을 채택했습니다.
2. **동일 볼륨 원자 교체**: 스테이징 디렉터리를 서빙 디렉터리와 동일한 볼륨(`serving_dir/.promote_staging_*`)에 생성하여 `generations/<version>`으로 이동할 때 POSIX `rename(2)` 및 Windows `MoveFileEx`가 즉시 수행되도록 보장했습니다.
3. **슬롯 디렉터리 경로 유지**: 기존 컨테이너 내부 프로세스가 서빙 슬롯 경로(`data/model_files/<model>/`)를 마운트하고 있어도 디렉터리 핸들이 유실되지 않고 내부 파일 포인터만 원자적으로 교체됩니다.
