# 공고 상세 '표준공고문' 링크 필요성 조사

> **작성일**: 2026-11-17
> **범위**: 공고 상세 첨부파일 카드의 `표준공고문` 링크(`stdNtceDocUrl`) 유지 여부 판단
> **대상 코드**: `src/app/services/announcement_attachments.py` `describe_announcement_links`,
> `src/app/templates/bids/_attachments.html`
> **결론**: 첨부 목록에 같은 URL 이 이미 있으면 링크를 숨기는 방식을 권고합니다. 코드는 이번 작업에서 고치지 않았습니다.

---

## 1. 조사 배경

공고 상세 화면의 첨부파일 카드는 다음 세 갈래를 그립니다.

| 갈래 | 원본 필드 | 화면 표시 |
| --- | --- | --- |
| 첨부파일 목록 | `ntceSpecDocUrl1`~`ntceSpecDocUrl10` + `ntceSpecFileNm1`~`ntceSpecFileNm10` | 파일명 링크 목록 |
| 표준공고문 | `stdNtceDocUrl` | `표준공고문` 링크 1개 |
| 나라장터 원문 | `bidNtceDtlUrl` | `나라장터 공고 원문 보기` 링크 |

`describe_announcement_links` 는 `stdNtceDocUrl` 을 첨부 목록과 대조하지 않고 그대로
`standard_notice_url` 로 돌려줍니다. 따라서 같은 파일이 목록과 링크에 두 번 나올 수
있다는 가설을 데이터로 확인했습니다.

## 2. 방법과 표본

- 운영 DB 는 `uv run python scripts/db_readonly_query.py --sql "<질의>"` 로만 조회했습니다.
  `docker exec`, `mysql` 직접 호출은 쓰지 않았고, 질의는 한 번에 하나씩 순서대로 실행했습니다.
- 전체 테이블 `LIKE` 스캔은 하지 않았습니다. `bid_announcements` 는 `category` 단독 인덱스와
  `(bid_ntce_dt, category)` 복합 인덱스가 있어, 용역(`category = 'Servc'`) + 30일 날짜 범위로
  먼저 좁혔습니다.
- 컬럼 타입은 `DESC bid_announcements` 로 확인했습니다. `raw_data` 는 `longtext` 이고 JSON
  문자열로 저장되어 있어 `JSON_EXTRACT` 앞에 `JSON_VALID` 를 두었습니다.

| 항목 | 값 |
| --- | --- |
| 표본 조건 | `category = 'Servc'` AND `bid_ntce_dt >= '2026-10-18'` AND `bid_ntce_dt < '2026-11-18'` |
| 표본 건수 | 16,565 |
| 실제 공고일 범위 | 2026-10-18 13:45:41 ~ 2026-11-16 23:01:57 |
| `raw_data` 유효 JSON | 16,565 (100%) |

## 3. 질의문

### Q1. 표본 규모와 `stdNtceDocUrl` 보유 건수

```sql
SELECT COUNT(*) AS total,
       SUM(CASE WHEN JSON_VALID(raw_data) THEN 1 ELSE 0 END) AS json_valid,
       SUM(CASE WHEN JSON_VALID(raw_data)
                 AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')), '') <> ''
                THEN 1 ELSE 0 END) AS std_present
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-10-18' AND bid_ntce_dt < '2026-11-18'
```

| total | json_valid | std_present |
| --- | --- | --- |
| 16,565 | 16,565 | 14,144 |

### Q2. `stdNtceDocUrl` 이 첨부 1~10번 URL 가운데 하나와 같은 비율

```sql
SELECT COUNT(*) AS std_present,
       SUM(CASE WHEN std IN (u1,u2,u3,u4,u5,u6,u7,u8,u9,u10) THEN 1 ELSE 0 END) AS in_spec
FROM (
  SELECT COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')), '') AS std,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl1')), '')  AS u1,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl2')), '')  AS u2,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl3')), '')  AS u3,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl4')), '')  AS u4,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl5')), '')  AS u5,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl6')), '')  AS u6,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl7')), '')  AS u7,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl8')), '')  AS u8,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl9')), '')  AS u9,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl10')), '') AS u10
  FROM bid_announcements
  WHERE category = 'Servc'
    AND bid_ntce_dt >= '2026-10-18' AND bid_ntce_dt < '2026-11-18'
) t
WHERE std <> ''
```

