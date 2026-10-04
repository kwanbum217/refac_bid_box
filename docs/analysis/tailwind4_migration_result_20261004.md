# Tailwind CSS 4 이전 결과

> 작성일: 2026-10-04
> Task: task_87ccc8ccefdf (builder)
> 브랜치: kwanbum217/tailwind4-migration
> 범위: 루트 정적 CSS 빌드( `src/app/templates/**/*.html`, `src/app/static/js/**/*.js` ). `frontend/` 는 제외.
> 상태: 이전 자체는 완료. braces 예외는 제거 불가로 escalation, 기존 Tailwind 시험 2건은 v3 전용 표기 전제라 실패.

---

## 1. 요약

빌드 도구를 `tailwindcss 3.4.16` 에서 `tailwindcss 4.3.3` + `@tailwindcss/cli 4.3.3` 정확 고정으로 이전했습니다. 입력 CSS 를 `@import "tailwindcss" source(none)` + `@source` 두 경로 기반으로 바꾸고, `theme.extend` 는 `@theme` 토큰으로, `darkMode: 'class'` 는 `@custom-variant dark` 로 옮겼습니다. v4 기본값 변경(border 기본색, button cursor, placeholder 색)은 `@layer base` 호환 규칙으로 v3 와 같게 맞췄고, 이름 변경 유틸리티 118회(중복 제거 후 실제 치환 대상)를 공식 표대로 치환했습니다.

이전 전후 생성 CSS 의 클래스 선택자 집합을 비교한 결과 이름 변경으로 설명되지 않는 누락은 0건입니다. 다만 기존 `tests/test_tailwind_build.py` 두 시험은 v3 의 색상 표기(rgb triplet)와 임의값 이스케이프(`\2c`)를 그대로 전제하므로 v4 산출물에서 실패합니다. 두 시험 수정은 허용된 쓰기 범위(`allowed_write_files`) 밖이라 escalation 합니다. braces 취약점 예외도 남습니다.

---

## 2. 바꾼 파일

| 파일 | 변경 |
| --- | --- |
| `package.json` | `build:css` 에서 `-c tailwind.config.js` 제거, devDependency 를 `tailwindcss 4.3.3`, `@tailwindcss/cli 4.3.3` 정확 고정 |
| `package-lock.json` | npm 으로 재생성 |
| `src/app/static/css/tailwind.input.css` | `@import "tailwindcss" source(none)` + `@source` 2개, `@custom-variant dark`, `@theme` 토큰, `@layer base` 호환 규칙, `@utility` 2개 |
| `src/app/static/css/tailwind.css` | v4 로 재생성한 커밋 산출물 |
| `src/app/templates/**/*.html` (11개) | 이름 변경 유틸리티 치환(class 토큰만) |
| `src/app/static/js/chat.js` | 이름 변경 유틸리티 치환(class 토큰만) 및 지역 변수 `rounded` 원복 |
| `.github/vulnerability-allowlist.yml` | braces 예외 유지(사유 갱신) |

`tailwind.config.js` 는 빌드에서 더 이상 읽지 않지만 `tests/test_tailwind_build.py` 가 값을 검증하므로 그대로 두었습니다.

---

## 3. 설정 방식 선택과 이유

`@config` 로 기존 JS 설정을 읽는 대신 CSS 우선 `@theme` 를 선택했습니다.

1. v4 는 JS 설정의 사용자 정의 `content.extract`(Django 템플릿 태그 제거)를 지원하지 않습니다. `@config` 로 읽어도 추출 방식은 v4 기본 추출기로 대체되므로 이전 목적을 달성하지 못합니다.
2. 그래서 `package.json` 의 `build:css` 에서 `-c tailwind.config.js` 를 제거하고, 입력 CSS 에서 `@source` 로 탐지 범위를 명시했습니다.
3. `@import "tailwindcss" source(none)` 으로 자동 소스를 끄고 `@source "../../templates/**/*.html"`, `@source "../../static/js/**/*.js"` 두 경로만 스캔하게 했습니다. 이 조치가 없으면 v4 가 저장소 전체를 자동 스캔해 `docs/` 등 문서의 예시 클래스까지 생성합니다(수정 전 산출물 89,489 바이트, 수정 후 63,653 바이트).
4. `@source` 경로는 입력 CSS 파일(`src/app/static/css/`) 기준 상대 경로입니다.

`@theme` 로 옮긴 토큰은 `primary` 3색, `harness` 5색, `enterprise` 반경, `h-sm`/`h-md` 그림자입니다. `darkMode: 'class'` 는 `@custom-variant dark (&:where(.dark, .dark *))` 로 유지했습니다. 입력 CSS 의 사용자 정의 유틸리티 두 개는 `@utility` 로 옮겼고, v4 가 같은 클래스에 대해 `border-color`/`color` 규칙을 생성합니다.

