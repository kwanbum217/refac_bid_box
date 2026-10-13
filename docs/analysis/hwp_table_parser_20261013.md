# 바이너리 HWP 표 복원으로 입찰가격 배점한도(B)·평점계수(k) 추출 개선

> **작성일**: 2026-10-13
> **작업 브랜치**: `kwanbum217/p1-hwp-table-parser`
> **기준 main**: `d602f308`
> **대상 파일**: `scripts/extract_score_params.py`, `tests/test_extract_score_params.py`
> **샘플**: `.cache/hwp_samples/용역적격심사세부기준(20221001시행).hwp` (78,848 B, gitignore 대상, 커밋 안 함)
> **판정**: 기준서 샘플에서 별표 표가 행 목록으로 복원되고 `parse_price_formula`·`parse_price_limit` 가 B·k 를 돌려준다. H1 표본(500건)에서 B·k 동시 추출이 1/431 에 그친 구조적 원인(바이너리 HWP 표 미복원)을 제거했다.

---

## 1. 질문과 배경

`docs/analysis/past_notice_method_pilot_20261013.md` 에 따르면 2015~2024 년 용역 적격심사제(`낙030001`) 공고 표본 500건 중 판독 431건에서 기준명 241, 통과점수 T 164, **B·k 동시 추출 1건**이었다. 원인은 판독 첨부의 92.7%(416/449 공고)가 바이너리 HWP 인데, `_binary_hwp_document` 가 BodyText 섹션의 문단 텍스트만 이어 붙이고 표의 행·셀 구조를 버리는 것이다. `parse_price_formula`·`parse_price_limit` 는 표 행 목록을 입력으로 받으므로 바이너리 HWP 에서는 원리적으로 빈 결과였다.

이 작업은 HWP 5.x 레코드에서 표·셀 구조를 복원해 그 두 파서가 쓰는 행 목록(`DocumentText.rows`)을 만든다.

---

## 2. HWP 5.x 바이너리 레코드 해석 요약

BodyText(`SectionN` 또는 `BodyText/SectionN`) 스트림은 zlib raw deflate 로 압축된 **레코드 열**이다. 기존 `_ole_streams` 가 압축 해제한 스트림을 그대로 쓴다.

### 2.1 레코드 헤더 (32비트 little-endian)

| 필드 | 비트 | 설명 |
| --- | --- | --- |
| TagID | 0-9 | 태그 (10비트) |
| Level | 10-19 | 중첩 깊이 (10비트) |
| Size | 20-31 | payload 크기 (12비트). `0xFFF` 이면 다음 4바이트가 실제 크기 |

### 2.2 사용한 태그

| TagID | 이름 | 용도 |
| --- | --- | --- |
| `0x42` | PARA_HEADER | 문단 머리 (셀 안 문단 구획) |
| `0x43` | PARA_TEXT | 문단 텍스트 (UTF-16LE) |
| `0x47` | CTRL_HEADER | 개체 컨트롤. 첫 4바이트가 ctrl id 를 little-endian 으로 담는다 |
| `0x48` | LIST_HEADER | 표 셀 주소·병합 정보 |
| `0x4D` | TABLE | 표 행 수·열 수 |

ctrl id 는 바이트가 뒤집혀 저장된다. 표는 `payload[:4]` 를 뒤집었을 때 `b"tbl "` 이다(실측 `20 6c 62 74`).

### 2.3 표·셀 오프셋 (샘플 28개 표에서 검증)

- **TABLE** (`0x4D`): `[0:4]` 속성, `[4:6]` 행 수, `[6:8]` 열 수. 레벨은 선행 CTRL_HEADER 의 다음 레벨.
- **LIST_HEADER** (셀, `0x48`): `[0:4]` 문단 수, `[4:8]` 리스트 속성, `[8:10]` 열(col), `[10:12]` 행(row), `[12:14]` colspan, `[14:16]` rowspan.
- 셀 문단은 (같은 레벨의) LIST_HEADER 다음부터 다음 LIST_HEADER 또는 상위 레벨 레코드 전까지 이어진다. PARA_TEXT 는 셀 레벨 이상에서 수집한다.

---

## 3. 복원 알고리즘

`_binary_hwp_document` 는 기존 평문 추출(문단 텍스트 이어붙이기)을 **그대로 유지**하고, 추가로 표 격자를 복원해 `DocumentText.rows` 에 넣는다.

1. `_hwp_records`: 스트림을 `(tag, level, payload)` 목록으로 푼다. 잘린·손상 레코드를 만나면 그 지점에서 멈춘다(예외 없음).
2. `_hwp_table_rows`: CTRL_HEADER(ctrl id `tbl `) 바로 뒤의 TABLE 레코드를 표 시작으로 본다.
3. `_hwp_read_table`: TABLE 의 선언 행·열 수와 셀 주소(col·row)를 합쳐 격자를 만든다. 셀 텍스트는 col 순서로 채우고, 병합 셀(colspan·rowspan)은 덮는 모든 칸을 같은 값으로 채운다. 선언값이 비정상이면 셀 주소에서 도출한다.
4. 표 복원이 실패해도 `contextlib.suppress` 로 건너뛰고 평문만 남긴다. 문단 텍스트 추출(기준명·T)은 나빠지지 않는다.

