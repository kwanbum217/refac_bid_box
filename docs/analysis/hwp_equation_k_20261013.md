# HWP 수식 개체·레코드 판독으로 용역 공고 k 추출을 보강한다

> **작성일**: 2026-10-13
> **작업 브랜치**: `kwanbum217/k1-hwp-equation-k`
> **비교 기준**: `98d06541` (main, B1 `67b0f3e8` 병합 이후)
> **대상 파일**: `scripts/extract_score_params.py`, `tests/test_extract_score_params.py`
> **표본**: 2015~2024년 용역 적격심사제(`낙030001`) 공고 500건 (연도별 50건, 시드 `h1pilot20261013`), 첨부 529건
> **판정**: k 미추출 477건 중 "계산식 문구가 텍스트에 없는" 408건을 표본 분류한 결과, 원인이 이미지·별표 미첨부가 대부분이고 수식 개체·레코드 유실은 1건이었습니다. 해당 1건을 회수해 k 23 → 24건(+1), 회귀 0건입니다.

---

## 1. 질문과 배경

B1(`bk_extract_improve_20261013.md`)은 B·k 동시 추출을 10 → 23건으로 늘린 뒤, 남은 k 미추출 477건을 다음으로 분해했습니다.

| 원인 | 건수 |
| --- | ---: |
| 판독 불가·첨부 없음 | 69 |
| 판독 가능하나 계산식 문구 자체 없음 | 408 |
| 계산식 문구는 있으나 k 실패 | 0 |

본 작업은 **408건의 원인을 표본으로 분류**하고, 원인이 HWP 수식 개체(EQEDIT 등)나 이미지인 경우 수식 개체 스크립트 텍스트를 판독해 k 추출을 늘리는 것이 목적입니다.

**가설과 검증 결과:** B1 은 408건의 원인을 "별표가 이미지로 들어갔거나 계산식 문구가 첨부에 없음"으로 추정했습니다. 본 작업은 ① 수식 개체 스크립트가 평문 추출에서 유실되는지, ② 첨부 이미지가 실제로 계산식인지를 실제 바이트와 육안 표본으로 확인했습니다.

---

## 2. 원인 분류

### 2.1 분류 규칙

선별 첨부(공고서·적격심사 관련 파일명만) 바이트를 공고 단위로 검사합니다.

| 원인 | 판정 |
| --- | --- |
| **수식 개체** | 계산식이 수식 개체(`EQEDIT` 0x58) 또는 레코드 문단에만 있어 현행 평문 추출이 놓친 경우. 레코드 단위 판독으로 회수 가능 |
| **그림** | 계산식 문구가 텍스트에 없고 첨부가 사실상 이미지뿐인 경우(평문 200자 미만 + 이미지 개체). OCR 이 필요해 회수 불가 |
| **첨부에 별표 없음** | 별표·배점한도·계산식 문맥이 선별 첨부에 아예 없음 |
| **기타** | 문맥은 있으나 계산식 문구도, 이미지도 없음 |

### 2.2 분류 결과 (408건)

| 원인 | 건수 | 비율 |
| --- | ---: | ---: |
| 수식 개체 | 1 | 0.2% |
| 그림 | 0 | 0.0% |
| 첨부에 별표 없음 | 189 | 46.3% |
| 기타 | 218 | 53.4% |
| **합계** | **408** | **100%** |

참고로 이미지 개체를 포함한 공고는 408건 중 171건(별표 없음 61 + 기타 110)입니다.

### 2.3 그림(이미지) 판정 근거

당초 가설과 달리 **계산식을 담은 이미지는 표본에서 확인되지 않았습니다.**

