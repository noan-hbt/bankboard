-- =====================================================================
-- Bankboard — Personal Finance OS — initial schema (P0 + structural P1)
-- Conventions
--   * money: NUMERIC(19,4), signed (negative = outflow)
--   * every user-owned row carries user_id (isolation enforced in repos)
--   * timestamps: TIMESTAMPTZ, UTC
--   * classification columns always come with *_confidence + *_source
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- Enumerated domains (CHECK constraints rather than PG enums: cheaper to
-- evolve through migrations)
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- Users & auth
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    base_currency   CHAR(3) NOT NULL DEFAULT 'EUR',
    timezone        TEXT NOT NULL DEFAULT 'Europe/Paris',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,          -- sha256 of opaque cookie token
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    user_agent      TEXT
);
CREATE INDEX ix_user_sessions_user ON user_sessions(user_id);

CREATE TABLE user_preferences (
    user_id                 UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    min_buffer              NUMERIC(19,4),          -- NULL = computed default
    opportunity_rate        NUMERIC(6,4) NOT NULL DEFAULT 0.05,
    modules                 JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {module_key: bool}
    notification_min_level  TEXT NOT NULL DEFAULT 'important'
        CHECK (notification_min_level IN ('info','useful','important','critical')),
    settings                JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Banking connections (provider-agnostic)
-- ---------------------------------------------------------------------
CREATE TABLE bank_auth_requests (            -- anti-CSRF OAuth state
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    state_hash      TEXT NOT NULL UNIQUE,
    institution_name    TEXT NOT NULL,
    institution_country CHAR(2) NOT NULL,
    provider_auth_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ
);

CREATE TABLE bank_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,                  -- 'enable_banking', 'demo', ...
    institution_name    TEXT NOT NULL,
    institution_country CHAR(2) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','reauth_required','error','revoked')),
    consent_valid_until TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ,
    last_error          TEXT,
    last_error_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_connections_user ON bank_connections(user_id);

CREATE TABLE bank_sessions (                 -- provider session (secret, encrypted)
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id       UUID NOT NULL REFERENCES bank_connections(id) ON DELETE CASCADE,
    session_ref_enc     TEXT NOT NULL,          -- Fernet-encrypted provider session id
    valid_until         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ
);
CREATE INDEX ix_bank_sessions_connection ON bank_sessions(connection_id);

CREATE TABLE accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_id       UUID REFERENCES bank_connections(id) ON DELETE SET NULL,
    provider_account_ref TEXT,                  -- provider uid (not secret)
    name                TEXT NOT NULL,
    iban_masked         TEXT,                   -- only last 4 kept in clear
    iban_hash           TEXT,                   -- sha256 for own-account transfer matching
    currency            CHAR(3) NOT NULL,
    account_type        TEXT NOT NULL DEFAULT 'checking'
        CHECK (account_type IN ('checking','savings','investment','credit','loan','cash','other')),
    is_liquid           BOOLEAN NOT NULL DEFAULT TRUE,   -- counts in liquid assets
    is_spending         BOOLEAN NOT NULL DEFAULT TRUE,   -- counts in safe-to-spend
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_booking_date DATE,
    last_synced_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (connection_id, provider_account_ref)
);
CREATE INDEX ix_accounts_user ON accounts(user_id);

CREATE TABLE balances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    balance_type    TEXT NOT NULL,              -- ISO 20022: CLBD, ITAV, XPCD, ...
    amount          NUMERIC(19,4) NOT NULL,
    currency        CHAR(3) NOT NULL,
    reference_date  DATE NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, balance_type, reference_date)
);

-- ---------------------------------------------------------------------
-- Sync jobs
-- ---------------------------------------------------------------------
CREATE TABLE sync_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_id   UUID REFERENCES bank_connections(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','succeeded','failed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb,   -- fetched/inserted/updated/removed
    error           TEXT
);
CREATE INDEX ix_sync_jobs_connection ON sync_jobs(connection_id, started_at DESC);

