-- tests/fixtures/ngram_mysql_init.sql
-- Isolated MySQL 8 test schema and fixture data for ngram FULLTEXT prefilter equivalence tests.
-- Non-negotiable: This fixture is used exclusively by isolated CI test containers, NEVER on production.

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `bid_results`;
DROP TABLE IF EXISTS `bid_announcements`;

CREATE TABLE `bid_announcements` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `bid_ntce_no` VARCHAR(50) NOT NULL,
    `bid_ntce_nm` VARCHAR(255) DEFAULT NULL,
    `dminstt_nm` VARCHAR(255) NOT NULL,
    `category` VARCHAR(50) NOT NULL,
    -- 운영 스키마와 같은 datetime(6) 이며, 하네스의 date 필터 조합이 대상 구간에 들어오도록
    -- 기본값을 둡니다. 날짜 자체는 검증 대상이 아니라 조합을 성립시키는 상수입니다.
    `bid_ntce_dt` DATETIME(6) DEFAULT '2025-06-01 00:00:00.000000',
    FULLTEXT KEY `ft_dminstt_nm` (`dminstt_nm`) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `bid_results` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `bid_ntce_no` VARCHAR(50) NOT NULL,
    `dminstt_nm` VARCHAR(255) NOT NULL,
    `bidwinnr_nm` VARCHAR(255) NOT NULL,
    `category` VARCHAR(50) NOT NULL,
    `rl_openg_dt` DATETIME(6) DEFAULT '2025-06-01 00:00:00.000000',
    FULLTEXT KEY `ft_dminstt_nm` (`dminstt_nm`) WITH PARSER ngram,
    FULLTEXT KEY `ft_bidwinnr_nm` (`bidwinnr_nm`) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- ==============================================================================
-- 10 Baseline Keywords & 14 Edge Classes Test Data
-- ==============================================================================

-- 1. F3 Baseline Keywords (10종) & Categories ('Servc', 'Cnstwk')
INSERT INTO `bid_announcements` (`bid_ntce_no`, `bid_ntce_nm`, `dminstt_nm`, `category`) VALUES
('ANN-BASE-01', '서울시 스마트 교통망 구축 용역', '서울특별시', 'Servc'),
('ANN-BASE-02', '서울 역사 보수 공사', '서울특별시', 'Cnstwk'),
('ANN-BASE-03', '거제 해양 관광 개발 계획 수립', '거제', 'Servc'),
('ANN-BASE-04', '거제 방파제 보강 공사', '거제', 'Cnstwk'),
('ANN-BASE-05', '공사 관리 소프트웨어 도입', '공사', 'Servc'),
('ANN-BASE-06', '도로 환경 정비 공사', '공사', 'Cnstwk'),
('ANN-BASE-07', '거제시 청사 전산망 유지보수', '거제시', 'Servc'),
('ANN-BASE-08', '거제시 보건소 신축 공사', '거제시', 'Cnstwk'),
('ANN-BASE-09', '교육청 정보시스템 운영 지원', '교육청', 'Servc'),
('ANN-BASE-10', '교육청 청사 시설 개선 공사', '교육청', 'Cnstwk'),
('ANN-BASE-11', '한국전 배전망 모니터링 시스템 구축', '한국전', 'Servc'),
('ANN-BASE-12', '한국전력 송전탑 보수 공사', '한국전', 'Cnstwk'),
('ANN-BASE-13', '한국토지주택공사 주거환경 조사 용역', '한국토지주택공사', 'Servc'),
('ANN-BASE-14', '한국토지주택공사 단지 조성 공사', '한국토지주택공사', 'Cnstwk'),
('ANN-BASE-15', '한국도로공사 고속도로 관제 시스템 용역', '한국도로공사', 'Servc'),
('ANN-BASE-16', '한국도로공사 교량 내진 보강 공사', '한국도로공사', 'Cnstwk'),
('ANN-BASE-17', '부산광역시 빅데이터 플랫폼 구축', '부산광역시', 'Servc'),
('ANN-BASE-18', '부산광역시 지하차도 개설 공사', '부산광역시', 'Cnstwk'),
('ANN-BASE-19', '경찰청 사이버 보안 관제 용역', '경찰청', 'Servc'),
('ANN-BASE-20', '경찰청 파출소 리모델링 공사', '경찰청', 'Cnstwk');

