# Tailwind CSS 4 이전 결과

> 작성일: 2026-10-04
> Task: task_87ccc8ccefdf (builder rework)
> 브랜치: kwanbum217/tailwind4-migration
> 범위: 루트 정적 CSS 빌드( `src/app/templates/**/*.html`, `src/app/static/js/**/*.js` ). `frontend/` 는 제외.
> 상태: 완료. 빌드 경로를 `@tailwindcss/postcss` + `postcss-cli` 로 바꿔 braces 를 의존 트리에서 제거했고, allowlist 의 braces 예외를 삭제했으며, v3 전용 Tailwind 시험 2건을 v4 표기로 갱신했습니다.

---

## 1. 요약

루트 정적 CSS 빌드를 `tailwindcss 3.4.16` 에서 `tailwindcss 4.3.3` 로 이전합니다. 1차 시도는 `@tailwindcss/cli 4.3.3` 을 썼지만 그 패키지가 `@parcel/watcher -> micromatch -> braces@3.0.3` 을 끌어와 braces 취약점 예외(GHSA-vfj7-8cjw-p6xm)를 제거할 수 없었습니다. 이번 rework 는 빌드 경로를 `@tailwindcss/postcss 4.3.3` + `postcss-cli 12.0.0` 으로 바꿔 같은 CSS 를 생성하면서 braces 를 트리에서 없앴습니다.

전환 결과 생성 CSS 는 이전 커밋(`@tailwindcss/cli` 산출)과 바이트 단위로 완전히 동일합니다(sha256 `a5d254d424201c05ac449c564607e3d7efdea89ef0bf95a61da5c6e3e68c5459`, 63,653 바이트). 즉 화면 모양을 바꾸는 산출 차이가 전혀 없고, 바뀐 것은 패키지·빌드 명령·설정 파일·allowlist·시험뿐입니다. 클래스 선택자 집합 비교에서 이름 변경으로 설명되지 않는 누락은 0건입니다.

---

## 2. 바꾼 파일

이번 rework 커밋(b65988eb 이후)에서 바꾼 파일입니다.

| 파일 | 변경 |
| --- | --- |
| `package.json` | devDependency 를 `tailwindcss 4.3.3`, `@tailwindcss/postcss 4.3.3`, `postcss 8.5.28`, `postcss-cli 12.0.0` 정확 고정. `@tailwindcss/cli` 제거. `build:css` 를 `postcss ... --no-map` 로 교체 |
| `package-lock.json` | npm 으로 재생성(braces, micromatch 제거) |
| `postcss.config.mjs` | 신규. `@tailwindcss/postcss` 플러그인에 `optimize: { minify: true }` 지정 |
| `src/app/static/css/tailwind.css` | 재생성했으나 이전 커밋 산출과 바이트 동일하여 변경 없음 |
| `.github/vulnerability-allowlist.yml` | npm 항목 `GHSA-vfj7-8cjw-p6xm`(braces) 삭제. `npm: []` |
| `tests/test_tailwind_build.py` | v3 전용 표기 전제 시험 2건을 v4 산출 표기로 갱신 |
| `docs/analysis/tailwind4_migration_result_20261004.md` | 본 문서 갱신 |

1차 시도 커밋(b65988eb)에서 이미 반영된 파일은 그대로 유지합니다. `tailwind.input.css`(`@import "tailwindcss" source(none)` + `@source` 2개 + `@custom-variant dark` + `@theme` 토큰 + `@layer base` 호환 규칙 + `@utility` 2개), 템플릿 11개와 `src/app/static/js/chat.js` 의 이름 변경 유틸리티 치환, `tailwind.config.js`(시험 검증용으로 보존)입니다.

---

## 3. 설정 방식 선택과 이유

### 3.1 CSS 우선 `@theme` (JS `@config` 대신)

`@config` 로 기존 JS 설정을 읽는 대신 CSS 우선 `@theme` 를 선택했습니다.