### 3.1 바이너리 HWP 수식 개체 서식 대응

HWPX·HWPML 의 수식 개체는 `평점(점)=배점한도-2 TIMES ...` 로 평문화되지만, 바이너리 HWP 는 배점한도와 계수를 숫자로 바꿔 `평점=50-2×` 형태로 남긴다(계수가 1 이면 `평점=30 -|` 처럼 생략). `parse_price_formula` 에 이 서식을 읽는 `_HWP_PRICE_FORMULA_RE` 를 추가하고, `parse_price_limit` 는 `70점` 처럼 `점` 접미사가 붙은 배점한도 셀도 읽도록 고쳤다.

---

## 4. 기준서 샘플 복원 결과 예시

복원한 표 28개, 행 170개 중 일부다.

**별표 배점한도 표 (표 rec4816)** — 입찰가격 배점한도 80:

| 구 분 | 구 분 | 배점한도 | 자기평점 | 심사평점 |
| --- | --- | ---: | --- | --- |
| 계 | 계 | 100 | | |
| 경영상태 | 당해용역 수행능력 | 20 | | |
| 특별신인도 | 특별신인도 | 1.5 | | |
| 입찰가격 | 입찰가격 | 80 | | |
| 결격사유 | 결격사유 | -20 | | |

**별표 입찰가격 평점 산식 행 (표 rec613)** — B=50, k=2:

| 심사항목 | 심사분야 | 심사방법 | 배점한도 |
| --- | --- | --- | ---: |
| 2. 입찰가격 | 2. 입찰가격 | `o 다음 산식에 의해 산출된 평점 적용 88 입찰가격 * 평점=50-2×｜( - )×100｜ 100 예정가격 ...` | 50점 |

---

## 5. 수정 전후 B·k 추출 비교 (기준서 1건)

`extract_document_text` 및 두 파서를 기준서 샘플에 직접 돌린 결과다.

| 항목 | 수정 전 | 수정 후 |
| --- | ---: | --- |
| `DocumentText.rows` (복원 행 수) | 0 | 170 |
| `parse_price_limit` (B 후보) | `[]` | `[30]` |
| `parse_price_formula` (k 후보) | `[]` | 8건, 계수 `{1, 2, 3, 4, 5, 20}` |
| `select_band` 로 고른 B | `None` | `30` |
| `DocumentText.flat` 길이 | 26,210 | 26,210 (동일) |

평문은 문자 단위로 동일하다(같은 연산 경로). H1 표본 431건의 판독 첨부 대부분이 같은 바이너리 HWP 이므로, 표 복원이 되는 순간 그 첨부들이 B·k 후보를 갖게 된다.

---

## 6. 남은 한계

1. **`배점한도-N×` 서식은 아직 읽지 않는다.** 시설분야용역 `별표2`(표 rec1493)는 수식이 `배점한도-60×` 로 렌더링되어 `평점=` 접두가 없다. 계수 신뢰도가 낮아 이번 범위에서는 건너뛰었다.
2. **기준비율(base_rate)은 바이너리에서 복원하지 않는다.** `{90} over {100}` 같은 HWPX 서식이 없고 분수 성분이 조판 순서로 흩어져 나온다. B·k 와 달리 근거가 약해 None 으로 둔다.
3. **여러 별표가 한 문서에 있으면 `parse_price_limit` 는 첫 입찰가격 행만 쓴다.** 기존 단일 반환 계약이며, 공고 낙찰방법 문구로 구간을 특정하지 못하면 `select_band` 가 확정하지 못한다.
4. **표 선언 행·열 수가 크게 틀린 문서**는 셀 주소에서 도출한 값으로 대체한다. 중첩 표는 바깥 셀 텍스트에 포함되고 별도 표로도 한 번 더 복원된다.

---

## 7. 검증

```sh
uv run pytest tests/test_extract_score_params.py tests/test_pilot_past_notice_method_extract.py -q
uv run pytest tests/ -q -m 'not data_assets'
uv run mypy src
python3 scripts/validate_agent_rules.py --quiet
```

`tests/test_extract_score_params.py` 에 합성 HWP 섹션(표 1개, 셀 4개) 테스트를 추가했다. 레코드 바이트를 직접 조립해 실제 파일 없이 1행 4열 격자와 rowspan 병합 채움, 잘린 레코드 정지를 고정한다. 바이너리 수식 서식(`평점=50-2×`, `평점=30 -|`)에 대한 파서 단위 시험도 포함한다.
