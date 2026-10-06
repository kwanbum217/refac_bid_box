# 적격심사 근거 원문 수집 저장소

> **경로**: `data/sources/qualification/`
> **관리 스크립트**: `scripts/build_qualification_sources_manifest.py`
> **스키마**: `QUALIFICATION_SOURCES_MANIFEST_V1`

---

## 1. 목적

여러 Orca 태스크와 사용자 내려받기에 흩어져 있던 적격심사 근거 원문(HWP·HWPX·PDF),
추출 텍스트·표를 sha256 기준으로 중복 제거해 한 곳에 모으고, 파일별 출처를 manifest 로 고정합니다.
docs/analysis 보고서의 원문 인용은 이 저장소 경로를 가리킵니다.

## 2. 구조

| 경로 | 커밋 | 설명 |
| --- | --- | --- |
| `manifest.json` | 예 | 파일별 sha256·경로·출처·인용 보고서 목록 |
| `README.md` | 예 | 이 문서 |
| `files/<기관 slug>/<sha256 앞 12자>_<파일명>` | 아니오 | 원문·추출물 사본(gitignore) |

원문 사본은 용량과 재배포 문제 때문에 커밋하지 않습니다. manifest 만 커밋하면
어떤 파일이 있어야 하는지, 각 파일의 sha256 이 무엇인지 검증할 수 있습니다.

## 3. 기관 slug

| slug | 기관 |
| --- | --- |
| `busan` | 부산광역시 |
| `cb` | 충청북도 |
| `chungnam` | 충청남도 |
| `daegu` | 대구광역시 |
| `daejeon` | 대전광역시 |
| `dapa` | 방위사업청 |
| `ekr` | 한국농어촌공사 |
| `gb` | 경상북도 |
| `gg` | 경기도 |
| `gn` | 경상남도 |
| `gwd` | 강원특별자치도 |
| `iia` | 인천국제공항공사 |
| `iiac` | 인천국제공항공사 |
| `inan` | 인천광역시 |
| `jeju` | 제주특별자치도 |
| `jeonbuk` | 전북특별자치도 |
| `jn_gj` | 전남광주통합특별시 |
| `kdhc` | 한국지역난방공사 |
| `kepcoec` | 한국전력기술 |
| `kepri` | 한국전력공사 전력연구원 |
| `khnp` | 한국수력원자력 |
| `khs` | 국가유산청 |
| `knoc` | 한국석유공사 |
| `koex` | 한국도로공사 |
| `kogas` | 한국가스공사 |
| `korail` | 한국철도공사 |
| `kps` | 한전KPS |
| `krc` | 한국농어촌공사 |
| `kwater` | 한국수자원공사 |
| `lh` | 한국토지주택공사 |
| `me` | 환경부 |
| `mois` | 행정안전부 |
| `mois_exec` | 행정안전부 |
| `molit` | 국토교통부 |
| `pps` | 조달청 |
| `sejong` | 세종특별자치시 |
| `seoul` | 서울특별시 |
| `ulsan` | 울산광역시 |

## 4. manifest 항목 필드

| 필드 | 의미 |
| --- | --- |
| `sha256` | 파일 내용 해시. 중복 제거 기준이며 항목 간 유일합니다. |
| `path` | `files/` 이하 상대 경로 |
| `original_filename` | 수집 당시 파일명(오기 정정 전 이름도 보존) |
| `institution` | 실제 내용 기준 기관명. 모르면 null |
| `doc_title` | 문서 제목. 모르면 null |
| `doc_number` | 예규·지침·공고 번호. 모르면 null |
| `effective_date` | 시행일(YYYY-MM-DD). 모르면 null |
| `source_url` | 출처 URL. 모르면 null |
| `source_kind` | elis, law.go.kr, g2b_attachment, institution_site, user_download, info21c, extracted_text |
| `derived_from` | 추출물이면 원본 sha256, 아니면 null |
| `cited_by` | 이 파일을 인용하는 docs/analysis 보고서 경로 목록 |
| `first_seen` | 이 내용이 처음 확인된 EXT_SRC 하위 상대 경로 |

값을 알 수 없으면 추측하지 않고 null 로 둡니다.

## 5. 기관명 정정 2건

파일명과 실제 내용이 다른 두 건은 내용 기준으로 기관을 정정하고 원래 이름을 `original_filename` 에 보존했습니다.

| original_filename | 정정 기관 | 근거 |
| --- | --- | --- |
| `한국도로공사 589792_0_한국도로공사)일반용역 적격심사 세부기준(23.07.31 시행).hwp` | 한국공항공사 | 지침 제653호, 2023-07-20 개정 |
| `한전KPS 2.(예고)한전 일반용역 적격심사 세부기준 전문(제2차).hwp` | 한국전력공사 | 개정 예고안(제2차) |

## 6. 재생성

```sh
uv run python scripts/build_qualification_sources_manifest.py
```

`EXT_SRC/` 를 입력으로 원문 배치, manifest 생성, 보고서 인용 갱신을 한 번에 수행합니다.
같은 입력에 대해 결정적으로 같은 결과를 냅니다(타임스탬프·절대 경로 미포함).

## 7. 현황

- 고유 파일 수: 860
- 수집 후보 파일 수(중복 포함): 2153
- 기관 수: 38