INSERT INTO `bid_results` (`bid_ntce_no`, `dminstt_nm`, `bidwinnr_nm`, `category`) VALUES
('RES-BASE-01', '서울특별시', '주식회사 서울교통솔루션', 'Servc'),
('RES-BASE-02', '서울특별시', '주식회사 한양건설', 'Cnstwk'),
('RES-BASE-03', '거제', '주식회사 거제해양엔지니어링', 'Servc'),
('RES-BASE-04', '거제', '거제종합건설', 'Cnstwk'),
('RES-BASE-05', '공사', '대한공사정보시스템', 'Servc'),
('RES-BASE-06', '공사', '삼우공사건설', 'Cnstwk'),
('RES-BASE-07', '거제시', '거제시정보통신', 'Servc'),
('RES-BASE-08', '거제시', '거제시개발건설', 'Cnstwk'),
('RES-BASE-09', '교육청', '주식회사 교육청미디어', 'Servc'),
('RES-BASE-10', '교육청', '교육청시설건설', 'Cnstwk'),
('RES-BASE-11', '한국전', '주식회사 한국전력기술', 'Servc'),
('RES-BASE-12', '한국전', '한국전업공사', 'Cnstwk'),
('RES-BASE-13', '한국토지주택공사', '주식회사 한국토지주택컨설팅', 'Servc'),
('RES-BASE-14', '한국토지주택공사', '한국토지주택종합건설', 'Cnstwk'),
('RES-BASE-15', '한국도로공사', '주식회사 한국도로공사엔지니어링', 'Servc'),
('RES-BASE-16', '한국도로공사', '한국도로공사보수건설', 'Cnstwk'),
('RES-BASE-17', '부산광역시', '부산광역시정보화진흥원', 'Servc'),
('RES-BASE-18', '부산광역시', '부산광역시도시개발건설', 'Cnstwk'),
('RES-BASE-19', '경찰청', '주식회사 경찰청보안통신', 'Servc'),
('RES-BASE-20', '경찰청', '경찰청시설관리건설', 'Cnstwk'),
-- bidwinnr_nm 기준선 매칭 전용 레코드
('RES-BASE-WIN-01', '인천광역시', '서울', 'Servc'),
('RES-BASE-WIN-02', '인천광역시', '거제', 'Servc'),
('RES-BASE-WIN-03', '인천광역시', '공사', 'Servc'),
('RES-BASE-WIN-04', '인천광역시', '거제시', 'Servc'),
('RES-BASE-WIN-05', '인천광역시', '교육청', 'Servc'),
('RES-BASE-WIN-06', '인천광역시', '한국전', 'Servc'),
('RES-BASE-WIN-07', '인천광역시', '한국토지주택공사', 'Servc'),
('RES-BASE-WIN-08', '인천광역시', '한국도로공사', 'Servc'),
('RES-BASE-WIN-09', '인천광역시', '부산광역시', 'Servc'),
('RES-BASE-WIN-10', '인천광역시', '경찰청', 'Servc'),
('RES-BASE-WIN-11', '인천광역시', '서울', 'Cnstwk'),
('RES-BASE-WIN-12', '인천광역시', '거제', 'Cnstwk'),
('RES-BASE-WIN-13', '인천광역시', '공사', 'Cnstwk'),
('RES-BASE-WIN-14', '인천광역시', '거제시', 'Cnstwk'),
('RES-BASE-WIN-15', '인천광역시', '교육청', 'Cnstwk'),
('RES-BASE-WIN-16', '인천광역시', '한국전', 'Cnstwk'),
('RES-BASE-WIN-17', '인천광역시', '한국토지주택공사', 'Cnstwk'),
('RES-BASE-WIN-18', '인천광역시', '한국도로공사', 'Cnstwk'),
('RES-BASE-WIN-19', '인천광역시', '부산광역시', 'Cnstwk'),
('RES-BASE-WIN-20', '인천광역시', '경찰청', 'Cnstwk');