-- ---------------------------------------------------------------------
-- Raw transactions — append-only source of truth
-- ---------------------------------------------------------------------
CREATE TABLE transaction_raw (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id          UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    provider_transaction_id TEXT,
    dedup_key           TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('booked','pending')),
    payload             JSONB NOT NULL,          -- exactly as received, first observation
    payload_hash        TEXT NOT NULL,
    payload_history     JSONB NOT NULL DEFAULT '[]'::jsonb,  -- later differing revisions
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, dedup_key)
);
CREATE INDEX ix_transaction_raw_user ON transaction_raw(user_id);

-- ---------------------------------------------------------------------
-- Reference data: merchants, categories, rules
-- ---------------------------------------------------------------------
CREATE TABLE categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,   -- NULL = system
    key             TEXT NOT NULL,
    name            TEXT NOT NULL,
    parent_key      TEXT,
    is_essential    BOOLEAN NOT NULL DEFAULT FALSE,
    default_kind    TEXT NOT NULL DEFAULT 'consumption',
    color           TEXT,
    UNIQUE NULLS NOT DISTINCT (user_id, key)
);

CREATE TABLE merchants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,   -- NULL = global
    key             TEXT NOT NULL,                 -- normalized slug
    name            TEXT NOT NULL,
    default_category_key TEXT,
    source          TEXT NOT NULL DEFAULT 'auto' CHECK (source IN ('seed','auto','manual')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (user_id, key)
);

CREATE TABLE merchant_aliases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    match_type      TEXT NOT NULL CHECK (match_type IN ('exact','prefix','contains','regex')),
    pattern         TEXT NOT NULL,                 -- applied to normalized label
    priority        INT NOT NULL DEFAULT 100,      -- lower = first
    UNIQUE NULLS NOT DISTINCT (user_id, match_type, pattern)
);

CREATE TABLE classification_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    priority        INT NOT NULL DEFAULT 100,
    field           TEXT NOT NULL CHECK (field IN ('label','merchant','mcc','counterparty')),
    match_type      TEXT NOT NULL CHECK (match_type IN ('exact','prefix','contains','regex')),
    pattern         TEXT NOT NULL,
    direction       TEXT CHECK (direction IN ('in','out')),
    category_key    TEXT,
    kind            TEXT,
    confidence      NUMERIC(4,3) NOT NULL DEFAULT 0.9,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- Normalized transactions
-- ---------------------------------------------------------------------
CREATE TABLE transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id          UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    raw_id              UUID NOT NULL UNIQUE REFERENCES transaction_raw(id) ON DELETE CASCADE,
    status              TEXT NOT NULL CHECK (status IN ('booked','pending')),
    booking_date        DATE NOT NULL,
    value_date          DATE,
    booked_at           TIMESTAMPTZ,                -- when time-of-day is known
    amount              NUMERIC(19,4) NOT NULL,     -- signed, account currency
    currency            CHAR(3) NOT NULL,
    original_amount     NUMERIC(19,4),
    original_currency   CHAR(3),
    label               TEXT NOT NULL,              -- best human label
    label_normalized    TEXT NOT NULL,
    counterparty_name   TEXT,
    counterparty_iban_hash TEXT,
    mcc                 TEXT,
    merchant_id         UUID REFERENCES merchants(id) ON DELETE SET NULL,
    merchant_source     TEXT,
    kind                TEXT NOT NULL DEFAULT 'consumption'
        CHECK (kind IN ('consumption','transfer','investment','income','refund','fee','debt_payment')),
    kind_confidence     NUMERIC(4,3) NOT NULL DEFAULT 0,
    kind_source         TEXT NOT NULL DEFAULT 'rule'
        CHECK (kind_source IN ('bank','rule','historical','model','manual')),
    category_key        TEXT NOT NULL DEFAULT 'uncategorized',
    category_confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    category_source     TEXT NOT NULL DEFAULT 'rule'
        CHECK (category_source IN ('bank','rule','historical','model','manual')),
    transfer_group_id   UUID,
    transfer_source     TEXT,                        -- 'rule' or 'manual'
    recurring_pattern_id UUID,
    is_excluded         BOOLEAN NOT NULL DEFAULT FALSE,   -- user hides it from analytics
    note                TEXT,
    pipeline_version    INT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_transactions_user_date ON transactions(user_id, booking_date);
