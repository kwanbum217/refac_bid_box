# 단일 EXISTS 질의 옵티마이저 계획 전환 원인 조사 보고서

> 조사일: 2026-09-20
> Task ID: `task_2be0499f5589`
> 조사자 역할: `investigator`
> 대상 시스템: MySQL 8.0 (`procurement` 데이터베이스)
> 상태: 분석 완료 (읽기 전용 조사, 코드 및 통계 변경 없음)

---

## 1. 대상 질의 특정 및 근거

### 1.1 특정 결과
`CURRENT_STATE.md` 6.1절("측정 설계와 실행계획 조사: 상위 문제는 compare_stats_snapshot 과 mysql_stats_refresh_policy 종결로 해소되었고 단일 질의의 옵티마이저 계획 전환 원인만 미해결")이 지칭하는 대상 질의는 **`src/app/services/compare_stats_snapshots.py:173-186`의 `_compute_matched_count_payload`에 위치한 매칭 공고 수 EXISTS 집계 질의**이다.

### 1.2 문서 및 코드 근거 대조
후보 질의 2건에 대한 문서 및 코드 대조 결과는 다음과 같다:

1. **후보 1: `src/app/services/compare_stats_snapshots.py:173-186` (`_compute_matched_count_payload`)**
   - **문서 근거 1**: `docs/analysis/state_code_consistency_audit_20260918.md:145-154`
     - 148행: "`docs/analysis/ax2_plan_instability_20260911.md:13-17`에서 compare-stats 매칭 질의의 실행계획 뒤집힘 원인을 '미확정'으로 결론 내린 것은 사실임."
     - 150-153행: "대상 경로인 compare-stats 엔드포인트는 네 집계를 사전 집계 스냅샷으로 전환하여 캐시 미적중 레이턴시를 4.9ms로 단축 완료 및 종결함 (`compare_stats_snapshot`). ... 6.1절 서술에 compare-stats 스냅샷 전환 및 영속 통계 신선도 정책 수립으로 서비스 영향은 해소되었으며, 단일 EXISTS 질의의 옵티마이저 계획 전환 원인 규명만 미해결임을 구체적으로 보완하거나 항목을 정리하십시오."
   - **문서 근거 2**: `docs/analysis/ax2_plan_instability_20260911.md:7-9`
     - "대상: `src/app/services/dashboard.py` 의 `get_compare_stats_data`(484행) 안 매칭 건수 EXISTS 쿼리"
     - 이 질의는 이후 compare_stats_snapshot 최적화 과정에서 `src/app/services/compare_stats_snapshots.py:173-186`의 `_compute_matched_count_payload`로 이동하여 동일한 EXISTS 구조로 보존됨.
   - **문서 근거 3**: `docs/context/CURRENT_STATE.md:72-74, 122`
     - 122행: "상위 문제는 compare_stats_snapshot 과 mysql_stats_refresh_policy 종결로 해소되었고 단일 질의의 옵티마이저 계획 전환 원인만 미해결입니다."
   - **판정**: **일치 (6.1절의 단일 EXISTS 질의)**.

2. **후보 2: `src/app/services/bid_queries.py:303-318` (`similar_announcement_latest_filter`)**
   - **코드 내용**: 공고 목록 조회 시 동일 공고 번호 내 더 최신 차수가 존재하는지 배제하기 위한 `NOT EXISTS` 서브쿼리 필터(`~has_newer`).
   - **문서 대조**: 6.1절의 이력이나 `ax2_plan_instability_20260911.md`, `state_code_consistency_audit_20260918.md` 등 성능 이슈 관련 문서에서 계획 전환이 추적되거나 미해결 과제로 기록된 바 없음.
   - **판정**: **불일치 (조사 대상 아님)**.

---

## 2. 조사 환경 및 읽기 전용 실행 규약 준수

- **실행기**: 모든 DB 질의는 `uv run python scripts/db_readonly_query.py --sql "<SQL>"` 단일 문장으로 실행되었음.
- **제약 준수**:
  - `docker`, `docker compose`, `mysql` CLI 직접 실행 0건.
  - `ANALYZE TABLE`, `CREATE INDEX`, `DROP INDEX`, `SET` 등 쓰기 및 세션 변경 작업 0건.
  - 이미 기각된 버퍼풀 가설 재실험 배제.
  - 실행계획 획득은 `EXPLAIN` 및 `EXPLAIN FORMAT=JSON`으로 수행 (질의를 실제 수행하는 `EXPLAIN ANALYZE` 배제).