1. 첨부 529건 중 206건의 바이너리 HWP 가 `BinData` 이미지 스트림을 가집니다(그림 부품 `SHAPE_COMPONENT_PICTURE` 0x55 기준 192건). 그러나 **별표 없음 조건**(이미지 有 + 평문 200자 미만)을 만족하는 첨부는 0건입니다.
2. 이미지가 가장 큰 첨부를 육안 확인한 결과 모두 **기관 로고·배너·훈장**이었습니다. 예: `20150315982`(한국환경공단 `kr Clean & Green`), `20150516487`(조달청), `20150619944`(교육청), `20210226428`(기관 배너).
3. 첨부 텍스트에 입찰가격 계산식 문구가 아예 없는 상태라, 408건은 계산식이 아니라 **별표(적격심사 세부기준) 문서 자체가 첨부·선별에 없는 경우**가 지배적입니다.

### 2.4 수식 개체(EQEDIT) 현황

바이너리 HWP 의 수식 개체는 `CTRL_HEADER`(ctrl id `eqed`) 아래 `HWPTAG_EQEDIT`(0x58) 레코드 payload 에 스크립트 문자열이 UTF-16LE 로 들어 있습니다. 실측 예입니다.

```text
TBIGCIRC `평점(점)`=`배점한도-`2` TIMES |( {88} over {100} - {입찰가격} over {예정가격} ) TIMES 100|
PBIGCIRC `평점(점)=배점한도-4 TIMES |( {88} over {100} - {입찰가격} over {예정가격} ) TIMES 100|
```

- 첨부 529건 중 11건에서 EQEDIT 64개를 확인했고, 이 중 계산식을 가진 공고는 이미 B1 에서 회수된 표본입니다.
- 문제는 **본문 스트림 전체를 UTF-16LE 로 통째로 디코딩하는 현행 방식**입니다. 레코드 크기가 홀수인 지점에서 정렬이 한 바이트씩 어긋나 뒤따르는 텍스트가 통째로 유실됩니다. 실측에서 문단·수식 payload 텍스트 81,785개 중 **33,032개(40.4%)** 가 이렇게 평문에서 사라졌습니다.
- 그 결과 `20220626311`(서울패션허브 창업뜰 경비·미화용역)은 문단에 `평점 = 90-20×…` 계산식이 레코드에는 있으나 평문 평문화에서 유실돼 k 를 얻지 못했습니다.

---

## 3. 수정 내용

### 3.1 레코드 단위 문단·수식 개체 판독

`scripts/extract_score_params.py` 에서 본문 스트림 전체 디코딩과 별개로 레코드를 개별 디코딩합니다.

| 위치 | 내용 |
| --- | --- |
| `scripts/extract_score_params.py:111` | `_HWP_TAG_EQEDIT = 0x58` 태그 상수 추가 |
| `scripts/extract_score_params.py:355` | `_hwp_record_text` — `PARA_TEXT`(0x43)와 `EQEDIT`(0x58) payload 를 레코드별로 디코딩해 텍스트를 모음 |
| `scripts/extract_score_params.py:469` | `_hwp_formula_rows` — 레코드 텍스트에서 계산식 문단을 행으로 승격 |
| `scripts/extract_score_params.py:478` | `_binary_hwp_document` — 절 단위로 레코드를 한 번 풀어 표 복원·계산식 승격에 함께 사용 |

레코드 텍스트는 스트림 정렬 오차에 영향받지 않으므로, 평문 디코딩이 놓친 계산식 문단과 수식 개체 스크립트를 회수합니다.

### 3.2 수식 개체 스크립트 백틱 정규화