호환 기본 스타일은 `@layer base` 에 넣었습니다. `border-color: var(--color-gray-200, currentColor)`(v3 기본 border 색), `button`/`[type=button]`/`[type=reset]`/`[type=submit]` 의 `cursor: pointer`, `input`/`textarea` placeholder `var(--color-gray-400)` 입니다. 주의: `theme(colors.gray.200)` 같은 v3 `theme()` 경로 표기는 v4 에서 해석되지 않아 산출물에 회색이 나오지 않았고, CSS 변수 표기로 고쳤습니다.

---

## 4. 이전 전후 선택자 비교

| 항목 | 값 |
| --- | ---: |
| 이전(v3) 클래스 선택자 수 | 627 |
| 이후(v4) 클래스 선택자 수 | 627 |
| 이름 변경으로 설명되는 변경 토큰 수(고유) | 6 |
| 이름 변경 후 기대 집합 크기 | 626 |
| 설명되지 않는 누락 수 | 0 |
| 이후에만 있는 추가 선택자 수 | 1 (`.rounded`, JS 지역 변수 스캔 부산물) |

비교는 `git show main:src/app/static/css/tailwind.css` 를 v3 로 두고 수행했습니다. 아래 명령은 클래스 선택자만 뽑아 v3 토큰에 공식 이름 변경 표를 적용한 뒤, v4 집합에서 사라진 것을 셉니다. 치환은 마지막 `:` 뒤 기본 유틸리티에만 적용해 `shadow`/`shadow-sm` 같은 이중 치환을 막습니다.

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
print(f'v3={len(v3)} v4={len(v4)} expected={len(expected)} renamed={sum(1 for t in v3 if rename(t)!=t)}')
print(f'unexplained_missing={len(missing)}')
for t in missing: print('  MISSING', t)
PY
```

이름 변경으로 설명되는 고유 토큰은 v3 기준 `shadow-sm`, `rounded`, `outline-none`, `backdrop-blur-sm`, `flex-shrink-0`, `focus:outline-none` 6개입니다.

치환 토큰 수(변경 라인 기준)는 `shadow-sm` 46, `rounded` 38, `outline-none` 26, `backdrop-blur-sm` 4, `flex-shrink-0` 5 이며, 모든 변경 라인이 `class=` 속성 안에서만 바뀌었습니다(`git diff -U0 -- src/app/templates src/app/static/js | grep -E '^[+-][^+-]' | grep -v 'class='` 결과 0줄).

---

## 5. 산출물 크기

| 시점 | `src/app/static/css/tailwind.css` |
| --- | ---: |
| 이전(v3, main) | 44,081 바이트 |
| 이후(v4, source(none) + @source 2경로) | 63,653 바이트 |

v4 는 `@layer properties` 폴백 블록과 opacity modifier 용 `color-mix` 폴백을 함께 내보내므로 파일이 커집니다. v4 자동 소스를 켠 중간 산출물은 89,489 바이트였고, 탐지 범위를 두 경로로 좁혀 63,653 바이트가 되었습니다.

---

## 6. braces 조사

`npm ci --include=dev` 후 `NODE_ENV` 를 해제하고 확인한 결과입니다.

```text
refac-bid-box-static@
└─┬ @tailwindcss/cli@4.3.3
  └─┬ @parcel/watcher@2.5.1
    └─┬ micromatch@4.0.8
      └── braces@3.0.3
