-- Wardrobe 迁移 0001：全部核心表
-- 约定：时间戳为 UTC ISO8601 文本，日期为 'YYYY-MM-DD'，金额为整数（最小货币单位）
-- 核心表含 version（乐观锁）与 deleted_at（软删除），attributes 为 JSON 扩展列
-- 注意：本文件按语句拆分执行，注释中不要使用分号

CREATE TABLE brand (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    name_ja     TEXT,
    name_zh     TEXT,
    website     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE category (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES category(id) ON DELETE RESTRICT,
    level       INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
    slug        TEXT NOT NULL UNIQUE,
    name_zh     TEXT NOT NULL,
    name_ja     TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK ((level = 1 AND parent_id IS NULL) OR (level > 1 AND parent_id IS NOT NULL))
);
CREATE INDEX ix_category_parent ON category(parent_id);

CREATE TABLE tag (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'free'
                CHECK (kind IN ('free','season','occasion','style','fit','status')),
    color_hex   TEXT CHECK (color_hex IS NULL OR color_hex GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'),
    created_at  TEXT NOT NULL
);

CREATE TABLE import_job (
    id             INTEGER PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'previewed'
                   CHECK (status IN ('previewed','committed','reverted','discarded','failed')),
    actor          TEXT NOT NULL,
    source_label   TEXT,
    payload_sha256 TEXT NOT NULL,
    payload        TEXT NOT NULL,
    options        TEXT NOT NULL DEFAULT '{}',
    summary        TEXT NOT NULL DEFAULT '{}',
    error_message  TEXT,
    created_at     TEXT NOT NULL,
    committed_at   TEXT,
    reverted_at    TEXT,
    backup_file    TEXT
);

CREATE TABLE image (
    id            INTEGER PRIMARY KEY,
    sha256        TEXT NOT NULL UNIQUE,
    mime          TEXT NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    bytes         INTEGER NOT NULL,
    storage_path  TEXT NOT NULL,
    thumb_path    TEXT NOT NULL,
    source_type   TEXT NOT NULL
                  CHECK (source_type IN ('user_upload','user_photo','official_site','ai_generated','other')),
    source_url    TEXT,
    source_note   TEXT,
    dominant_hex  TEXT,
    import_job_id INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE product (
    id              INTEGER PRIMARY KEY,
    brand_id        INTEGER REFERENCES brand(id) ON DELETE RESTRICT,
    category_id     INTEGER REFERENCES category(id) ON DELETE RESTRICT,
    origin          TEXT NOT NULL DEFAULT 'catalog' CHECK (origin IN ('catalog','manual')),
    name_ja         TEXT,
    name_zh         TEXT,
    name_en         TEXT,
    gender          TEXT CHECK (gender IN ('men','women','unisex','kids','baby')),
    detail_url      TEXT,
    season_label    TEXT,
    material_text   TEXT,
    care_text       TEXT,
    care_symbols    TEXT NOT NULL DEFAULT '[]',
    description     TEXT,
    list_price      INTEGER,
    currency        TEXT NOT NULL DEFAULT 'JPY',
    verification    TEXT NOT NULL DEFAULT 'unverified' CHECK (verification IN ('unverified','verified')),
    verified_at     TEXT,
    attributes      TEXT NOT NULL DEFAULT '{}',
    notes           TEXT,
    import_job_id   INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    deleted_at      TEXT,
    CHECK (name_ja IS NOT NULL OR name_zh IS NOT NULL OR name_en IS NOT NULL)
);
CREATE INDEX ix_product_brand ON product(brand_id);
CREATE INDEX ix_product_category ON product(category_id);

CREATE TABLE product_identifier (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    scheme      TEXT NOT NULL CHECK (scheme IN ('detail_page_id','item_no','jan','sku','other')),
    value       TEXT NOT NULL,
    value_norm  TEXT NOT NULL,
    source      TEXT,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_product_identifier ON product_identifier(product_id, scheme, value_norm);
CREATE INDEX ix_identifier_lookup ON product_identifier(scheme, value_norm);

CREATE TABLE product_color (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    color_code   TEXT,
    name_ja      TEXT,
    name_zh      TEXT,
    hex          TEXT CHECK (hex IS NULL OR hex GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'),
    color_family TEXT,
    is_default   INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    sort_order   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (product_id, color_code, name_ja)
);
CREATE UNIQUE INDEX ux_product_color_default ON product_color(product_id) WHERE is_default = 1;

CREATE TABLE product_size (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    size_label  TEXT NOT NULL,
    size_system TEXT NOT NULL DEFAULT 'alpha'
                CHECK (size_system IN ('alpha','waist_cm','shoe_cm','numeric','free','other')),
    size_detail TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (product_id, size_label)
);

CREATE TABLE material_component (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    part        TEXT NOT NULL DEFAULT 'body',
    part_raw    TEXT,
    fiber       TEXT NOT NULL,
    fiber_raw   TEXT,
    percent     REAL CHECK (percent IS NULL OR (percent > 0 AND percent <= 100)),
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_material_product ON material_component(product_id);
CREATE INDEX ix_material_fiber ON material_component(fiber);

CREATE TABLE product_image (
    product_id  INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    image_id    INTEGER NOT NULL REFERENCES image(id) ON DELETE RESTRICT,
    role        TEXT NOT NULL DEFAULT 'gallery'
                CHECK (role IN ('main','gallery','color','detail','model','size_chart')),
    color_code  TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, image_id)
);

CREATE TABLE purchase (
    id            INTEGER PRIMARY KEY,
    purchased_on  TEXT NOT NULL,
    channel       TEXT NOT NULL DEFAULT 'store'
                  CHECK (channel IN ('store','online','gift','secondhand','other')),
    store_name    TEXT,
    order_no      TEXT,
    total_amount  INTEGER,
    currency      TEXT NOT NULL DEFAULT 'JPY',
    notes         TEXT,
    import_job_id INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    deleted_at    TEXT
);
CREATE INDEX ix_purchase_date ON purchase(purchased_on);
CREATE UNIQUE INDEX ux_purchase_order ON purchase(store_name, order_no)
    WHERE order_no IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE purchase_line (
    id              INTEGER PRIMARY KEY,
    purchase_id     INTEGER NOT NULL REFERENCES purchase(id) ON DELETE CASCADE,
    product_id      INTEGER REFERENCES product(id) ON DELETE RESTRICT,
    product_match   TEXT NOT NULL DEFAULT 'unmatched'
                    CHECK (product_match IN ('unmatched','suggested','confirmed')),
    item_code_raw   TEXT,
    name_raw        TEXT,
    color_code      TEXT,
    color_name      TEXT,
    color_hex       TEXT CHECK (color_hex IS NULL OR color_hex GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'),
    size_label      TEXT,
    size_system     TEXT CHECK (size_system IN ('alpha','waist_cm','shoe_cm','numeric','free','other')),
    quantity        INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    unit_price      INTEGER,
    discount_amount INTEGER,
    verification    TEXT NOT NULL DEFAULT 'unverified' CHECK (verification IN ('unverified','verified')),
    verified_at     TEXT,
    attributes      TEXT NOT NULL DEFAULT '{}',
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    CHECK ((product_match = 'unmatched') = (product_id IS NULL))
);
CREATE INDEX ix_line_purchase ON purchase_line(purchase_id);
CREATE INDEX ix_line_product ON purchase_line(product_id);

CREATE TABLE wardrobe_item (
    id               INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    purchase_line_id INTEGER REFERENCES purchase_line(id) ON DELETE RESTRICT,
    category_id      INTEGER REFERENCES category(id) ON DELETE RESTRICT,
    color_code       TEXT,
    color_name       TEXT,
    color_hex        TEXT CHECK (color_hex IS NULL OR color_hex GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'),
    size_label       TEXT,
    size_system      TEXT CHECK (size_system IN ('alpha','waist_cm','shoe_cm','numeric','free','other')),
    eff_color_code   TEXT,
    eff_color_name   TEXT,
    eff_color_hex    TEXT,
    eff_color_family TEXT,
    eff_size_label   TEXT,
    eff_size_system  TEXT,
    eff_sources      TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'owned'
                     CHECK (status IN ('owned','wishlist','returned','disposed','sold','given_away','lost')),
    condition        TEXT CHECK (condition IN ('new','good','fair','worn','damaged')),
    acquired_on      TEXT,
    retired_on       TEXT,
    refund_amount    INTEGER,
    location         TEXT,
    alterations      TEXT,
    wear_count       INTEGER NOT NULL DEFAULT 0 CHECK (wear_count >= 0),
    last_worn_on     TEXT,
    favorite         INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0,1)),
    verification     TEXT NOT NULL DEFAULT 'unverified' CHECK (verification IN ('unverified','verified')),
    verified_at      TEXT,
    attributes       TEXT NOT NULL DEFAULT '{}',
    notes            TEXT,
    import_job_id    INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    deleted_at       TEXT,
    CHECK (refund_amount IS NULL OR status = 'returned')
);
CREATE INDEX ix_item_product ON wardrobe_item(product_id);
CREATE INDEX ix_item_purchase_line ON wardrobe_item(purchase_line_id);
CREATE INDEX ix_item_status ON wardrobe_item(status);
CREATE INDEX ix_item_color_family ON wardrobe_item(eff_color_family);

CREATE TABLE item_tag (
    item_id  INTEGER NOT NULL REFERENCES wardrobe_item(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE item_image (
    item_id     INTEGER NOT NULL REFERENCES wardrobe_item(id) ON DELETE CASCADE,
    image_id    INTEGER NOT NULL REFERENCES image(id) ON DELETE RESTRICT,
    role        TEXT NOT NULL DEFAULT 'gallery' CHECK (role IN ('main','gallery','detail','tag_label','receipt')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, image_id)
);

CREATE TABLE outfit (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT,
    season         TEXT CHECK (season IN ('spring','summer','autumn','winter','all')),
    occasion       TEXT,
    rating         INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    cover_image_id INTEGER REFERENCES image(id) ON DELETE RESTRICT,
    attributes     TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    deleted_at     TEXT
);

CREATE TABLE outfit_item (
    outfit_id   INTEGER NOT NULL REFERENCES outfit(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES wardrobe_item(id) ON DELETE RESTRICT,
    slot        TEXT NOT NULL DEFAULT 'other'
                CHECK (slot IN ('outer','top','inner','bottom','dress','shoes','bag','accessory','other')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (outfit_id, item_id)
);

CREATE TABLE outfit_tag (
    outfit_id INTEGER NOT NULL REFERENCES outfit(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (outfit_id, tag_id)
);

CREATE TABLE outfit_image (
    outfit_id  INTEGER NOT NULL REFERENCES outfit(id) ON DELETE CASCADE,
    image_id   INTEGER NOT NULL REFERENCES image(id) ON DELETE RESTRICT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (outfit_id, image_id)
);

CREATE TABLE import_row (
    id            INTEGER PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES import_job(id) ON DELETE CASCADE,
    row_index     INTEGER NOT NULL,
    entity        TEXT NOT NULL
                  CHECK (entity IN ('product','purchase','purchase_line','wardrobe_item','outfit','tag','image')),
    ref           TEXT,
    action        TEXT NOT NULL CHECK (action IN ('create','update','link','skip','propose','error')),
    target_id     INTEGER,
    match_reason  TEXT,
    normalized    TEXT,
    diff          TEXT,
    errors        TEXT NOT NULL DEFAULT '[]',
    warnings      TEXT NOT NULL DEFAULT '[]',
    UNIQUE (job_id, row_index)
);

CREATE TABLE change_proposal (
    id             INTEGER PRIMARY KEY,
    entity         TEXT NOT NULL,
    entity_id      INTEGER NOT NULL,
    field          TEXT NOT NULL,
    current_value  TEXT,
    proposed_value TEXT,
    reason         TEXT,
    actor          TEXT NOT NULL,
    import_job_id  INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','accepted','rejected','superseded','withdrawn')),
    created_at     TEXT NOT NULL,
    decided_at     TEXT
);
CREATE INDEX ix_proposal_status ON change_proposal(status);
CREATE INDEX ix_proposal_entity ON change_proposal(entity, entity_id);

CREATE TABLE change_log (
    id            INTEGER PRIMARY KEY,
    occurred_at   TEXT NOT NULL,
    actor         TEXT NOT NULL,
    entity        TEXT NOT NULL,
    entity_id     INTEGER NOT NULL,
    op            TEXT NOT NULL CHECK (op IN ('create','update','delete','restore','verify','unverify','revert')),
    before        TEXT,
    after         TEXT,
    version_after INTEGER,
    import_job_id INTEGER REFERENCES import_job(id) ON DELETE SET NULL,
    proposal_id   INTEGER REFERENCES change_proposal(id) ON DELETE SET NULL
);
CREATE INDEX ix_change_entity ON change_log(entity, entity_id);
CREATE INDEX ix_change_job ON change_log(import_job_id);

CREATE VIRTUAL TABLE search_index USING fts5(
    names,
    brand,
    codes,
    colors,
    materials,
    tags,
    notes,
    tokenize = 'trigram'
);
