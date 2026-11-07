# MOIS_OTHER 일반용역 원문 14건 재수집 기록 (전남광주·강원)

> **작성일**: 2026-11-07
> **작업자**: worker (task_228d0ca8dfa8)
> **대상**: `docs/analysis/mois_other_general_source_20261107.md` (브랜치 `kwanbum217/mois-general`, 커밋 `4efa9816`) 2.2절 확보 파일 14건
> **수집 시각**: 2026-11-07 18:08~18:12 KST
> **복원 위치**: `data/sources/qualification/files/`
> **판정**: candidate

---

## 1. 요약

- 14건 전부 같은 출처에서 다시 내려받아 복원했습니다. 일치 11건, 부분 일치 3건, 실패 0건입니다.
- 부분 일치 3건은 ELIS 본문 HTML이며, 크기는 원 표와 같고 요청마다 새로 발급되는 UUID 13개만 다릅니다. UUID를 정규화하면 복원본과 연속 두 번의 재수집본이 모두 바이트 동일합니다.
- 원 표에 출처 URL이 없던 8번(전남광주 지침 제정안 HWPX)은 ELIS 입법예고 상세(광주광역시 입법예고 제2026-21호, 공고일 2026-06-04)의 첨부 2번에서 찾아 내려받았고 SHA-256이 일치합니다.

---

## 2. 복원 경로 규칙

`.cache/` 와 `data/sources/qualification/files/` 는 모두 `.gitignore` 215행 이하 대상입니다. 원 표 2.2절의 `.cache/mois_other_general/` 은 임시 수집 캐시였으므로, 영구 보관 위치인 `data/sources/qualification/files/` 아래에 같은 하위 경로와 파일명을 유지해 두었습니다.

| 원 표 경로 | 복원 경로 |
| --- | --- |
| `.cache/mois_other_general/<이하>` | `data/sources/qualification/files/mois_other_general/<이하>` |
| `data/sources/qualification/files/jn_gj/<파일명>` | 같음 |

`.cache/mois_other_general/` 아래 원 경로 자체는 복원하지 않았습니다.

---

## 3. 파일별 재수집 결과