-- 2. 14 Edge Classes Test Data
INSERT INTO `bid_announcements` (`bid_ntce_no`, `bid_ntce_nm`, `dminstt_nm`, `category`) VALUES
('ANN-EDGE-01', '서울특별시 청사 안내 표지판 정비', '서울특별시', 'Servc'),
('ANN-EDGE-01B', '경기도 성남시 환경개선사업', '경기도 성남시', 'Servc'),
('ANN-EDGE-02', '강남구청 정보시스템 유지보수', '강남구청', 'Servc'),
('ANN-EDGE-03', '서울특별시 강남구 공공시설 관리 용역', '서울특별시 강남구', 'Servc'),
('ANN-EDGE-04', '한국도로공사(본사) 보안 점검 용역', '한국도로공사(본사)', 'Servc'),
('ANN-EDGE-05', '서울-경기 광역 교통망 타당성 조사', '서울-경기', 'Servc'),
('ANN-EDGE-06', '기획/관리 본부 업무자동화 컨설팅', '기획/관리', 'Servc'),
('ANN-EDGE-07', 'K-water2026 차세대 수자원 플랫폼', 'K-water2026', 'Servc'),
('ANN-EDGE-08', '한국전력 연구용역', '한국', 'Servc'),
('ANN-EDGE-09', '100% 달성 클린에너지 사업', '100%', 'Servc'),
('ANN-EDGE-10', '공사_1차 현장 안전진단 용역', '공사_1차', 'Servc'),
('ANN-EDGE-11', '공사\'s 협력사 교육 프로그램', '공사\'s', 'Servc'),
('ANN-EDGE-12', '+공사* 기획 관리 용역', '+공사*', 'Servc'),
('ANN-EDGE-13', '한국농어촌공사전남지역본부영광지사 수로 정비', '한국농어촌공사전남지역본부영광지사', 'Servc'),
('ANN-EDGE-14', '토지주택 종합계획 수립', '한국토지주택공사', 'Servc');

INSERT INTO `bid_results` (`bid_ntce_no`, `dminstt_nm`, `bidwinnr_nm`, `category`) VALUES
('RES-EDGE-01', '서울특별시', '주식회사 서울도시정비', 'Servc'),
('RES-EDGE-01B', '경기도 성남시', '주식회사 성남정보기술', 'Servc'),
('RES-EDGE-02', '강남구청', '주식회사 강남구청솔루션', 'Servc'),
('RES-EDGE-03', '서울특별시 강남구', '주식회사 강남엔지니어링', 'Servc'),
('RES-EDGE-04', '한국도로공사(본사)', '한국도로공사(본사)서비스', 'Servc'),
('RES-EDGE-05', '서울-경기', '서울-경기협력단', 'Servc'),
('RES-EDGE-06', '기획/관리', '기획/관리컨설팅그룹', 'Servc'),
('RES-EDGE-07', 'K-water2026', 'K-water2026파트너스', 'Servc'),
('RES-EDGE-08', '한국', '한국시스템즈', 'Servc'),
('RES-EDGE-09', '100%', '100%엔지니어링', 'Servc'),
('RES-EDGE-10', '공사_1차', '공사_1차안전관리단', 'Servc'),
('RES-EDGE-11', '공사\'s', '공사\'s파트너스', 'Servc'),
('RES-EDGE-12', '+공사*', '+공사*솔루션', 'Servc'),
('RES-EDGE-13', '한국농어촌공사전남지역본부영광지사', '한국농어촌공사전남지역본부영광지사협력사', 'Servc'),
('RES-EDGE-14', '한국토지주택공사', '토지주택개발컨설팅', 'Servc');
