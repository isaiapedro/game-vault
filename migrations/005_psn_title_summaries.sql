-- Fast account sync stores PSN's one-call title summaries. Detailed trophies remain lazy.
CREATE TABLE psn_title_summaries (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    official_title TEXT NOT NULL,
    platform TEXT NOT NULL,
    progress SMALLINT CHECK (progress BETWEEN 0 AND 100),
    earned_bronze INTEGER NOT NULL DEFAULT 0 CHECK (earned_bronze >= 0),
    earned_silver INTEGER NOT NULL DEFAULT 0 CHECK (earned_silver >= 0),
    earned_gold INTEGER NOT NULL DEFAULT 0 CHECK (earned_gold >= 0),
    earned_platinum INTEGER NOT NULL DEFAULT 0 CHECK (earned_platinum >= 0),
    total_bronze INTEGER NOT NULL DEFAULT 0 CHECK (total_bronze >= 0),
    total_silver INTEGER NOT NULL DEFAULT 0 CHECK (total_silver >= 0),
    total_gold INTEGER NOT NULL DEFAULT 0 CHECK (total_gold >= 0),
    total_platinum INTEGER NOT NULL DEFAULT 0 CHECK (total_platinum >= 0),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- A shared PSN trophy set can represent multiple explicitly matched platform releases.
CREATE INDEX idx_psn_title_summaries_external_id ON psn_title_summaries(external_id);