| # | 원 표 경로 | 복원 경로 | 출처 URL | 원 SHA-256 | 재수집 SHA-256 | 일치 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `.cache/mois_other_general/elis/jngj/001.bin` | `data/sources/qualification/files/mois_other_general/elis/jngj/001.bin` | `https://www.elis.go.kr/allalr/attListDown?alrNo=12000091007019&histNo=001&attlistSn=001` | `691aaba3f21b98491c34c92ee56249fb64b63d2765d14fafd88f1e2ec8e962d1` | `691aaba3f21b98491c34c92ee56249fb64b63d2765d14fafd88f1e2ec8e962d1` | 일치 |
| 2 | `.cache/mois_other_general/elis/jngj_001.html` | `data/sources/qualification/files/mois_other_general/elis/jngj_001.html` | `https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=12000091007019&histNo=001&menuNm=main` | `d195b9a16ddaa3336f57d766e7330aad16a290f8bc0500e7d73887bfcf2b4159` | `2712b196000d3947aad1e54d82cadf72bee60f950736b6025855af53bf57e8f2` | 부분 일치(4.1절) |
| 3 | `.cache/mois_other_general/elis/jn_005.html` | `data/sources/qualification/files/mois_other_general/elis/jn_005.html` | `https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=46000007006065&histNo=005&menuNm=main` | `ee8703f752f260c459f62d13bc9ce2d6fee524430837e942e0a7eb74e14b760e` | `3ccb529ed0cc1f6e27f4c1584d5b6d446c49fbcaa9dd6e6d60dea4a6ccce2181` | 부분 일치(4.1절) |
| 4 | `.cache/mois_other_general/elis/att/jn005_001.bin` | `data/sources/qualification/files/mois_other_general/elis/att/jn005_001.bin` | `https://www.elis.go.kr/allalr/attListDown?alrNo=46000007006065&histNo=005&attlistSn=001` | `919eaaaebf4f777b3e1216b9c4a0be42bdf4f22fae83356b0614a46adf8e8b60` | `919eaaaebf4f777b3e1216b9c4a0be42bdf4f22fae83356b0614a46adf8e8b60` | 일치 |
| 5 | `.cache/mois_other_general/elis/gwd/001.bin` | `data/sources/qualification/files/mois_other_general/elis/gwd/001.bin` | `https://www.elis.go.kr/allalr/attListDown?alrNo=42000035005022&histNo=001&attlistSn=001` | `cc7a84631971a07ab492c086e07c09bbdb4a914fabd4ac1c0e29d35338ba6ec7` | `cc7a84631971a07ab492c086e07c09bbdb4a914fabd4ac1c0e29d35338ba6ec7` | 일치 |
| 6 | `.cache/mois_other_general/elis/gwd/012.bin` | `data/sources/qualification/files/mois_other_general/elis/gwd/012.bin` | `https://www.elis.go.kr/allalr/attListDown?alrNo=42000035005022&histNo=001&attlistSn=012` | `47d97640a2d4e4ae1c38c3c3e9e7a595373c075209433f9c0729186016fda5e1` | `47d97640a2d4e4ae1c38c3c3e9e7a595373c075209433f9c0729186016fda5e1` | 일치 |
| 7 | `.cache/mois_other_general/elis/gwd_001.html` | `data/sources/qualification/files/mois_other_general/elis/gwd_001.html` | `https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=42000035005022&histNo=001&menuNm=main` | `93321fb71b07053875f49604a988ada6b48b602e001a22b6157e5f0821c896eb` | `ad81b939ffbca0f7a34005d7e4b643b6afdbc491c17432f76a87f67e2d6076f9` | 부분 일치(4.1절) |
| 8 | `data/sources/qualification/files/jn_gj/a689c5afafec_전남광주통합특별시 2.+[붙임]+전남광주통합특별시+일반용역+적격심사+세부지침+제정안.hwpx` | 같음 | `https://www.elis.go.kr/lgsltntc/attFileDown.do?adFileNm=2.%20%5B%EB%B6%99%EC%9E%84%5D%20%EC%A0%84%EB%82%A8%EA%B4%91%EC%A3%BC%ED%86%B5%ED%95%A9%ED%8A%B9%EB%B3%84%EC%8B%9C%20%EC%9D%BC%EB%B0%98%EC%9A%A9%EC%97%AD%20%EC%A0%81%EA%B2%A9%EC%8B%AC%EC%82%AC%20%EC%84%B8%EB%B6%80%EC%A7%80%EC%B9%A8%20%EC%A0%9C%EC%A0%95%EC%95%88.hwpx&realFileNm=6290000_EC37FC4030F44dd3AB51DD1966598906.hwpx` | `a689c5afafec719e8d546212062aa0fe29685eb794ea6dbe30f2975e56b439ad` | `a689c5afafec719e8d546212062aa0fe29685eb794ea6dbe30f2975e56b439ad` | 일치(4.2절) |
| 9 | `.cache/mois_other_general/raw/R26BK01560778_000_1.bin` | `data/sources/qualification/files/mois_other_general/raw/R26BK01560778_000_1.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01560778&bidPbancOrd=000&fileType=&fileSeq=1&prcmBsneSeCd=03` | `9dff6e63a21096945b050baa26bfbf85595dd9dc40b2231e3e3e09970ab647dc` | `9dff6e63a21096945b050baa26bfbf85595dd9dc40b2231e3e3e09970ab647dc` | 일치 |
| 10 | `.cache/mois_other_general/raw/R26BK01560778_000_3.bin` | `data/sources/qualification/files/mois_other_general/raw/R26BK01560778_000_3.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01560778&bidPbancOrd=000&fileType=&fileSeq=3&prcmBsneSeCd=03` | `dc4fb8a9b896231d47c08fdf31fee1d2ebd68ae2acf4fc84fe582c2ad4d62ebd` | `dc4fb8a9b896231d47c08fdf31fee1d2ebd68ae2acf4fc84fe582c2ad4d62ebd` | 일치 |
| 11 | `.cache/mois_other_general/raw/R26BK01577453_000_1.bin` | `data/sources/qualification/files/mois_other_general/raw/R26BK01577453_000_1.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01577453&bidPbancOrd=000&fileType=&fileSeq=1&prcmBsneSeCd=03` | `21777daf4f59fd5d2543a37638a32fcb25df8e09eb02919cf39b7328436f2eb9` | `21777daf4f59fd5d2543a37638a32fcb25df8e09eb02919cf39b7328436f2eb9` | 일치 |
| 12 | `.cache/mois_other_general/raw/R25BK01139979_001_1.bin` | `data/sources/qualification/files/mois_other_general/raw/R25BK01139979_001_1.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01139979&bidPbancOrd=001&fileType=&fileSeq=1&prcmBsneSeCd=03` | `81e729592fdd4cc496a757d0b2f06498b4239063f101885881265846d0fa37a4` | `81e729592fdd4cc496a757d0b2f06498b4239063f101885881265846d0fa37a4` | 일치 |
| 13 | `.cache/mois_other_general/raw/R25BK01139979_001_2.bin` | `data/sources/qualification/files/mois_other_general/raw/R25BK01139979_001_2.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01139979&bidPbancOrd=001&fileType=&fileSeq=2&prcmBsneSeCd=03` | `8b89d88bd56e10d959344f2a39c362b9e11b6d9d24381613e07fff5b7a301458` | `8b89d88bd56e10d959344f2a39c362b9e11b6d9d24381613e07fff5b7a301458` | 일치 |
| 14 | `.cache/mois_other_general/raw/R25BK01139979_001_4.bin` | `data/sources/qualification/files/mois_other_general/raw/R25BK01139979_001_4.bin` | `https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01139979&bidPbancOrd=001&fileType=&fileSeq=4&prcmBsneSeCd=03` | `83519e769abc00c93d9bc8b01bbdc0b6667b553597ec7b1cc6fa59be1a6a3728` | `83519e769abc00c93d9bc8b01bbdc0b6667b553597ec7b1cc6fa59be1a6a3728` | 일치 |