1. v4 는 JS 설정의 사용자 정의 `content.extract`(Django 템플릿 태그 제거)를 지원하지 않습니다. `@config` 로 읽어도 추출 방식은 v4 기본 추출기로 대체되므로 이전 목적을 달성하지 못합니다.
2. 그래서 `build:css` 에서 `-c tailwind.config.js` 를 제거하고, 입력 CSS 에서 `@source` 로 탐지 범위를 명시했습니다.
3. `@import "tailwindcss" source(none)` 으로 자동 소스를 끄고 `@source "../../templates/**/*.html"`, `@source "../../static/js/**/*.js"` 두 경로만 스캔하게 했습니다. 이 조치가 없으면 v4 가 저장소 전체를 자동 스캔해 `docs/` 등 문서의 예시 클래스까지 생성합니다(수정 전 산출물 89,489 바이트, 수정 후 63,653 바이트).
4. `@source` 경로는 입력 CSS 파일(`src/app/static/css/`) 기준 상대 경로입니다.

`@theme` 로 옮긴 토큰은 `primary` 3색, `harness` 5색, `enterprise` 반경, `h-sm`/`h-md` 그림자입니다. `darkMode: 'class'` 는 `@custom-variant dark (&:where(.dark, .dark *))` 로 유지했습니다. 입력 CSS 의 사용자 정의 유틸리티 두 개는 `@utility` 로 옮겼고, v4 가 같은 클래스에 대해 `border-color`/`color` 규칙을 생성합니다.

### 3.2 빌드 경로를 `@tailwindcss/postcss` + `postcss-cli` 로 바꾼 이유

`@tailwindcss/cli 4.3.3` 은 CSS 컴파일러 자체는 `@tailwindcss/node`/`@tailwindcss/oxide` 를 쓰지만, 파일 감시를 위해 `@parcel/watcher@2.5.1` 을 함께 의존하고 그 하위의 `micromatch@4.0.8` 이 다시 `braces@3.0.3`(수정판 없음, GHSA-vfj7-8cjw-p6xm)을 끌어옵니다. `@tailwindcss/postcss 4.3.3` 은 같은 컴파일러를 쓰되 `@parcel/watcher` 를 의존하지 않으므로 braces 가 트리에서 사라집니다.

`postcss.config.mjs` 한 파일에 설정을 둡니다.

```js
export default {
  plugins: {
    '@tailwindcss/postcss': {
      optimize: { minify: true },
    },
  },
};
```

`build:css` 는 스크립트 이름과 입력·출력 경로를 유지합니다.

```text
postcss src/app/static/css/tailwind.input.css -o src/app/static/css/tailwind.css --no-map
```

- `optimize: { minify: true }`: CLI 의 `--minify` 와 같은 압축을 켜되 `NODE_ENV` 와 무관하게 결정적으로 동작하도록 명시했습니다. 결과는 CLI `--minify` 산출과 바이트 단위로 같습니다.
- `--no-map`: `postcss-cli` 는 기본으로 인라인 소스맵을 붙입니다. CLI 산출에는 없던 `sourceMappingURL` 주석이 들어가면 재현성·바이트 비교가 깨지므로 끕니다.
- 끝 개행: `postcss-cli` 가 이미 산출 끝에 개행 1개를 붙입니다. CLI 시절의 `printf '\n'` 를 그대로 두면 개행이 2개가 되어 커밋 산출과 1바이트 어긋나므로 제거했습니다. 최종 파일은 여전히 정확히 개행 1개로 끝납니다.

### 3.3 호환 기본 스타일

`@layer base` 에 v3 기본값을 재현하는 규칙을 넣었습니다. `border-color: var(--color-gray-200, currentColor)`(v3 기본 border 색), `button`/`[type=button]`/`[type=reset]`/`[type=submit]` 의 `cursor: pointer`, `input`/`textarea` placeholder `var(--color-gray-400)` 입니다. 주의: `theme(colors.gray.200)` 같은 v3 `theme()` 경로 표기는 v4 에서 해석되지 않아 CSS 변수 표기로 썼습니다.

