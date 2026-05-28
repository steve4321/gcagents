CREATE TABLE IF NOT EXISTS market_signals (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    genre TEXT,
    title TEXT,
    data JSONB NOT NULL,
    score FLOAT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    genre TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    gdd JSONB,
    proposal JSONB NOT NULL,
    itch_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS game_metrics (
    id SERIAL PRIMARY KEY,
    project_id INT REFERENCES game_projects(id),
    metric_type TEXT NOT NULL,
    value FLOAT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS company_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content JSONB NOT NULL,
    importance FLOAT DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_market_signals_source ON market_signals(source);
CREATE INDEX idx_market_signals_captured ON market_signals(captured_at DESC);
CREATE INDEX idx_game_projects_status ON game_projects(status);
CREATE INDEX idx_game_metrics_project ON game_metrics(project_id, captured_at DESC);
CREATE INDEX idx_company_memory_category ON company_memory(category);
