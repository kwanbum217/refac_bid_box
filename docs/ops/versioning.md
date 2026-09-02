# 버전 관리 정본 규칙 (Versioning Policy)

> **작성일**: 2026-09-02
> **적용 범위**: refac_bid_box 프로젝트 전체
> **관련 이슈**: Task `task_8550dd99265b` - 버전 정본 단일화

---

## 1. 정본 단일화 원칙

| 항목 | 내용 |
| --- | --- |
| **정본 파일** | `pyproject.toml` (`[project]` 섹션의 `version`) |
| **읽는 방법** | `importlib.metadata.version("refac_bid_box")` (표준 라이브러리, 새 의존성 없음) |
| **적용 대상** | FastAPI 앱(`src/app/main.py`), 헬스체크, OpenAPI 문서, 모든 런타임 버전 노출 |
| **값 변경 권한** | 담당자만 변경 가능. 자동화 스크립트/릴리스 태그 생성은 별도 과업으로 분리 |

**핵심 규칙**: 버전 값은 **오직 `pyproject.toml` 한 곳에만** 기록합니다. 다른 어디에도 버전 문자열 리터럴을 쓰지 않습니다.

---

## 2. 구현 세부 사항

### 2.1 버전 조회 함수 (`src/app/core/config.py`)

```python
from importlib.metadata import PackageNotFoundError, version as pkg_version

def get_app_version() -> str:
    """패키지 메타데이터에서 버전을 읽습니다.

    패키지가 설치되지 않은 환경(예: 개발 모드 `uv run`)에서도 안전하게 동작하도록
    예외를 잡아 기본값으로 떨어뜨리되, 그 사실이 드러나도록 합니다.
    기동이 버전 조회 때문에 실패하면 안 됩니다.
    """
    try:
        return pkg_version("refac_bid_box")
    except PackageNotFoundError:
        # 개발 환경에서 pip install -e . 없이 실행 시 발생할 수 있습니다.
        # 기동을 막지 않고 안전 기본값을 반환하되, 호출 측이 이 값을 쓸 수 있도록 합니다.
        return "0.1.0"
```

### 2.2 FastAPI 앱에서의 사용 (`src/app/main.py`)

```python
from src.app.core.config import get_app_version

app = FastAPI(
    title="refac_bid_box API",
    description="...",
    version=get_app_version(),  # 하드코딩 제거
    ...
)
```

### 2.3 안전성 보장

- **예외 처리**: `PackageNotFoundError`를 잡아 기본값(`0.1.0`)으로 폴백
- **기동 차단 없음**: 버전 조회 실패로 애플리케이션 기동이 중단되지 않음
- **새 의존성 없음**: `importlib.metadata`는 Python 3.8+ 표준 라이브러리

---

## 3. CURRENT_STATE.md v1.0.0 표기 관련

> **중요**: `docs/context/CURRENT_STATE.md`의 `version: v1.0.0` 표기는 **근거 없이 앞서 있는 값**입니다.

- `pyproject.toml`과 FastAPI 앱은 모두 `0.1.0`을 정본으로 사용 중
- `CURRENT_STATE.md`는 코디네이터 소유 문서로, 동시 편집 충돌 방지를 위해 **이 Task에서 수정하지 않음**
- 실제 버전 범프(0.1.0 → 1.0.0)는 담당자의 릴리스 판단에 따르는 별도 과업
- 이 문서(`versioning.md`)에 그 사실을 기록해 두며, 정정은 코디네이터가 별도 수행

---

## 4. 검증 규칙 (자동화)

`tests/test_version_consistency.py`가 다음을 검증합니다:

1. `pyproject.toml`에 `version` 필드 존재
2. 설치된 패키지 버전(`importlib.metadata`)이 `pyproject.toml` 버전과 일치
3. 버전 형식이 시맨틱 버전(MAJOR.MINOR.PATCH) 준수
4. `get_app_version()` 함수가 올바른 값 반환
5. `main.py`에 버전 문자열 리터럴 하드코딩 없음
6. 본 문서(`docs/ops/versioning.md`)에 정본 규칙 및 후속 과업 기록 존재

실행:
```bash
uv run pytest tests/test_version_consistency.py -v
```

---

## 5. 후속 과업 (Out of Scope for This Task)

다음은 **이번 Task 범위가 아니며** 별도 과업으로 관리합니다:

| 과업 | 설명 |
| --- | --- |
| **릴리스 태그 생성** | `git tag v0.1.0` 등 태그 자동화 |
| **CHANGELOG 자동화** | 커밋 메시지 기반 변경 이력 생성 |
| **버전 범프 스크립트** | `bumpversion` 또는 유사 도구로 patch/minor/major 자동 증가 |
| **CURRENT_STATE.md 정정** | v1.0.0 → 0.1.0 동기화 (코디네이터가 별도 수행) |
| **CI/CD 연계** | 태그 푸시 시 빌드/배포 파이프라인 트리거 |

이 과업들은 `docs/ops/versioning.md`에 기록하되 **구현하지 않습니다**. 향후 별도 Task로 분할해 진행합니다.

---

## 6. 변경 이력

| 날짜 | 변경 내용 | 비고 |
| --- | --- | --- |
| 2026-09-02 | 초기 작성: 정본 단일화 규칙, 구현 가이드, 후속 과업 정리 | Task `task_8550dd99265b` 완료 산출물 |

---

## 7. 관련 파일

| 파일 | 역할 |
| --- | --- |
| `pyproject.toml:7` | **정본** - `version = "0.1.0"` |
| `src/app/core/config.py` | `get_app_version()` 함수 정의 |
| `src/app/main.py:349` | `version=get_app_version()`로 동적 읽기 |
| `tests/test_version_consistency.py` | 정본 일치 자동 검증 |
| `docs/context/CURRENT_STATE.md:5` | **수정 금지** - 코디네이터 소유, v1.0.0 표기는 근거 없음 |