---

## 4. 이전 전후 선택자 비교

| 항목 | 값 |
| --- | ---: |
| 이전(v3) 클래스 선택자 수 | 627 |
| 이후(v4) 클래스 선택자 수 | 627 |
| 이름 변경으로 설명되는 변경 토큰 수(고유) | 6 |
| 이름 변경 후 기대 집합 크기 | 626 |
| 설명되지 않는 누락 수 | 0 |
| 이후에만 있는 추가 선택자 수 | 1 (`.rounded`, 아래 설명) |

`설명되지 않는 누락 0` 은 v3 산출에 있던 클래스 선택자가 v4 산출에서 이름 변경으로 설명되지 않고 사라진 경우가 없다는 뜻입니다. 비교는 `git show main:src/app/static/css/tailwind.css` 를 v3 로 두고 수행합니다. 아래 명령은 클래스 선택자만 뽑아 v3 토큰에 공식 이름 변경 표를 적용한 뒤 v4 집합에서 사라진 것을 셉니다. 치환은 마지막 `:` 뒤 기본 유틸리티에만 적용해 `shadow`/`shadow-sm` 같은 이중 치환을 막습니다.

```sh
git show main:src/app/static/css/tailwind.css > /tmp/v3.css
python3 - src/app/static/css/tailwind.css <<'PY'
import re, sys
TOKEN = re.compile(r'\.((?:\\(?:[0-9a-fA-F]{1,6} ?|.)|[A-Za-z0-9_-])+)')
def unesc(t):
    t = re.sub(r'\\([0-9a-fA-F]{1,6}) ', lambda m: chr(int(m.group(1), 16)), t)
    return re.sub(r'\\(.)', r'\1', t)
def extract(css):
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    prev = None
    while prev != css:
        prev = css; css = re.sub(r'\{[^{}]*\}', '{}', css)
    return {unesc(m.group(1)) for m in TOKEN.finditer(css)}
EXACT = {'shadow-sm':'shadow-xs','shadow':'shadow-sm','drop-shadow-sm':'drop-shadow-xs',
         'drop-shadow':'drop-shadow-sm','blur-sm':'blur-xs','blur':'blur-sm',
         'backdrop-blur-sm':'backdrop-blur-xs','backdrop-blur':'backdrop-blur-sm',
         'rounded-sm':'rounded-xs','rounded':'rounded-sm','outline-none':'outline-hidden',
         'ring':'ring-3','overflow-ellipsis':'text-ellipsis'}
PREFIX = {'flex-shrink-':'shrink-','flex-grow-':'grow-'}
def rename(t):
    p = t.split(':'); b = p[-1]
    if b in EXACT: b = EXACT[b]
    else:
        for o, n in PREFIX.items():
            if b.startswith(o): b = n + b[len(o):]; break
    p[-1] = b; return ':'.join(p)
v3 = extract(open('/tmp/v3.css', encoding='utf-8').read())
v4 = extract(open(sys.argv[1], encoding='utf-8').read())
expected = {rename(t) for t in v3}
missing = sorted(expected - v4)
extra = sorted(v4 - expected)
print(f'v3={len(v3)} v4={len(v4)} expected={len(expected)} renamed={sum(1 for t in v3 if rename(t)!=t)}')
print(f'unexplained_missing={len(missing)}')
print(f'v4_only={len(extra)} -> {extra}')
PY
```

출력은 `v3=627 v4=627 expected=626 renamed=6`, `unexplained_missing=0`, `v4_only=1 -> ['rounded']` 입니다.

이름 변경으로 설명되는 고유 토큰은 v3 기준 `shadow-sm`, `rounded`, `outline-none`, `backdrop-blur-sm`, `flex-shrink-0`, `focus:outline-none` 6개입니다. `v4_only` 의 `rounded` 는 v4 기본 추출기가 `src/app/static/js/chat.js` 의 지역 변수 이름 `rounded`(433행, `Math.round` 결과 변수)를 클래스 후보로 잡은 집합차 부산물입니다. `.rounded{border-radius:.25rem}` 규칙은 v3 산출에도 동일하게 존재하므로 화면에 새로 생기는 효과가 아닙니다. 템플릿 쪽 `rounded` 38회는 모두 v4 이름 `rounded-sm` 으로 치환되어 클래스 `rounded` 를 쓰는 요소는 없습니다.