```

- `braces` 최신 버전은 3.0.3 이고 advisory GHSA-vfj7-8cjw-p6xm 영향 범위는 `<=3.0.3`, 수정판이 없습니다(`npm view braces version` = 3.0.3).
- v3 의 `tailwindcss@3.4.16 → chokidar → micromatch → braces` 경로가 사라진 대신, v4 CLI 의 `@parcel/watcher → micromatch → braces` 경로로 같은 취약 버전이 남습니다. 메이저 이전만으로는 예외를 제거할 수 없습니다.
- 따라서 `.github/vulnerability-allowlist.yml` 의 `GHSA-vfj7-8cjw-p6xm` 항목을 지우지 않고 사유만 v4 경로로 갱신했습니다. `scripts/filter_npm_audit.py` 판정은 통과합니다(`all HIGH/CRITICAL vulnerabilities are in allowlist`).
- 참고: 이 환경은 `NODE_ENV=production` 이라 `npm ls`/`npm audit` 이 dev 의존성을 생략합니다. dev 를 포함해 확인해야 위 트리가 보입니다.

---

## 7. 사람이 브라우저로 확인할 화면

이전 전 상태와 픽셀을 눈으로 비교할 화면과 주목할 클래스입니다.

| 화면(템플릿) | 확인할 클래스 / 지점 |
| --- | --- |
| `src/app/templates/base.html` | 전역 기본 border 색이 `gray-200` 인지(색 미지정 `border`), 버튼 `cursor: pointer` |
| `src/app/templates/index.html` | `shadow-xs`(구 `shadow-sm`) 카드 그림자, `rounded-[26px]`, `xl:grid-cols-[minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.1fr)]` |
| `src/app/templates/bids/list.html` | `rounded-sm`(구 `rounded`) 페이지네이션, `outline-hidden`(구 `outline-none`) 입력 포커스, `space-x-2` 간격 |
| `src/app/templates/bids/results.html` | `shadow-xs` 로딩 카드, `rounded-sm` 배지 |
| `src/app/templates/bids/dashboard.html`, `detail.html`, `compare.html`, `result_detail.html` | `rounded-sm`, `shadow-xs`, `outline-hidden` |
| `src/app/templates/chatbot/chat.html` | `shrink-0`(구 `flex-shrink-0`) 헤더 고정, `backdrop-blur-xs`(구 `backdrop-blur-sm`), `focus:outline-hidden`, `rounded-sm` 배지 |
| `src/app/static/js/chat.js` | 스트리밍 말풍선 `shadow-xs`, 아이콘 `rounded-sm`, `shrink-0`; `formatChartValue` 정상 동작(지역 변수 원복) |

`hover:` 상태와 `space-x/y` 인접 자식 간격은 정적 비교로 확인이 어려우므로 위 화면에서 마우스 hover 와 목록 간격을 함께 봐야 합니다.

---

## 8. 미해결 및 escalation

1. braces 예외 제거 불가: 6장 참조. `@tailwindcss/cli 4.3.3` 의 `@parcel/watcher → micromatch → braces@3.0.3` 이 유일한 잔존 경로이며 수정판이 없습니다. 근본 해소는 `@parcel/watcher` 가 브레이스를 쓰지 않는 상류 릴리스에 달려 있습니다.
2. 기존 Tailwind 시험 2건 실패: `tests/test_tailwind_build.py` 는 허용된 쓰기 범위 밖이라 고치지 않았습니다.
   - `test_custom_theme_tokens_in_build_css`: v3 는 커스텀 색을 `rgb(0 115 230)` 같은 triplet 으로 출력했지만, v4 는 `--color-primary: #0073e6` 로 정규화합니다. 시험은 rgb triplet 문자열을 찾습니다.
   - `test_template_tailwind_utilities_exist_in_build_css`: 임의값의 쉼표를 v3 는 `\2c ` 로, v4 는 `\,` 로 이스케이프합니다. 시험은 `\2c ` 를 하드코딩합니다. 실제로는 `grid-cols-[auto_minmax(0,1fr)]`, `xl:grid-cols-[minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.1fr)]` 두 클래스가 v4 산출물에 존재합니다.
   - 두 시험 모두 main(v3)에서는 통과합니다. v4 표기에 맞춘 시험 갱신이 필요합니다.

---

## 9. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `npm ci` + `npm run build:css` + `git diff --exit-code -- src/app/static/css/tailwind.css` | 통과(빌드 결정적, 연속 2회 동일). 단 이 환경은 `NODE_ENV=production` 이라 `npm ci` 에 `--include=dev` 가 필요 |
| 선택자 비교(4장 명령) | 설명되지 않는 누락 0 |
| `npm ls braces`(NODE_ENV 해제) | braces@3.0.3 잔존 → 예외 유지 |
| `scripts/filter_npm_audit.py` | 통과(모두 allowlist) |
| `uv run pytest tests/ -q -m 'not data_assets'` | 6 failed, 6008 passed. 실패 6 = Tailwind 2 + 기존 환경 실패 4 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 21/21 |

기존 환경 실패 4건은 `tests/e2e/test_ssr_chatbot_stream.py` 3건, `tests/test_result_coverage.py::test_task_notifies_only_when_alert` 1건입니다. 이 중 result_coverage 1건은 main(v3) 에서도 동일하게 실패함을 stash 기준선 실행으로 확인했습니다. e2e 3건은 이번 이전 중 `chat.js` 지역 변수 `rounded` 가 `rounded-sm` 로 잘못 치환되어 발생한 회귀이며, 변수를 원복한 뒤 전부 통과했습니다.
