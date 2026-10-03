# Tailwind CSS 4 이전 영향 조사

> 조사일: 2026-10-03
> 범위: 루트 Tailwind 빌드, `src/app/templates/**/*.html`, `src/app/static/js/**/*.js`
> 결론: 이전 자체는 수행하지 않았습니다. `frontend/`는 범위에서 제외했습니다.

## 1. 현재 빌드 기준선

루트 `package.json`은 `tailwindcss`를 `3.4.16`으로 고정하고 `build:css`에서 `tailwindcss -c tailwind.config.js -i src/app/static/css/tailwind.input.css -o src/app/static/css/tailwind.css --minify`를 실행합니다. 설정의 `content.files`는 템플릿과 정적 JS를 스캔하며, 템플릿 HTML에는 사용자 정의 추출기가 설정되어 있습니다. 빌드 산출물은 `src/app/static/css/tailwind.css`이며 커밋 대상입니다.

CI의 `Install Tailwind Toolchain` 단계는 `npm ci`를 수행하고, `Verify Tailwind CSS Reproducibility` 단계는 `npm run build:css` 후 `git diff --exit-code -- src/app/static/css/tailwind.css`로 커밋 산출물과의 일치를 확인합니다. 따라서 v4 전환 시 패키지와 잠금 파일, 빌드 명령, 설정 및 입력 CSS를 함께 바꾸고, CI에서 새 산출물을 생성해 커밋해야 합니다. 이전 후에도 재현성 검사는 같은 방식으로 유지해야 합니다.

## 2. 유틸리티 이름 변경 및 제거 영향

아래 횟수는 두 지정 경로의 정적 `class`, `className`, `classes` 따옴표 문자열에 들어 있는 유틸리티 토큰 수이며, 파일 수는 하나 이상 포함한 파일 수입니다. 변형 접두사(예: `hover:`) 뒤의 기본 유틸리티를 세며, 접두사가 더 긴 다른 유틸리티에 포함된 경우는 별도 토큰으로 취급합니다.

| v3 유틸리티 | v4 대응/상태 | 사용 횟수 | 파일 수 |
| --- | --- | ---: | ---: |
| `shadow-sm` | `shadow-xs` | 45 | 9 |
| `shadow` | `shadow-sm` | 0 | 0 |
| `drop-shadow-sm` | `drop-shadow-xs` | 0 | 0 |
| `drop-shadow` | `drop-shadow-sm` | 0 | 0 |
| `blur-sm` | `blur-xs` | 0 | 0 |
| `blur` | `blur-sm` | 0 | 0 |
| `backdrop-blur-sm` | `backdrop-blur-xs` | 4 | 3 |
| `backdrop-blur` | `backdrop-blur-sm` | 0 | 0 |
| `rounded-sm` | `rounded-xs` | 0 | 0 |
| `rounded` | `rounded-sm` | 38 | 10 |
| `outline-none` | `outline-hidden` | 26 | 7 |
| `ring` | `ring-3` | 0 | 0 |
| `bg-opacity-*` | 제거 | 0 | 0 |
| `text-opacity-*` | 제거 | 0 | 0 |
| `border-opacity-*` | 제거 | 0 | 0 |
| `divide-opacity-*` | 제거 | 0 | 0 |
| `ring-opacity-*` | 제거 | 0 | 0 |
| `placeholder-opacity-*` | 제거 | 0 | 0 |
| `flex-shrink-*` | 제거, `shrink-*` 사용 | 5 | 2 |
| `flex-grow-*` | 제거, `grow-*` 사용 | 0 | 0 |
| `overflow-ellipsis` | 제거, `text-ellipsis` 사용 | 0 | 0 |
| `decoration-slice` | 제거 | 0 | 0 |
| `decoration-clone` | 제거 | 0 | 0 |

현재 실측상 치환이 필요한 이름 변경은 `shadow-sm` 45회, `backdrop-blur-sm` 4회, `rounded` 38회, `outline-none` 26회, `flex-shrink-*` 5회입니다. 이름 변경 표의 각 행 수는 아래 명령으로 재현합니다. 명령은 현재 조사일의 경로만 읽으며, `rg` PCRE2의 좌우 부정형 경계로 `shadow-sm`과 `shadow`를 구분합니다.