| std_present | in_spec | 비율 |
| --- | --- | --- |
| 14,144 | 14,143 | 99.99% (표본 전체 대비 85.38%) |

### Q3. 첨부 목록이 비어 있는 건수와 '공고문' 이름 첨부 보유 건수

```sql
SELECT COUNT(*) AS std_present,
       SUM(CASE WHEN u1='' AND u2='' AND u3='' AND u4='' AND u5=''
                 AND u6='' AND u7='' AND u8='' AND u9='' AND u10='' THEN 1 ELSE 0 END) AS no_attach_files,
       SUM(CASE WHEN n1  LIKE '%공고문%' OR n2  LIKE '%공고문%' OR n3  LIKE '%공고문%'
                 OR n4  LIKE '%공고문%' OR n5  LIKE '%공고문%' OR n6  LIKE '%공고문%'
                 OR n7  LIKE '%공고문%' OR n8  LIKE '%공고문%' OR n9  LIKE '%공고문%'
                 OR n10 LIKE '%공고문%' THEN 1 ELSE 0 END) AS has_notice_named_file
FROM (
  SELECT COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')), '')       AS std,
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecDocUrl1')), '')      AS u1,
         /* u2 ~ u10 동일 형태 */
         COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecFileNm1')), '')      AS n1,
         /* n2 ~ n10 동일 형태 */
  FROM bid_announcements
  WHERE category = 'Servc'
    AND bid_ntce_dt >= '2026-10-18' AND bid_ntce_dt < '2026-11-18'
) t
WHERE std <> ''
```

| std_present | no_attach_files | has_notice_named_file |
| --- | --- | --- |
| 14,144 | 0 | 8,965 (63.37%) |

### Q4. 같은 URL 을 가리키는 첨부파일의 이름에 '공고문' 이 들어간 비율

```sql
SELECT COUNT(*) AS in_spec,
       SUM(CASE WHEN std = u1  THEN n1  LIKE '%공고문%'
                WHEN std = u2  THEN n2  LIKE '%공고문%'
                WHEN std = u3  THEN n3  LIKE '%공고문%'
                WHEN std = u4  THEN n4  LIKE '%공고문%'
                WHEN std = u5  THEN n5  LIKE '%공고문%'
                WHEN std = u6  THEN n6  LIKE '%공고문%'
                WHEN std = u7  THEN n7  LIKE '%공고문%'
                WHEN std = u8  THEN n8  LIKE '%공고문%'
                WHEN std = u9  THEN n9  LIKE '%공고문%'
                WHEN std = u10 THEN n10 LIKE '%공고문%'
                ELSE 0 END) AS matched_name_has_notice
FROM ( /* Q3 과 같은 파생 표, std/n1~n10/u1~u10 */ ) t
WHERE std <> '' AND std IN (u1,u2,u3,u4,u5,u6,u7,u8,u9,u10)
```

| in_spec | matched_name_has_notice | 비율 |
| --- | --- | --- |
| 14,143 | 8,934 | 63.16% |

즉 표준공고문 링크가 가리키는 파일은 첨부 목록에서 대부분 `공고문` 이 들어간 이름으로
이미 노출되어 있습니다. 나머지 5,209건(36.84%)은 이름만으로는 같은 파일임을 알 수 없는
경우입니다(예: `계약 공통 첨부서류(계약일반조건 등).zip`).

### Q5. 첨부 1~10번과 다른 표준공고문 URL (1건) 확인

```sql
SELECT bid_ntce_no, bid_ntce_ord, bid_ntce_dt, bid_ntce_nm,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')) AS std_url,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.ntceSpecFileNm1')) AS f1
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-10-18' AND bid_ntce_dt < '2026-11-18'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')) IS NOT NULL
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')) <> ''
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.stdNtceDocUrl')) NOT IN ( /* u1 ~ u10 */ )
LIMIT 5
```

