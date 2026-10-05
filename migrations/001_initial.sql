-- Game Vault — initial schema

CREATE TABLE games (
    id              SERIAL PRIMARY KEY,
    psn_id          VARCHAR(255),
    igdb_id         INTEGER,
    title           VARCHAR(500) NOT NULL,
    platform        VARCHAR(50) NOT NULL DEFAULT 'PS5',
    cover_url       TEXT,
    description     TEXT,
    developer       VARCHAR(255),
    publisher       VARCHAR(255),
    release_date    DATE,
    genres          JSONB DEFAULT '[]',
    specifications  JSONB DEFAULT '{}',
    hltb_main_hours NUMERIC(6,2),
    hltb_complete_hours NUMERIC(6,2),
    hltb_platinum_hours NUMERIC(6,2),
    psnprofiles_slug VARCHAR(255),
    trophies_cached_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_games (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'owned'
                    CHECK (status IN ('owned', 'wishlist', 'playing', 'completed', 'platinum')),
    purchase_date   DATE,
    purchase_price  NUMERIC(8,2),
    notes           TEXT,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (game_id)
);

CREATE TABLE backlog_entries (
    id          SERIAL PRIMARY KEY,
    game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    target_date DATE,
    notes       TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (game_id),
    UNIQUE (position)
);

CREATE TABLE trophies (
    id                  SERIAL PRIMARY KEY,
    game_id             INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    psn_trophy_id       VARCHAR(100),
    name                VARCHAR(500) NOT NULL,
    description         TEXT,
    trophy_type         VARCHAR(10) NOT NULL CHECK (trophy_type IN ('bronze', 'silver', 'gold', 'platinum')),
    trophy_image_url    TEXT,
    guide_step          INTEGER,
    estimated_minutes   INTEGER,
    rarity_percentage   NUMERIC(5,2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_trophies (
    id          SERIAL PRIMARY KEY,
    trophy_id   INTEGER NOT NULL REFERENCES trophies(id) ON DELETE CASCADE,
    earned      BOOLEAN NOT NULL DEFAULT FALSE,
    earned_at   TIMESTAMPTZ,
    notes       TEXT,
    UNIQUE (trophy_id)
);

CREATE TABLE play_sessions (
    id           SERIAL PRIMARY KEY,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    session_date DATE NOT NULL DEFAULT CURRENT_DATE,
    hours_played NUMERIC(5,2) NOT NULL CHECK (hours_played > 0),
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_games_status ON user_games(status);
CREATE INDEX idx_backlog_position ON backlog_entries(position);
CREATE INDEX idx_trophies_game_id ON trophies(game_id);
CREATE INDEX idx_trophies_type ON trophies(trophy_type);
CREATE INDEX idx_play_sessions_game_id ON play_sessions(game_id);
CREATE INDEX idx_play_sessions_date ON play_sessions(session_date);