CREATE INDEX ix_transactions_account_date ON transactions(account_id, booking_date);
CREATE INDEX ix_transactions_user_merchant ON transactions(user_id, merchant_id);
CREATE INDEX ix_transactions_user_category ON transactions(user_id, category_key);
CREATE INDEX ix_transactions_transfer_group ON transactions(transfer_group_id)
    WHERE transfer_group_id IS NOT NULL;

-- Multi-dimensional context tags (project, person, location, purpose, free)
CREATE TABLE tags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL,       -- 'project' | 'person' | 'location' | 'purpose' | 'free'
    value           TEXT NOT NULL,
    UNIQUE (user_id, dimension, value)
);

CREATE TABLE transaction_tags (
    transaction_id  UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag_id          UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    source          TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('rule','model','manual')),
    confidence      NUMERIC(4,3) NOT NULL DEFAULT 1,
    PRIMARY KEY (transaction_id, tag_id)
);

-- ---------------------------------------------------------------------
-- Recurring patterns & expected transactions
-- ---------------------------------------------------------------------
CREATE TABLE recurring_patterns (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_key          TEXT NOT NULL,              -- merchant/counterparty + direction
    merchant_id         UUID REFERENCES merchants(id) ON DELETE SET NULL,
    account_id          UUID REFERENCES accounts(id) ON DELETE SET NULL,
    label               TEXT NOT NULL,
    direction           TEXT NOT NULL CHECK (direction IN ('in','out')),
    kind                TEXT NOT NULL,
    category_key        TEXT NOT NULL,
    cadence             TEXT NOT NULL
        CHECK (cadence IN ('weekly','biweekly','monthly','bimonthly','quarterly','yearly','irregular')),
    period_days         NUMERIC(8,2) NOT NULL,
    day_of_month        INT,
    mean_amount         NUMERIC(19,4) NOT NULL,     -- signed
    amount_std          NUMERIC(19,4) NOT NULL,
    amount_min          NUMERIC(19,4) NOT NULL,
    amount_max          NUMERIC(19,4) NOT NULL,
    occurrences         INT NOT NULL,
    first_date          DATE NOT NULL,
    last_date           DATE NOT NULL,
    next_expected_date  DATE,
    confidence          NUMERIC(4,3) NOT NULL,
    is_subscription     BOOLEAN NOT NULL DEFAULT FALSE,
    is_salary           BOOLEAN NOT NULL DEFAULT FALSE,
    status              TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','stopped','ignored')),
    user_confirmed      BOOLEAN,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, series_key)
);

