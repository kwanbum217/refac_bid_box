# task_bdf61eec4069: Tailwind 빌드타임 CSS 전환

> **작성일**: 2026-08-26
> **Task ID**: task_bdf61eec4069
> **상태**: 빌드·대조 테스트 완료, 병합 게이트 2건 차단

---

## 요약

브라우저 JIT(`vendor/tailwindcss/3.4.16/tailwindcss.js` + 인라인 `tailwind.config`)를 제거하고, `tailwind.config.js` + `npm run build:css` 산출물 `src/app/static/css/tailwind.css`로 교체했다. `tests/test_tailwind_build.py`로 템플릿 클래스 대조 검증을 추가했다.

## 변경 파일

| 파일 | 변경 |
| --- | --- |
| `package.json` | tailwindcss 3.4.16, `build:css` 스크립트 |
| `tailwind.config.js` | 인라인 설정 이관, HTML class 속성 커스텀 extractor |
| `src/app/static/css/tailwind.input.css` | `@tailwind` directives + 비표준 opacity 보완 유틸 |
| `src/app/static/css/tailwind.css` | 빌드 산출물 (커밋 대상) |
| `src/app/templates/base.html` | JIT script 제거, `css/tailwind.css` link (bootstrap/daisyui 다음) |
| `tests/test_tailwind_build.py` | 클래스·테마·JIT 제거 대조 테스트 |

## 검증 결과

| 명령 | 결과 |
| --- | --- |
| `npm run build:css` | PASS |
| `uv run pytest tests/test_tailwind_build.py -q` | PASS (6) |
| `uv run pytest tests/ -q -m 'not data_assets'` | FAIL (2154 pass, 3 fail) |
| `python3 scripts/validate_agent_rules.py --quiet` | FAIL (CURRENT_STATE source_commit) |

## 차단 사유 (allowed_write_files 외 수정 필요)

1. **`tests/test_static_assets.py`**: `vendor/tailwindcss` 참조 검사가 본 Task 변경과 충돌. `css/tailwind.css` 검사로 갱신 필요.
2. **`docs/context/CURRENT_STATE.md`**: `source_commit`이 HEAD보다 6커밋 뒤처짐 (허용 5). validate_agent_rules 실패.

## 기술 메모

- Tailwind CLI는 `border-white/12`, `text-blue-100/72` 등 비표준 opacity slash 값을 자동 생성하지 않음. `tailwind.input.css`에 동등 유틸을 `@layer utilities`로 보완(템플릿 class 변경 없음).
- `tailwind.config.js` content extractor는 Jinja 블록 내부 class 토큰과 `/` opacity 클래스를 안정적으로 수집한다.

## vendor 보존

`src/app/static/vendor/tailwindcss/3.4.16/tailwindcss.js`는 삭제하지 않았다 (되돌릴 근거).
