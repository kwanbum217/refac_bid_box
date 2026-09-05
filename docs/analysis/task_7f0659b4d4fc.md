# task_7f0659b4d4fc 작업 보고

> **작성일**: 2026-09-05
> **역할**: builder
> **정본 설계**: [`docs/analysis/task_x4_model_swap_atomic.md`](task_x4_model_swap_atomic.md)

승격·롤백의 서빙 디렉터리 두 번 이동을 없앴습니다. 같은 볼륨 파일 단위 `os.replace` 로 서빙 경로 이름을 유지하고, Windows 심볼릭 링크와 Docker 바인드 마운트 링크 교체는 채택하지 않았습니다. 중간 실패는 백업/holding 복사본으로 서빙 트리를 되돌립니다.

`CURRENT_STATE` 의 `model_swap_gap` 은 코디네이터 소유라 수정하지 않았습니다. 디스크 전환 후 인메모리 `ModelRegistry` 교체는 범위 밖이며 변경하지 않았습니다.