CREATE TABLE expected_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pattern_id          UUID REFERENCES recurring_patterns(id) ON DELETE CASCADE,
    account_id          UUID REFERENCES accounts(id) ON DELETE SET NULL,
    label               TEXT NOT NULL,
    category_key        TEXT NOT NULL,
    kind                TEXT NOT NULL,
    expected_date       DATE NOT NULL,
    expected_amount     NUMERIC(19,4) NOT NULL,
    range_min           NUMERIC(19,4) NOT NULL,
    range_max           NUMERIC(19,4) NOT NULL,
    confidence          NUMERIC(4,3) NOT NULL,
    prediction_source   TEXT NOT NULL
        CHECK (prediction_source IN ('recurring','income','behavior','manual','subscription','known_event')),
    status              TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','matched','missed','cancelled')),
    matched_transaction_id UUID REFERENCES transactions(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_expected_user_date ON expected_transactions(user_id, expected_date);

-- ---------------------------------------------------------------------
-- Goals (needed by safe-to-spend: committed goals)
-- ---------------------------------------------------------------------
CREATE TABLE goals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    target_amount       NUMERIC(19,4) NOT NULL CHECK (target_amount > 0),
    current_amount      NUMERIC(19,4) NOT NULL DEFAULT 0,
    target_date         DATE,
    priority            INT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    minimum_monthly_contribution NUMERIC(19,4) NOT NULL DEFAULT 0,
    desired_monthly_contribution NUMERIC(19,4) NOT NULL DEFAULT 0,
    flexibility         TEXT NOT NULL DEFAULT 'medium' CHECK (flexibility IN ('low','medium','high')),
    linked_account_id   UUID REFERENCES accounts(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','reached','paused','abandoned')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE goal_contributions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id         UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    amount          NUMERIC(19,4) NOT NULL,
    contributed_on  DATE NOT NULL,
    transaction_id  UUID REFERENCES transactions(id) ON DELETE SET NULL,
    source          TEXT NOT NULL DEFAULT 'manual'
);

-- ---------------------------------------------------------------------
-- Snapshots & metrics
-- ---------------------------------------------------------------------
CREATE TABLE financial_snapshots (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date       DATE NOT NULL,
    net_worth           NUMERIC(19,4) NOT NULL,
    liquid_assets       NUMERIC(19,4) NOT NULL,
    cash                NUMERIC(19,4) NOT NULL,
    investments         NUMERIC(19,4) NOT NULL DEFAULT 0,
    liabilities         NUMERIC(19,4) NOT NULL DEFAULT 0,
    monthly_income      NUMERIC(19,4) NOT NULL,      -- trailing 30 days
    monthly_expenses    NUMERIC(19,4) NOT NULL,      -- trailing 30 days
    savings_rate        NUMERIC(8,4),
    safe_to_spend       NUMERIC(19,4),
    financial_score     NUMERIC(5,2),
    goal_progress       NUMERIC(5,4),
    data_confidence     NUMERIC(4,3),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- sub-scores, per-account balances
    is_reconstructed    BOOLEAN NOT NULL DEFAULT FALSE,       -- backfilled from history
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, snapshot_date)
);

-- ---------------------------------------------------------------------
-- Events (outbox), insights, recommendations
-- ---------------------------------------------------------------------
CREATE TABLE domain_events (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT
);
CREATE INDEX ix_domain_events_pending ON domain_events(occurred_at) WHERE processed_at IS NULL;

CREATE TABLE insights (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint         TEXT NOT NULL,
    type                TEXT NOT NULL,
    module              TEXT NOT NULL,
    section             TEXT NOT NULL DEFAULT 'attention'
        CHECK (section IN ('attention','opportunity','info')),
    priority            TEXT NOT NULL DEFAULT 'useful'
        CHECK (priority IN ('info','useful','important','critical')),
    importance          NUMERIC(4,3) NOT NULL,
    confidence          NUMERIC(4,3) NOT NULL,
    title               TEXT NOT NULL,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence            JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_actions   JSONB NOT NULL DEFAULT '[]'::jsonb,
    state               TEXT NOT NULL DEFAULT 'new'
        CHECK (state IN ('new','ongoing','resolved','ignored')),
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    UNIQUE (user_id, fingerprint)
);
CREATE INDEX ix_insights_user_state ON insights(user_id, state);

CREATE TABLE recommendations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    insight_id      UUID REFERENCES insights(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,   -- target metric, baseline value
    status          TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed','ignored','accepted','in_progress','completed','dismissed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Feed (chronological observations shown to the user)
CREATE TABLE feed_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    type            TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'info'
        CHECK (priority IN ('info','useful','important','critical')),
    title           TEXT NOT NULL,
    data            JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key       TEXT,
    UNIQUE (user_id, dedup_key)
);
CREATE INDEX ix_feed_user_time ON feed_items(user_id, occurred_at DESC);

-- ---------------------------------------------------------------------
-- AI advisor
-- ---------------------------------------------------------------------
CREATE TABLE advisor_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE advisor_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES advisor_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
    content         TEXT NOT NULL,
    tool_calls      JSONB NOT NULL DEFAULT '[]'::jsonb,   -- name, input, output
    provider        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Dashboard
-- ---------------------------------------------------------------------
CREATE TABLE dashboard_layouts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL DEFAULT 'default',
    layout          JSONB NOT NULL,     -- [{i, widget, x, y, w, h, hidden, config}]
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- ---------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------
CREATE TABLE audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,          -- 'login', 'bank.connect', 'bank.revoke', 'data.delete'...
    target          TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- never financial values
    ip              INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_user_time ON audit_logs(user_id, created_at DESC);
