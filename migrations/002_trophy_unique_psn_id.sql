-- Add unique index for PSN trophy deduplication (partial: only when psn_trophy_id is set)
CREATE UNIQUE INDEX IF NOT EXISTS idx_trophies_game_psn_id
    ON trophies(game_id, psn_trophy_id)
    WHERE psn_trophy_id IS NOT NULL;