```sh
python3 - <<'PY'
from pathlib import Path
import re

files = sorted(
    list(Path('src/app/templates').glob('**/*.html'))
    + list(Path('src/app/static/js').glob('**/*.js'))
)
classes = []
for path in files:
    source = path.read_text(errors='replace')
    for match in re.finditer(
        r'\bclass(?:Name|es)?\s*[:=]\s*["\'`]([^"\'`$]*)(?:\$\{[^}]*\}[^"\'`]*)?["\'`]',
        source,
    ):
        classes.extend((path, token) for token in re.findall(r'[^\s]+', match.group(1)))

renamed = [
    'shadow-sm', 'shadow', 'drop-shadow-sm', 'drop-shadow', 'blur-sm', 'blur',
    'backdrop-blur-sm', 'backdrop-blur', 'rounded-sm', 'rounded', 'outline-none', 'ring',
]
removed = [
    'bg-opacity-', 'text-opacity-', 'border-opacity-', 'divide-opacity-', 'ring-opacity-',
    'placeholder-opacity-', 'flex-shrink-', 'flex-grow-', 'overflow-ellipsis',
    'decoration-slice', 'decoration-clone',
]
for utility in renamed + removed:
    hits = []
    for path, token in classes:
        base = token.split(':')[-1].lstrip('!-')
        if (base.startswith(utility) if utility.endswith('-') else base == utility):
            hits.append((path, token))
    print(f'{utility}: {len(hits)} occurrences, {len({path for path, _ in hits})} files')
PY
```

## 3. 기본값 변경 영향 사용처

| 변경 항목 | 실측 사용처 | 파일 수 | 해석 |
| --- | ---: | ---: | --- |
| 기본 `border` 색상 `gray-200` → `currentColor` | `border` 144회 | 12 | 색상을 명시하지 않은 테두리 유틸리티 |
| 기본 `ring` 색상 `blue-500` → `currentColor` | bare `ring` 0회 | 0 | `ring-2`, `ring-4`, `ring-primary`처럼 명시적 폭/색상은 기본 `ring` 사용으로 세지 않음 |
| 버튼 기본 커서 `pointer` → `default` | `<button>` 태그 38개 | 11 | 버튼 요소의 기본 커서가 변경될 수 있음 |
| `space-x-*` / `space-y-*` 선택자 변경 | 103회 | 12 | 인접 자식 선택자에 의존하는 배치이므로 양쪽 자식 간격 및 역순 배치 확인 필요 |
| hover 변형의 기기 조건 변경 | `hover:` 토큰 111회 | 12 | hover 가능한 기기에서만 적용되므로 터치 사용 시 hover만으로 제공하는 상태 피드백 점검 필요 |

집계 재현용 명령은 다음과 같습니다. `border`는 정확히 bare 유틸리티만 세고, 버튼 태그는 HTML 텍스트에서 세며, `space-*`와 hover는 변형 접두사를 포함한 클래스 토큰을 셉니다.

```sh
python3 - <<'PY'
from pathlib import Path
import re

files = sorted(
    list(Path('src/app/templates').glob('**/*.html'))
    + list(Path('src/app/static/js').glob('**/*.js'))
)
classes = []
for path in files:
    source = path.read_text(errors='replace')
    for match in re.finditer(
        r'\bclass(?:Name|es)?\s*[:=]\s*["\'`]([^"\'`$]*)(?:\$\{[^}]*\}[^"\'`]*)?["\'`]',
        source,
    ):
        classes.extend((path, token) for token in re.findall(r'[^\s]+', match.group(1)))

queries = {
    'bare-border': lambda token: token.split(':')[-1].lstrip('!-') == 'border',
    'bare-ring': lambda token: token.split(':')[-1].lstrip('!-') == 'ring',
    'space-x/y': lambda token: token.split(':')[-1].lstrip('!-').startswith(('space-x-', 'space-y-')),
    'hover': lambda token: 'hover:' in token,
}
for label, predicate in queries.items():
    hits = [(path, token) for path, token in classes if predicate(token)]
    print(f'{label}: {len(hits)} occurrences, {len({path for path, _ in hits})} files')
buttons = [(path, len(re.findall(r'<button\b', path.read_text(errors='replace'), re.I))) for path in files]
buttons = [(path, count) for path, count in buttons if count]
print(f'button tags: {sum(count for _, count in buttons)} occurrences, {len(buttons)} files')
PY
```

정적 문자열로 탐지되지 않는 실행 시 조합 클래스는 위 사용량 집계에 포함되지 않습니다. 반대로 `border` 기본색 변경은 단순히 bare `border`로 선언된 사용처 수이지 화면에서 실제 회색 테두리가 보이는 요소 수와 같지는 않습니다. 이전 후 브라우저 확인에서 색상 상속과 자식 조합 선택자를 확인해야 합니다.

## 4. 설정 및 입력 CSS 영향

| 현재 기능 | 현재 설정 | v4 전환 지점 |
| --- | --- | --- |
| `theme.extend` | `primary`, `harness` 색상, `enterprise` 반경, `h-sm`/`h-md` 그림자 | CSS 우선 설정으로 옮겨 `@theme` 토큰을 정의합니다. 필요하면 호환 목적으로 JS 설정을 `@config`로 명시 로드합니다. |
| `plugins` | 빈 배열 | 현재 플러그인 마이그레이션은 없습니다. 향후 플러그인을 추가할 때 v4 호환 여부를 확인합니다. |
| `content.files` | 템플릿과 정적 JS 두 경로 | v4 자동 소스 탐지 또는 `@source`로 두 경로가 포함되는지 명시하고 빌드 산출물에서 확인합니다. |
| 사용자 정의 HTML `extract` | `class="..."` 추출 및 Django 템플릿 태그 제거 | v4에서 동일한 사용자 정의 추출 동작을 보장하는지 확인이 필요합니다. 자동 탐지로 동적/템플릿 클래스가 빠지면 `@source inline()` 등으로 보완하거나 추출 전략을 재설계합니다. |
| `blocklist` | `!container` 차단 | v4 설정 호환 여부와 차단 필요성을 확인합니다. 잘못 추출되는 토큰의 원인이 제거되면 설정도 불필요할 수 있습니다. |
| `@tailwind` 지시문 | `base`, `components`, `utilities` 세 줄 | `@import "tailwindcss";`로 통합합니다. |
| `@layer utilities` | 사용자 정의 `border-white/12`, `text-blue-100/72` 유틸리티 | v4의 CSS 우선 사용자 정의 유틸리티 규칙으로 등록하고 기존 클래스가 같은 CSS를 생성하는지 비교합니다. |
| `@apply` | 입력 파일에서 사용 없음 | 현재 이전 항목 없음. |

`tailwind.config.js`에서 사용 중인 설정 기능은 `darkMode: 'class'`, `blocklist`, `content.files`, `content.extract.html`, `theme.extend` 및 빈 `plugins`입니다. CSS 입력은 세 `@tailwind` 지시문과 두 규칙을 선언한 `@layer utilities`를 사용합니다. `@apply`는 입력 CSS에 나타나지 않습니다.

## 5. 패키지·CLI·CI 변경점

v4는 CLI를 별도 `@tailwindcss/cli` 패키지로 분리하므로, 전환 시 루트 `devDependencies`, lockfile, CI의 `npm ci`, `build:css` 명령을 같은 변경 단위로 맞춰야 합니다. CSS 입력을 `@import "tailwindcss"`로 바꾸고 JS 설정을 유지한다면 CSS 안에서 `@config` 경로를 지정해야 합니다. 산출 CSS 생성 순서와 후행 개행 동작이 바뀌지 않는지도 확인해야 합니다.

CI는 현재 커밋된 Tailwind 산출물을 재빌드해 바이트 단위로 대조합니다. 전환 PR/커밋에서 새 `tailwind.css`를 생성하여 포함하고, 클린 체크아웃의 `npm ci && npm run build:css && git diff --exit-code -- src/app/static/css/tailwind.css`가 성공해야 합니다. CI 검증 명령과 입력 파일이 새 v4 경로를 실제 사용하는지 확인한 뒤에만 이전 완료로 판단할 수 있습니다.

## 6. 작업량 및 권장 순서

| 추정 항목 | 현재 실측/추정 |
| --- | --- |
| 조사 대상 소스 | 템플릿 11개 + 정적 JS 1개 = 12개 파일 |
| 이름 치환 | 약 118회 (위 표에서 45 + 4 + 38 + 26 + 5) |
| 기본 동작 시각 점검 후보 | bare border 144회, space 103회, hover 111회, 버튼 38개 |
| 빌드 설정/입력 | `package.json`, lockfile, `tailwind.config.js`, `tailwind.input.css`, CI 워크플로, 생성 CSS 등 최소 6개 파일과 생성물 |
| 추정 불확실성 | 템플릿 변수로 런타임 조립되는 클래스와 Tailwind 생성 CSS 크기는 별도 탐지가 필요 |

권장 순서는 다음과 같습니다.

1. 지원 브라우저 범위를 먼저 결정합니다.
2. v4 CLI 및 `@config`/`@theme`/`@source`를 적용하고, 소스 탐지 결과를 먼저 비교합니다.
3. 설정·지시문 변환 뒤 빌드가 되는지 확인하고 사용자 정의 유틸리티 두 개를 검사합니다.
4. 이름 변경 약 118회를 적용하고 클래스 추출 누락을 보완합니다.
5. border/ring 색상, 버튼 커서, space 선택자 및 hover 조건을 화면별로 확인합니다.
6. `tailwind.css`를 재생성하여 CI 재현성 검사를 통과시킵니다.

공식 업그레이드 안내의 지원 기준은 Safari 16.4+, Chrome 111+, Firefox 128+입니다. 이 범위를 제품 지원 기준으로 채택할지, 구형 브라우저를 포함해야 하는지 전환 착수 전에 결정해야 합니다.

## 7. 사전 결정 및 조사 제한

- 지원 브라우저 범위를 확정해야 합니다. v4의 최소 버전을 받아들일 수 없으면 별도 호환성 전략을 먼저 결정해야 합니다.
- 레거시 HTML 추출기의 Django 템플릿 문법 처리와 `blocklist` 동작을 v4 빌드에서 확인해야 합니다.
- 정적 클래스 문자열 기반 집계이므로 실행 중 조합되는 클래스 수, 시각적 영향, 생성 CSS의 용량 변화는 이 조사에서 측정하지 않았습니다.
- 이 문서는 영향 조사이며 Tailwind 의존성, 설정, 템플릿, 생성 CSS를 수정하거나 실제 v4 빌드를 수행하지 않았습니다.