| 공고번호 | 공고일 | 비고 |
| --- | --- | --- |
| R26BK01792264 | 2026-10-26 | `stdNtceDocUrl` 의 `fileSeq=11` 로, 첨부 1~10번과 다른 파일 |

이 1건은 `raw_data` 에 `ntceSpecDocUrl11`·`ntceSpecFileNm11` 이 없고 `stdNtceDocNm` 같은
이름 필드도 없습니다. 링크를 유지해야만 접근할 수 있는 파일입니다.

## 4. 대표 사례

| 공고번호 | 공고명 | 공고일 | 첨부 목록의 같은 URL 파일명 |
| --- | --- | --- | --- |
| R26BK01819469 | 2026년 글로벌 소상공인(K-소상공인) 육성사업 Shopee 단독 기획전 운영 용역 | 2026-11-10 | `(붙임1) 입찰공고문_2026년 글로벌 소상공인(K-소상공인) 육성사업 Shopee 단독 기획전 운영 용역.hwp` |
| R26BK01819477 | 잠수교 문화공간 조성 및 접근성 개선공사 건설폐기물처리용역(장기계속) | 2026-11-10 | `1. 입찰공고문(잠수교 폐기물).hwpx` |
| R26BK01819479 | 2027년 경남인공지능혁신본부 시설물 관리용역 | 2026-11-10 | `공고문_2027년 경남인공지능혁신본부 시설물 관리 용역(11.10. 공고게시기준).hwp` |

세 사례 모두 `stdNtceDocUrl` 이 `ntceSpecDocUrl1` 과 문자열까지 같습니다. 화면에는 같은
URL 이 `입찰공고문` 파일 링크와 `표준공고문` 링크로 두 번 나옵니다.

## 5. 권고안

**권고: 첨부 목록과 URL 이 중복되면 `표준공고문` 링크를 숨긴다(조건부 숨김).**

근거는 다음과 같습니다.

1. 표준공고문 URL 이 있는 14,144건 가운데 14,143건(99.99%)이 첨부 1~10번 URL 과
   완전히 같은 문자열입니다. 링크를 그대로 두면 거의 모든 공고에서 같은 파일이 두 번
   노출됩니다.
2. 그중 8,934건(63.16%)은 첨부 목록 파일명에 `공고문` 이 들어 있어, 중복이라는 사실이
   화면에서도 분명합니다. 나머지 36.84%는 파일명만으로는 중복임을 알기 어려워
   중복 제거가 오히려 목록을 깔끔하게 만듭니다.
3. 첨부 목록이 비어 있는 공고는 0건입니다. 따라서 "목록이 없을 때만 표준공고문을
   보여준다" 같은 대체 규칙은 필요 없습니다.
4. 예외는 1건(0.007%)뿐입니다. R26BK01792264 처럼 표준공고문이 첨부 1~10번 밖의
   파일(`fileSeq=11`)을 가리키는 경우가 있어, 무조건 삭제하면 이 파일에 접근할 수
   없게 됩니다. 중복일 때만 숨기면 예외가 자동으로 보존됩니다.
5. `나라장터 공고 원문 보기`(`bidNtceDtlUrl`)는 별도 목적지이므로 그대로 둡니다.

차선책은 링크를 아예 삭제하는 것이지만, 위 1건에서 파일 접근이 끊기고 `stdNtceDocUrl`
필드 자체를 더 이상 쓰지 않게 됩니다. 유지(현행)는 99.99% 중복 노출을 감수해야 하므로
권고하지 않습니다.

## 6. 한계

- 용역(`Servc`) 최근 30일 표본만 조사했습니다. 다른 카테고리나 과거 구간에서 중복
  비율이 다를 수 있습니다.
- 외부 URL 은 내려받거나 열지 않았습니다. URL 문자열 비교만으로 중복을 판정했습니다.
- `raw_data` 에 표준공고문 파일명 필드가 없어, 링크에 표시할 이름은 지금처럼 코드의
  고정 문구 `표준공고문` 을 써야 합니다.
- 이번 작업에서는 `src/app/services/announcement_attachments.py` 와
  `src/app/templates/bids/_attachments.html` 을 고치지 않았습니다. 적용 여부는
  사용자가 결정합니다.