수식 개체 스크립트는 조판에 따라 백틱이 끼어듭니다(`평점(점)`=`배점한도-`2`). `_formula_text_rows`(`scripts/extract_score_params.py:156`)가 후보 문단을 찾을 때 백틱을 먼저 제거하도록 했습니다. `parse_price_formula`(`scripts/extract_score_params.py:595`)는 이미 같은 정규화를 하므로 판정 규칙이 일치합니다.

### 3.3 시험

`tests/test_extract_score_params.py` 에 합성 레코드 시험 5건을 추가했습니다.

- `CTRL_HEADER`(0x58 수식 개체) payload 를 조립해 스크립트 판독과 `parse_price_formula` 결과를 고정
- 백틱이 낀 수식 개체 스크립트 판독
- 홀수 크기 레코드 뒤 문단이 전체 스트림 디코딩에서 유실되는 것과, 레코드 판독으로 회수되는 것을 함께 검증(실측 `20220626311` 유실 유형)

---

## 4. 결과

### 4.1 수정 전후 지표 (동일 캐시 첨부 529건)

| 지표 | 수정 전 | 수정 후 | 증감 |
| --- | ---: | ---: | ---: |
| 판독 가능 | 431 | 431 | 0 |
| B | 25 | 25 | 0 |
| k | 23 | 24 | +1 |
| T | 164 | 164 | 0 |
| B·k 동시 | 23 | 23 | 0 |
| T·B·k 전량 | 17 | 17 | 0 |

### 4.2 결과 분류 (outcome)

| 분류 | 수정 전 | 수정 후 | 증감 |
| --- | ---: | ---: | ---: |
| 전량추출 | 17 | 17 | 0 |
| 부분추출 | 155 | 156 | +1 |
| 표 해석 실패 | 259 | 258 | -1 |
| 첨부 없음 | 61 | 61 | 0 |
| 판독 불가 형식 | 6 | 6 | 0 |
| 스캔 PDF | 2 | 2 | 0 |

### 4.3 회수 표본

| 연도 | 공고번호 | 공고명 | 첨부 | 회수 전 | 회수 후 |
| ---: | --- | --- | --- | --- | --- |
| 2022 | 20220626311 | 2022년 서울패션허브 창업뜰 경비용역 안내 및 미화용역 | hwp | k 없음 | k=20 |

계산식 `3) 입찰가격(90점) : 평점 = 90-20×88/100-입찰가격/예정가격)×100` 이 `PARA_TEXT` 레코드에는 있었으나 평문 평문화에서 유실된 표본입니다. 같은 문서에 배점한도 표가 없어 B 는 여전히 나오지 않습니다(k 단독 회수).

---

## 5. 회귀 검증

수정 전후 CSV 를 공고번호로 맞대어, 이전에 값을 얻던 표본이 실패로 바뀐 경우를 셌습니다. **B 0건, k 0건, T 0건으로 회귀가 없습니다.**

k 후보 집합이 넓어진 공고는 21건입니다(B1 도 같은 동작을 정상으로 기록했습니다). 그중 5건은 후보가 1개에서 복수로 늘었습니다. 이는 같은 문서의 구간별 계산식이 평문 유실로 일부만 보이던 것이 온전히 보이게 된 결과이며, 구간 확정은 `select_band` 과제입니다. 후보 값 집합은 `parse_price_formula` 가 반환하는 모든 후보를 합칩니다.

---

## 6. 한계와 잔여

1. **남은 407건은 첨부 구성 문제입니다.** 별표(적격심사 세부기준) 문서가 첨부되지 않았거나 파일명 선별에서 빠진 경우가 지배적입니다. 이는 `extract_score_params.py` 파서 범위 밖이며, 선별 정책 또는 전량 첨부 수집이 선행돼야 합니다.
2. **계산식을 담은 이미지는 표본에서 0건**이라 OCR 착수 근거가 없습니다. 남은 이미지는 기관 로고·배너입니다.
3. **k 후보 복수화**는 구간 확정(`select_band`) 과제로 남습니다.
4. 수식 개체(EQEDIT) 자체는 표본 11건뿐이라, 레코드 판독의 직접 효과는 유실된 레코드 문단 회수에서 나왔습니다.

---

## 7. 판정

1. 408건의 원인은 **이미지 0 · 수식 개체/레코드 유실 1 · 별표 미첨부·미선별 407** 입니다. B1 의 "이미지·첨부 구성 문제" 추정을 실측으로 확인했고, 이미지 기대는 기각됐습니다.
2. 수식 개체·레코드 판독을 구현해 **k 23 → 24건(+1), 회귀 0건**입니다. 판독 가능 기준 5.34% → 5.57% 입니다.
3. 남은 미추출은 파서로 회수할 여지가 작고, **별표 첨부 확보 정책**이 다음 지렛대입니다.

---

## 8. 검증 및 재현

```sh
uv run pytest tests/test_extract_score_params.py tests/test_pilot_past_notice_method_extract.py -q
uv run pytest tests/ -q -m 'not data_assets'
uv run mypy src
python3 scripts/validate_agent_rules.py --quiet
```

표본·첨부는 커밋하지 않습니다. 재현 절차입니다(첨부는 나라장터에서 다시 받으며 요청 간 1초).

```sh
mkdir -p .cache/past_notice_pilot
uv run python scripts/db_readonly_query.py --sql-file .cache/past_notice_pilot/sample.sql \
    --format json --limit 500 > .cache/past_notice_pilot/sample_raw.json
