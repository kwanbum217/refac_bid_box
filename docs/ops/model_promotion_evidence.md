# 모델 승격 증거 결속

> 승격 판정과 실제 레지스트리 아티팩트의 일치를 확인하는 운영 규칙입니다.

---

## 승격 게이트

`paired_verdict.json`의 `verdict`가 `approved`인 경우 다음 다섯 필드가 모두
비어 있지 않아야 합니다.

| 필드 | 의미 |
| --- | --- |
| `champion_checksum` | `champion_version` 디렉터리의 아티팩트 해시 |
| `challenger_checksum` | 승격 대상 버전 디렉터리의 아티팩트 해시 |
| `sample_hash` | 쌍대 비교에 사용한 표본 식별자 |
| `code_commit` | 비교 실행 코드 커밋 |
| `decided_at` | 판정 시각 |

아티팩트 해시는 `src/ml/promotion.py`의
`compute_artifact_checksum()`이 `model.bin`과 `metadata.json`을 고정된 순서와
파일명·길이 framing으로 묶어 계산한 SHA-256 값입니다. 판정 파일을 다른 버전
디렉터리에 복사하거나 모델 파일·메타데이터를 바꾸면 재계산 값이 달라져
승격이 거부됩니다. `champion_version` 디렉터리가 없거나
`challenger_version`이 현재 승격 대상과 다를 때도 거부됩니다.

`rejected` 판정은 증거 필드가 비어 있어도 즉시 차단되며 `--force`로 우회할 수
없습니다. `approved`의 증거 결속 실패 역시 `--force`로 우회할 수 없습니다.

## 판정 파일 생성

사람이 체크섬을 직접 계산해 JSON을 작성하지 않도록 운영 도구가 두 아티팩트의
해시를 채워 파일을 생성합니다.

```bash
uv run python scripts/promote_model.py create-verdict \
  --model servc_institution_v1 \
  --version v_20260903_000000_000 \
  --champion-version v_20260902_000000_000 \
  --verdict approved \
  --sample-hash <표본-해시> \
  --code-commit <비교-코드-커밋>
```

`create-verdict`, `write-verdict`, `verdict`는 같은 명령의 별칭입니다.
`--decided-at`을 생략하면 현재 UTC 시각이 기록됩니다. `rejected` 판정은
`--evidence`로 기각 사유를 남길 수 있습니다.

## 감사 로그

모든 승격 시도는 `data/promotion_audit.log`에 JSON Lines로 append됩니다. 각
항목에는 시각, 모델명, 버전, 판정 파일 해시, 재계산한 champion·challenger
아티팩트 해시, 결과(`promoted` 또는 `rejected`), 거부 사유가 들어갑니다. 이
경로는 런타임 `*.log` 규칙으로 Git에 추적되지 않으며 기존 항목을 덮어쓰거나
잘라내지 않습니다.