치환 토큰 수(변경 라인 기준)는 `shadow-sm` 46, `rounded` 38, `outline-none` 26, `backdrop-blur-sm` 4, `flex-shrink-0` 5 이며, 모든 변경 라인이 `class=` 속성 안에서만 바뀌었습니다(`git diff -U0 -- src/app/templates src/app/static/js | grep -E '^[+-][^+-]' | grep -v 'class='` 결과 0줄).

---

## 5. 산출물 크기

| 시점 | `src/app/static/css/tailwind.css` |
| --- | ---: |
| 이전(v3, main) | 44,081 바이트 |
| 이후(v4, source(none) + @source 2경로) | 63,653 바이트 |

v4 는 `@layer properties` 폴백 블록과 opacity modifier 용 `color-mix` 폴백을 함께 내보내므로 파일이 커집니다. v4 자동 소스를 켠 중간 산출물은 89,489 바이트였고, 탐지 범위를 두 경로로 좁혀 63,653 바이트가 되었습니다. 이전 커밋(`@tailwindcss/cli` 산출)과 rework(`postcss`) 산출은 63,653 바이트로 sha256 까지 동일합니다.

---

## 6. braces 조사와 예외 제거

`@tailwindcss/cli` 를 제거하고 `@tailwindcss/postcss` + `postcss-cli` 로 바꾼 뒤의 결과입니다.

```text
$ env -u NODE_ENV npm ls braces --all
refac-bid-box-static@
└── (empty)

$ env -u NODE_ENV npm ls micromatch --all
refac-bid-box-static@
└── (empty)

$ env -u NODE_ENV npm audit --audit-level=high
found 0 vulnerabilities
```

- braces 와 micromatch 가 루트 의존성 트리에서 완전히 사라졌습니다. 수정판이 없는 취약 버전도 남지 않았습니다.
- 따라서 `.github/vulnerability-allowlist.yml` 의 npm 항목 `GHSA-vfj7-8cjw-p6xm`(braces)을 삭제하고 `npm: []` 로 두었습니다.
- `uv run python scripts/check_vulnerability_allowlist.py` 통과: 남은 3건은 python chromadb 항목이며 전부 사유와 유효한 만료일을 가집니다.
- 참고: 이 환경은 `NODE_ENV=production` 이라 `npm ls`/`npm audit` 이 dev 의존성을 생략합니다. dev 를 포함해 확인하려면 `NODE_ENV` 를 해제하거나 `--include=dev` 를 씁니다. CI(GitHub Actions)는 `NODE_ENV` 가 없어 dev 가 포함된 트리로 스캔합니다.

---

## 7. 사람이 브라우저로 확인할 화면

이전 전 상태와 픽셀을 눈으로 비교할 화면과 주목할 클래스입니다. 산출 CSS 가 바이트 동일하므로 v3 대비 시각 회귀는 없어야 하지만, 기본값 변경 항목은 실제 브라우저에서 확인합니다.