크기는 원 표와 전건 같습니다(1번 65,024 / 2번 71,916 / 3번 78,147 / 4번 30,720 / 5번 96,768 / 6번 58,368 / 7번 70,450 / 8번 222,259 / 9번 58,880 / 10번 59,904 / 11번 58,880 / 12번 77,312 / 13번 71,680 / 14번 1,432,919 bytes).

---

## 4. 불일치·실패 사유

### 4.1 ELIS 본문 HTML 3건: 동적 토큰

- ELIS `selectAlrBdtOne` 응답은 요청마다 CSRF 계열 UUID 13개를 새로 발급합니다. 첫 차이는 `<meta name="_csrf" content="<UUID>">` 입니다.
- 같은 URL을 1.5초 간격으로 두 번 받아 UUID를 `UUID`로 치환하면 두 응답이 바이트 동일합니다. 복원본도 같은 정규화에서 두 응답과 동일합니다.
- 따라서 원 표의 SHA-256은 그 수집 시점의 토큰값을 포함한 값이며 같은 바이트를 다시 만들 수 없습니다. 본문 내용 차이는 없습니다.
- 실패로 처리하지 않은 이유는 크기와 정규화 내용이 모두 원 표와 같기 때문입니다.

### 4.2 원 표에 URL이 없던 8번

- 원 표는 출처를 `ELIS 입법예고 첨부(사전 확보, URL 미기록)`으로만 적었습니다.
- ELIS 입법예고 목록에서 `전남광주통합특별시 일반용역 적격심사 세부지침(안) 행정예고`(광주광역시 입법예고 제2026-21호, 공고일 2026-06-04, `pbancSn=1504`, `srchCtpvCd=29`, `srchSggCd=000`)를 찾았습니다.
- 상세 페이지 첨부 2번은 표시명이 `2. [붙임] 전남광주통합특별시 일반용역 적격심사 세부지침 제정안.hwpx`이고 저장명이 `6290000_EC37FC4030F44dd3AB51DD1966598906.hwpx`입니다. 내려받은 파일이 222,259 bytes, SHA-256 `a689c5afafec...`로 원 표와 같아 같은 파일로 확인했습니다.
- 원 표의 파일명은 공백이 `+`로 치환된 형태이므로 복원 경로도 원 표·manifest에 적힌 이름을 그대로 썼습니다.

---

## 5. 남은 위험

1. 2·3·7번은 원 표 SHA-256과 바이트 단위로 같지 않습니다. 이 3건의 해시를 고정값으로 검증하는 자동화가 있으면 예외 처리하거나, 본문 동등성(크기 + UUID 정규화)으로 판정해야 합니다.
2. `.cache/mois_other_general/` 하위 원 경로는 복원하지 않았습니다. 그 경로를 직접 인용하는 문서나 스크립트가 있으면 `data/sources/qualification/files/mois_other_general/` 로 바꿔야 합니다.
3. `data/sources/qualification/files/` 는 `.gitignore` 대상이라 복원한 14건은 이 커밋에 포함되지 않습니다. 다른 워크트리나 새 클론에서는 3절 URL로 다시 내려받아야 합니다.
4. ELIS·나라장터 응답은 시점에 따라 달라질 수 있습니다. 이 기록은 2026-11-07 수집분 기준입니다.
