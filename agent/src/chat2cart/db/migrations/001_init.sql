CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE inbound_messages (
    id TEXT PRIMARY KEY,
    chat_jid TEXT NOT NULL,
    sender_jid TEXT NOT NULL,
    sender_pn TEXT,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    claimed_at TEXT,
    finished_at TEXT,
    error TEXT,
    run_id TEXT
);

CREATE TABLE whatsapp_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL
        CHECK (state IN ('connected', 'reconnecting', 'logged_out', 'stopped')),
    changed_at TEXT NOT NULL,
    heartbeat_at TEXT,
    detail TEXT
);

CREATE TABLE lid_map (
    lid TEXT PRIMARY KEY,
    pn TEXT NOT NULL,
    learned_at TEXT NOT NULL
);

CREATE TABLE request_queue (
    id INTEGER PRIMARY KEY,
    inbound_id TEXT NOT NULL,
    items_json TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    released_at TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'released', 'done'))
);

CREATE TABLE cart_jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    job_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result_json TEXT
);

CREATE TABLE alerts (
    key TEXT PRIMARY KEY,
    last_sent_at TEXT NOT NULL
);