| 화면(템플릿) | 확인할 클래스 / 지점 |
| --- | --- |
| `src/app/templates/base.html` | 전역 기본 border 색이 `gray-200` 인지(색 미지정 `border`), 버튼 `cursor: pointer` |
| `src/app/templates/index.html` | `shadow-xs`(구 `shadow-sm`) 카드 그림자, `rounded-[26px]`, `xl:grid-cols-[minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.1fr)]` |
| `src/app/templates/bids/list.html` | `rounded-sm`(구 `rounded`) 페이지네이션, `outline-hidden`(구 `outline-none`) 입력 포커스, `space-x-2` 간격 |
| `src/app/templates/bids/results.html` | `shadow-xs` 로딩 카드, `rounded-sm` 배지 |
| `src/app/templates/bids/dashboard.html`, `detail.html`, `compare.html`, `result_detail.html` | `rounded-sm`, `shadow-xs`, `outline-hidden` |
| `src/app/templates/chatbot/chat.html` | `shrink-0`(구 `flex-shrink-0`) 헤더 고정, `backdrop-blur-xs`(구 `backdrop-blur-sm`), `focus:outline-hidden`, `rounded-sm` 배지 |
| `src/app/static/js/chat.js` | 스트리밍 말풍선 `shadow-xs`, 아이콘 `rounded-sm`, `shrink-0`; `formatChartValue` 정상 동작 |

`hover:` 상태와 `space-x/y` 인접 자식 간격은 정적 비교로 확인이 어려우므로 위 화면에서 마우스 hover 와 목록 간격을 함께 봐야 합니다.

---

## 8. 시험 갱신

`tests/test_tailwind_build.py` 의 v3 전용 표기 전제 2건을 v4 산출 표기로 갱신했습니다. 시험의 의도(사용자 정의 테마 토큰과 템플릿 유틸리티가 산출물에 존재)는 유지했고, 검사 대상 토큰 수를 줄이거나 단언을 삭제하지 않았습니다.

- `test_custom_theme_tokens_in_build_css`: v3 는 커스텀 색을 `rgb(0 115 230)` 같은 공백 구분 triplet 으로 출력했지만 v4 는 `--color-primary:#0073e6` 처럼 소문자 hex 로 정규화합니다. 검사 대상을 같은 4개 토큰(primary DEFAULT·hover, harness sidebar·border)의 v4 변수 선언 표기로 바꿨습니다.
- `test_template_tailwind_utilities_exist_in_build_css`: 임의값의 쉼표를 v3 는 `\2c ` 로, v4 는 `\,` 로 이스케이프합니다. 선택자 생성 함수 `_tailwind_minified_selector` 의 쉼표 이스케이프를 `\,` 로 고쳐 `grid-cols-[auto_minmax(0,1fr)]`, `xl:grid-cols-[minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.1fr)]` 두 클래스가 정상 검출되게 했습니다.

---

## 9. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `env -u NODE_ENV npm ci` | exit 0. 52 packages, 0 vulnerabilities |
| `env -u NODE_ENV npm run build:css` + `git diff --exit-code -- src/app/static/css/tailwind.css` | exit 0. 클린 설치 후 재빌드가 커밋 산출물과 바이트 동일 |
| `NODE_ENV=production npm run build:css` + 같은 diff 검사 | exit 0. `NODE_ENV` 와 무관하게 결정적 |
| 선택자 비교(4장 명령) | v3=627 v4=627, 설명되지 않는 누락 0 |
| `env -u NODE_ENV npm ls braces --all` | 빈 결과(braces 제거) |
| `env -u NODE_ENV npm ls micromatch --all` | 빈 결과 |
| `env -u NODE_ENV npm audit --audit-level=high` | found 0 vulnerabilities |
| `uv run python scripts/check_vulnerability_allowlist.py` | 통과(3건, 전부 사유·유효 만료일 보유) |
| `uv run pytest tests/test_tailwind_build.py -q` | 6 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 1 failed, 6013 passed, 40 skipped, 3 deselected. 실패 1건은 아래 참조 |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과 21/21 |

미해결 실패 1건은 `tests/test_result_coverage.py::test_task_notifies_only_when_alert`(assert 0 == 1)입니다. 이 시험과 그 실행 경로(`tests/test_result_coverage.py`, `src/tasks/coverage_tasks.py`, `src/tasks/scheduled_tasks.py`, `src/app/core/cache.py`)는 `git diff main...HEAD` 에서 변경이 없어 main 과 동일한 코드이며, Tailwind 이전과 무관한 기존 환경 실패입니다. 범위 밖이라 고치지 않았습니다.