uv run python scripts/pilot_past_notice_method_extract.py \
    --sample .cache/past_notice_pilot/sample_raw.json --out-dir .cache/past_notice_pilot
```

수정 전 수치는 위 실행 결과를 `.cache/past_notice_pilot/sample_extract_results_before.csv` 로 보존한 뒤, 수정 후 같은 캐시에 다시 돌려 비교합니다.

원인 분류(408건)는 다음 스니펫으로 재계산됩니다.

```sh
uv run python - <<'PY'
import csv, glob, io, re, zipfile
from pathlib import Path
from scripts.extract_score_params import (
    _hwp_formula_rows, _hwp_records, _ole_streams, extract_document_text, parse_price_formula)

CACHE = Path('.cache/past_notice_pilot')
OLE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
SECTION = re.compile(r'(BodyText/)?Section\d+')
KEEP = re.compile(r'[^\t\n\u0020-\u007E\u00A1-\u00FF\u2010-\u2027\u2026\u3000-\u303F'
                  r'\u3131-\u318E\u4E00-\u9FFF\uAC00-\uD7A3\uFF01-\uFF60]')


def classify(bid):
    eq = rec = images = flat_max = 0
    bh = calc = byo = False
    for path in sorted(glob.glob(str(CACHE / 'attachments' / f'{bid}_*'))):
        data = Path(path).read_bytes()
        doc = extract_document_text(data)
        text = doc.flat + ' ' + ' '.join(' '.join(r) for r in doc.rows)
        bh = bh or '배점한도' in text
        calc = calc or ('계산식' in text or '산식' in text)
        byo = byo or '별표' in text
        flat_max = max(flat_max, len(doc.flat.strip()))
        if data[:8] == OLE:
            streams = _ole_streams(data)
            sections = [streams[n] for n in streams if n.startswith('BodyText/') or SECTION.fullmatch(n)]
            for section in sections:
                for tag, _lvl, payload in _hwp_records(section):
                    if tag == 0x55:
                        images += 1
                    elif tag == 0x58:
                        script = KEEP.sub('', payload.decode('utf-16le', 'ignore'))
                        if parse_price_formula([(script,)]):
                            eq = 1
            if parse_price_formula(_hwp_formula_rows(_hwp_records(b''.join(sections)))):
                rec = 1
        elif data[:4] == b'PK\x03\x04':
            archive = zipfile.ZipFile(io.BytesIO(data))
            for name in archive.namelist():
                if name.endswith('.xml') and re.search(
                        r'<hp:(img|pic)\b|<(hp:)?binData\b',
                        archive.read(name).decode('utf-8', 'replace'), re.I):
                    images += 1
    if eq or rec:
        return '수식 개체'
    if images and flat_max < 200:
        return '그림'
    if not (bh or calc or byo):
        return '첨부에 별표 없음'
    return '기타'


rows = list(csv.DictReader((CACHE / 'sample_extract_results_before.csv').open(encoding='utf-8')))
counts = {}
for row in rows:
    if row['multiplier'] or int(row['readable_count']) == 0:
        continue
    cause = classify(row['bid_ntce_no'])
    counts[cause] = counts.get(cause, 0) + 1
print(counts)
PY
```

출력은 `{'기타': 218, '첨부에 별표 없음': 189, '수식 개체': 1}` 입니다.
