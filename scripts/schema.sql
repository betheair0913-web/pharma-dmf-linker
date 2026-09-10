-- Vercel(Neon Postgres) 배포용 스키마.
-- 로컬 SQLite(dmf_linker.db) 의 3개 마스터를 그대로 옮긴 읽기 전용 사본이다.
-- 수집·정규화는 로컬 Streamlit 앱이 계속 담당하고, 여기에는 결과만 적재한다.

DROP TABLE IF EXISTS dmf_master;
CREATE TABLE dmf_master (
    dmf_id              TEXT PRIMARY KEY,
    ingredient_name_kr  TEXT,
    ingredient_name_en  TEXT,
    norm_ingredient_key TEXT,
    norm_base_key       TEXT,
    registrant_name     TEXT,
    manufacturer_name   TEXT,
    country_code        TEXT,
    address             TEXT,
    registration_date   TEXT,
    bizrno              TEXT,
    status              TEXT,
    first_seen_snapshot TEXT,
    last_seen_snapshot  TEXT,
    updated_at          TEXT
);

DROP TABLE IF EXISTS finished_drug_master;
CREATE TABLE finished_drug_master (
    -- 한 품목이 여러 성분을 가지므로 item_seq 는 단독으로 유일하지 않다.
    -- 로컬 SQLite 와 동일하게 (item_seq, norm_ingredient_key) 복합 기본키를 쓴다.
    item_seq            TEXT NOT NULL,
    norm_ingredient_key TEXT NOT NULL,
    norm_base_key       TEXT,
    product_name        TEXT,
    product_name_en     TEXT,
    company_name        TEXT,
    company_name_en     TEXT,
    cnsgn_manuf         TEXT,
    ingredient_code     TEXT,
    ingredient_name_kr  TEXT,
    ingredient_name_en  TEXT,
    item_status         TEXT,
    permit_date         TEXT,
    cancel_date         TEXT,
    change_date         TEXT,
    etc_otc_code        TEXT,
    atc_code            TEXT,
    bizrno              TEXT,
    first_seen_snapshot TEXT,
    last_seen_snapshot  TEXT,
    updated_at          TEXT,
    PRIMARY KEY (item_seq, norm_ingredient_key)
);

DROP TABLE IF EXISTS change_history_log;
CREATE TABLE change_history_log (
    log_id       BIGINT PRIMARY KEY,
    snapshot_ym  TEXT,
    target_type  TEXT,
    target_id    TEXT,
    target_label TEXT,
    change_type  TEXT,
    field_name   TEXT,
    before_val   TEXT,
    after_val    TEXT,
    detected_at  TEXT
);

-- 조인 키와 필터 컬럼. 성분 키 조인이 전체 질의의 병목이라 가장 중요하다.
CREATE INDEX ix_dmf_base   ON dmf_master (norm_base_key);
CREATE INDEX ix_dmf_exact  ON dmf_master (norm_ingredient_key);
CREATE INDEX ix_dmf_status ON dmf_master (status);
CREATE INDEX ix_dmf_mfr    ON dmf_master (lower(manufacturer_name) text_pattern_ops);

CREATE INDEX ix_fin_base   ON finished_drug_master (norm_base_key);
CREATE INDEX ix_fin_exact  ON finished_drug_master (norm_ingredient_key);
CREATE INDEX ix_fin_status ON finished_drug_master (item_status);
CREATE INDEX ix_fin_comp   ON finished_drug_master (lower(company_name) text_pattern_ops);

CREATE INDEX ix_chg_snap   ON change_history_log (snapshot_ym, target_type, target_id);

-- 부분 문자열 검색(LIKE '%...%')을 인덱스로 태우기 위한 trigram.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_dmf_mfr_trgm  ON dmf_master           USING gin (lower(manufacturer_name) gin_trgm_ops);
CREATE INDEX ix_dmf_ingr_trgm ON dmf_master           USING gin (lower(ingredient_name_kr) gin_trgm_ops);
CREATE INDEX ix_fin_comp_trgm ON finished_drug_master USING gin (lower(company_name) gin_trgm_ops);
CREATE INDEX ix_fin_prod_trgm ON finished_drug_master USING gin (lower(product_name) gin_trgm_ops);
