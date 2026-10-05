-- Additive evolution: original identifiers, estimates and queue positions are retained.
ALTER TABLE user_games ADD COLUMN ownership TEXT NOT NULL DEFAULT 'owned'
    CHECK (ownership IN ('owned','wanted','available'));
ALTER TABLE user_games ADD COLUMN play_state TEXT NOT NULL DEFAULT 'not_started'
    CHECK (play_state IN ('not_started','playing','paused','finished','dropped'));
ALTER TABLE user_games ADD COLUMN goal TEXT NOT NULL DEFAULT 'completionist'
    CHECK (goal IN ('story','completionist','platinum'));
ALTER TABLE user_games ADD COLUMN next_action TEXT;
UPDATE user_games SET ownership = CASE WHEN status = 'wishlist' THEN 'wanted' ELSE 'owned' END,
    play_state = CASE WHEN status = 'playing' THEN 'playing' WHEN status = 'completed' THEN 'finished' ELSE 'not_started' END;
ALTER TABLE backlog_entries ADD COLUMN goal TEXT NOT NULL DEFAULT 'completionist'
    CHECK (goal IN ('story','completionist','platinum'));
ALTER TABLE backlog_entries ADD COLUMN user_remaining_hours NUMERIC(8,2) CHECK (user_remaining_hours >= 0);
ALTER TABLE games ADD COLUMN hltb_extra_hours NUMERIC(8,2);
ALTER TABLE games ADD COLUMN hltb_completionist_hours NUMERIC(8,2);
ALTER TABLE games ADD COLUMN platinum_hours NUMERIC(8,2) CHECK (platinum_hours >= 0);
ALTER TABLE games ADD COLUMN platinum_source TEXT;
ALTER TABLE games ADD COLUMN metadata_checked_at TIMESTAMPTZ;
ALTER TABLE games ADD COLUMN platinum_feasibility TEXT NOT NULL DEFAULT 'unknown'
    CHECK (platinum_feasibility IN ('attainable','blocked','unknown','not_applicable'));
ALTER TABLE games ADD COLUMN platinum_blocker_reason TEXT;
ALTER TABLE games ADD COLUMN platinum_evidence_url TEXT;
ALTER TABLE games ADD COLUMN platinum_checked_at TIMESTAMPTZ;
UPDATE games SET hltb_extra_hours = hltb_complete_hours, hltb_completionist_hours = hltb_platinum_hours;
UPDATE games SET platinum_feasibility='blocked',
    platinum_blocker_reason='Legacy collection marks platinum unattainable; specific reason unverified'
WHERE platform='PS3' AND title IN ('Battlefield 3','Call of Duty: Black Ops 2','FIFA 09','FIFA 12',
    'FIFA 13','FIFA 15','Killzone 2','LittleBigPlanet','LittleBigPlanet 2','Mortal Kombat 9',
    'Mercenaries 2: World in Flames','NBA 2K9','Need for Speed: The Run','SmackDown vs. Raw 2008',
    'Star Wars: The Force Unleashed');
CREATE TABLE provider_mappings (
    id SERIAL PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, external_id TEXT NOT NULL,
    match_state TEXT NOT NULL DEFAULT 'suggested' CHECK (match_state IN ('confirmed','suggested','legacy')),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(provider,external_id,game_id)
);
CREATE UNIQUE INDEX provider_one_confirmed_release ON provider_mappings(game_id,provider) WHERE match_state='confirmed';
INSERT INTO provider_mappings(game_id,provider,external_id,match_state)
SELECT id,'igdb',igdb_id::text,'legacy' FROM games WHERE igdb_id IS NOT NULL;
INSERT INTO provider_mappings(game_id,provider,external_id,match_state)
SELECT id,'psn',psn_id,'legacy' FROM games WHERE psn_id IS NOT NULL;
CREATE TABLE game_time_estimates (
    id SERIAL PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ('story','main_extra','completionist','platinum')),
    hours NUMERIC(8,2) NOT NULL CHECK(hours >= 0), provider TEXT NOT NULL,
    source_ref TEXT, retrieved_at TIMESTAMPTZ, match_confidence TEXT NOT NULL DEFAULT 'unknown',
    UNIQUE(game_id,category,provider)
);
INSERT INTO game_time_estimates(game_id,category,hours,provider,match_confidence)
SELECT id,'story',hltb_main_hours,'legacy_hltb','unverified' FROM games WHERE hltb_main_hours > 0
UNION ALL SELECT id,'main_extra',hltb_extra_hours,'legacy_hltb','unverified' FROM games WHERE hltb_extra_hours > 0
UNION ALL SELECT id,'completionist',hltb_completionist_hours,'legacy_hltb','unverified' FROM games WHERE hltb_completionist_hours > 0;
CREATE TABLE trophy_sets (
    id SERIAL PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, external_id TEXT NOT NULL, has_platinum BOOLEAN,
    UNIQUE(provider,external_id,game_id)
);
CREATE TABLE trophy_groups (
    id SERIAL PRIMARY KEY, trophy_set_id INTEGER NOT NULL REFERENCES trophy_sets(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL, name TEXT NOT NULL, is_base_game BOOLEAN,
    UNIQUE(trophy_set_id,external_id)
);
ALTER TABLE trophies ADD COLUMN trophy_set_id INTEGER REFERENCES trophy_sets(id) ON DELETE SET NULL;
ALTER TABLE trophies ADD COLUMN group_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE trophies ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_trophies ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE user_trophies ADD COLUMN observed_at TIMESTAMPTZ;
ALTER TABLE user_trophies ADD COLUMN manual_override BOOLEAN NOT NULL DEFAULT FALSE;
-- Existing observations have unknown origin; do not claim they were manually verified.
UPDATE user_trophies SET source = 'legacy';
CREATE TABLE play_state_history (
    id SERIAL PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    previous_state TEXT, play_state TEXT NOT NULL, changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE integration_jobs (
    id SERIAL PRIMARY KEY, provider TEXT NOT NULL, state JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Reconcile only the compatibility projection; do not infer story completion or change the queue.
UPDATE user_games ug SET status=CASE
    WHEN ownership='wanted' THEN 'wishlist'
    WHEN EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
        WHERE t.game_id=ug.game_id AND t.trophy_type='platinum' AND ut.earned) THEN 'platinum'
    WHEN play_state='finished' THEN 'completed'
    WHEN play_state='playing' THEN 'playing' ELSE 'owned' END;