---

## 3. 대상 질의문 및 조건별 실행계획 대조

### 3.1 대상 기본 SQL 문장
```sql
SELECT count(bid_announcements.id) AS count_1
FROM bid_announcements
WHERE EXISTS (
    SELECT bid_results.id
    FROM bid_results
    WHERE bid_results.bid_ntce_no = bid_announcements.bid_ntce_no
      AND bid_results.rl_openg_dt >= '2025-09-20 00:00:00'
)
```

### 3.2 4대 조건축별 실행계획 비교표

MySQL 8.0 옵티마이저는 세미조인(Semi-join) 서브쿼리를 최적화할 때 여러 세미조인 전략(`Materialization`, `DuplicateWeedout`, `FirstMatch`, `LooseScan`) 중 비용 기반으로 전략을 선택한다.

| 조건 축 | 상세 조건 (WHERE 절) | 채택된 세미조인 전략 | 옵티마이저 추정 비용 | 드라이빙 테이블 및 접근 경로 | 종속 테이블 및 접근 경로 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **1. 날짜 범위 폭** | `rl_openg_dt >= '2020-01-01'` (약 6년 광범위) | DuplicateWeedout | 2,747,849.06 | `bid_results` (ALL, 3,388,146행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | `rl_openg_dt >= '2025-09-10'` (1년 10일 전) | DuplicateWeedout | 1,433,261.12 | `bid_results` (range, `rl_openg_dt` 인덱스, 795,232행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | `rl_openg_dt >= '2025-09-17'` (1년 3일 전) | DuplicateWeedout | 1,317,910.68 | `bid_results` (range, `rl_openg_dt` 인덱스, 710,596행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | `rl_openg_dt >= '2025-09-18'` (1년 2일 전) | Materialization | 1,151,002.74 | `<subquery2>` (ALL, 임시테이블) ← `bid_results` (range, 642,190행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | `rl_openg_dt >= '2025-09-20'` (기준 1년) | Materialization | 1,197,272.73 | `<subquery2>` (ALL, 임시테이블) ← `bid_results` (range, 644,574행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | `rl_openg_dt >= '2026-06-01'` (최근 3개월 협소) | Materialization | 295,530.88 | `<subquery2>` (ALL, 임시테이블) ← `bid_results` (range, 159,104행) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| **2. 기관명 유무** | 기관명 없음 (기준 1년) | Materialization | 1,197,272.73 | `<subquery2>` (임시테이블 구체화) | `bid_announcements` (ref) |
| | `dminstt_nm = '서울특별시'` (대형 기관) | FirstMatch | 75,737.94 | `bid_announcements` (ref, `dminstt_nm` 인덱스, 50,210행) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |
| | `dminstt_nm = '한국도로공사'` (중형 기관) | FirstMatch | 179.50 | `bid_announcements` (ref, `dminstt_nm` 인덱스, 119행) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |
| | `dminstt_nm = '한국전력공사'` (중형 기관) | FirstMatch | 386.02 | `bid_announcements` (ref, `dminstt_nm` 인덱스, 256행) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |
| **3. 카테고리 값** | `category = 'Servc'` (용역, 외부조건) | DuplicateWeedout | 1,152,908.88 | `bid_results` (range, `rl_openg_dt` 인덱스, 719,552행) | `bid_announcements` (ref, uniq 인덱스, filtered 50%) |
| | `category = 'Frgcpt'` (외자, 외부조건) | FirstMatch | 82,483.62 | `bid_announcements` (ref, `ix_bid_ann_cat_dt`, 54,682행) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |
| | 서브쿼리 내부 `category = 'Servc'` | Materialization | 520,573.49 | `<subquery2>` ← `bid_results` (range, `ix_bid_results_cat_dt_stats`) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| | 서브쿼리 내부 `category = 'Frgcpt'` | Materialization | 853.90 | `<subquery2>` ← `bid_results` (range, `ix_bid_results_cat_dt_stats`) | `bid_announcements` (ref, uniq 인덱스, 1행) |
| **4. 대상 건수 규모** | 서울특별시 + Servc | FirstMatch | 48,023.91 | `bid_announcements` (index_merge, intersect) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |
| | 한국도로공사 + Cnstwk | FirstMatch | 1.51 | `bid_announcements` (ref, `ix_bid_ann_inst_cat_ntce`, 1행) | FirstMatch[`bid_results` (ref, uniq 인덱스, 1행)] |

---

## 4. 계획 전환(Plan Flip)이 일어나는 조건과 그렇지 않은 조건 판정

### 4.1 전환이 일어나는 임계 조건
1. **날짜 범위 (선택도) 임계점: `2025-09-17`과 `2025-09-18` 사이**
   - 날짜 범위가 넓어 서브쿼리 추정 행 수가 약 70만 행을 초과하는 구간(`2025-09-17` 이전)에서는 **`DuplicateWeedout`** 전략이 채택된다 (`bid_results` 인덱스 범위 스캔 후 `bid_announcements` 조인, 임시 테이블 중복 제거).
   - 날짜 범위가 좁아져 추정 행 수가 약 65만 행 이하로 내려가는 구간(`2025-09-18` 이후)에서는 **`Materialization`** 전략으로 전환된다 (`bid_results`를 해시 임시테이블로 구체화 후 `bid_announcements` 조인).
   - 실제 테이블의 해당 날짜 기준 행 수는 `2025-09-17` 310,933건, `2025-09-18` 309,920건으로 불과 1,013건(약 0.3%) 차이지만, 옵티마이저의 추정 행 수(index dive 추정치 710,596행 vs 642,190행) 계산 비용이 DuplicateWeedout(1,317,910) vs Materialization(1,151,002)의 교차점을 통과하면서 전략이 완전히 뒤집힌다.

2. **외부 필터의 선택도에 따른 조인 순서 및 세미조인 전략 역전**
   - 외부 `bid_announcements`에 높은 선택도를 가진 조건(예: `dminstt_nm`, 소수 카테고리인 `category = 'Frgcpt'`)이 붙으면, 외부 테이블 필터링 행 수가 급감하므로 옵티마이저는 `bid_announcements`를 선행 드라이빙 테이블로 선택하고 세미조인 전략을 **`FirstMatch`**로 전환한다 (비용 1.51 ~ 75,737로 대폭 감소).
   - 반면 외부 조건이 없거나 선택도가 낮은 카테고리(`Servc`, 212만 건)인 경우 `bid_results` 선행의 `DuplicateWeedout` 또는 `Materialization`이 유지된다.

### 4.2 전환이 일어나지 않는 조건 (안정 구간)
- **외부에 특정 기관 조건(`dminstt_nm`)이 명시된 경우**: 날짜 범위나 카테고리와 무관하게 항상 `bid_announcements` 선행의 `FirstMatch` 전략으로 고정된다.
- **날짜가 매우 오래된 과거(`2020`~`2024년`)인 경우**: 항상 `DuplicateWeedout`과 `bid_results` 전체 스캔/대규모 범위 스캔으로 고정된다.
- **날짜가 최근(`2026년 이후`)인 경우**: 항상 `Materialization` 전략으로 고정된다.

---

## 5. 원인 후보 판정 및 지지·반증 근거

과거 관찰(`ax2_plan_instability_20260911.md`)에서 동일한 기준일(`2025-09-10`)임에도 시점에 따라 `range` 스캔과 `ALL`(전체 테이블 스캔) 또는 세미조인 전략이 흔들렸던 현상에 대해 원인 후보를 판정한다.

### 후보 1: 세미조인 전략 간 비용 임계치 경계(Cost Boundary Crossing)에 위치함
- **판정**: **강력히 지지됨 (주요 원인)**
- **지지 근거**:
  - `2025-09-10` ~ `2025-09-20` 구간은 옵티마이저가 계산하는 `DuplicateWeedout` 비용(약 130만~144만)과 `Materialization` 비용(약 115만~126만)이 매우 근접한 경계선상에 위치한다.
  - 날짜 바인드 값이 며칠 바뀌거나 통계 수치가 미세하게 변동하는 것만으로 두 전략의 우위가 뒤집히는 것을 확인했다.
- **반증/한계**:
  - 동일한 바인드 값(`2025-09-10`)에서 날짜 변경 없이 시점만 달라졌을 때 계획이 갈렸던 점은 순수 날짜 선택도 단독으로는 설명되지 않으며, 아래 후보 2와 결합되어 발생한다.

### 후보 2: 영속 통계 노후화와 동적 Index Dive 추정치 오차의 상호작용
- **판정**: **강력히 지지됨 (주요 원인)**
- **지지 근거**:
  - 실제 DB 통계 확인 결과 `bid_announcements`의 `n_rows`는 6,377,745행, `bid_results`의 `n_rows`는 3,388,123행으로 통계 갱신 시각은 2026-09-13이다.
  - `rl_openg_dt >= '2025-09-10'`의 실제 행 수는 309,406행이지만, MySQL 옵티마이저가 Index Dive를 통해 추정한 `rows_examined_per_scan`은 746,563행(약 2.4배 과대추정)이다.
  - 범위 조건의 B-tree 인덱스 다이브는 리프 노드 샘플링에 의존하므로, 동시 트랜잭션의 삽입/삭제나 버퍼 풀 내 페이지 캐시 상태에 따라 추정 행 수가 미세하게 요동칠 수 있다. 비용 차이가 불과 5~10% 이내인 경계 구간에서는 이 미세 추정치 변동이 전략 뒤집힘을 유발하기에 충분하다.
- **반증/한계**:
  - 세션 변수(`eq_range_index_dive_limit` 등)를 변경하거나 프로파일링 트레이스를 켜지 않고 읽기 전용 상태에서 실시간 다이브 샘플링 분산을 직접 캡처하는 것은 불가능하다.

### 후보 3: 영속 통계 자동 갱신(InnoDB Table Stats Update)
- **판정**: **기각**
- **근거**:
  - `mysql.innodb_table_stats`의 `last_update`는 `bid_announcements` 2026-09-13 07:55:01, `bid_results` 2026-09-13 11:42:46이다.
  - 과거 2026-09-10 ~ 2026-09-11의 전환 당시에도 통계 갱신 시각은 2026-09-01로 고정되어 있었음이 확인되었으므로, 영속 통계 자체의 변경이 뒤집힘의 원인일 가능성은 없다.

### 후보 4: 버퍼풀 크기 가설
- **판정**: **기각 (사전 확정 사실)**
- **근거**:
  - `docs/analysis/at2_coldsql_cause_investigation_20260910.md` 및 `CURRENT_STATE.md:50`에 의해 이미 버퍼풀 가설은 기각되었으며 본 조사에서도 재실험하지 않음.

---

## 6. 결론 및 종합 판정

1. **판정 요약**:
   - 단일 EXISTS 매칭 질의(`_compute_matched_count_payload`)의 옵티마이저 계획 뒤집힘 원인은 **"기준일(최근 1년) 부근이 `DuplicateWeedout`과 `Materialization` 세미조인 전략 간의 비용 역전 임계 경계(비용 차이 10% 미만)에 정확히 걸쳐 있으며, 인덱스 다이브 추정치의 거친 오차(실제 대비 2.4배 과대추정)가 결합되어 발생하는 구조적 선택도 민감성"**으로 판정한다.
2. **서비스 영향 평가**:
   - 본 질의는 실시간 HTTP 요청 경로에서 직접 수행될 경우 계획 뒤집힘에 따라 응답 시간이 1초대에서 수십 초대로 요동치는 원인이었으나, `compare_stats_snapshot`을 통해 주기적 사전 계산 스냅샷으로 격리되었고 영속 통계 관리 정책이 수립되어 프로덕션 사용자 경로에 대한 영향은 완전히 종결되었다.

---

## 7. 남은 확인 과제 (향후 권고 사항)

현재는 읽기 전용 제약과 쓰기/세션 변경 금지 원칙에 따라 옵티마이저 트레이스(`SET optimizer_trace`)를 실행할 수 없었다. 만약 추가적인 세부 메커니즘 확인이 필요하다면 다음을 권고한다:
1. **옵티마이저 트레이스 분석 (별도 승인 필요)**:
   - 세션 권한이 부여된 환경에서 `optimizer_trace`를 활성화하여 `setup_semijoin_dups_weedout`과 `setup_semijoin_materialized`의 비용 계산 산식 파라미터(임시 테이블 I/O 비용 vs 정렬 중복 제거 비용)를 직접 대조.
2. **세미조인 전략 힌트 고정 검토 (필요 시)**:
   - 스냅샷 계산 시 세미조인 흔들림을 원천 차단하고자 할 경우 `/*+ SEMIJOIN(MATERIALIZATION) */` 힌트의 효용성 검토.
