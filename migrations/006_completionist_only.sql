-- Retire selectable plans and manual remaining estimates without deleting history.
CREATE TABLE retired_collection_plans (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    collection_goal TEXT, queue_goal TEXT, user_remaining_hours NUMERIC(8,2),
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO retired_collection_plans(game_id,collection_goal,queue_goal,user_remaining_hours)
SELECT COALESCE(ug.game_id,be.game_id),ug.goal,be.goal,be.user_remaining_hours
FROM user_games ug FULL OUTER JOIN backlog_entries be ON be.game_id=ug.game_id;
UPDATE user_games SET goal='completionist';
UPDATE backlog_entries SET goal='completionist',user_remaining_hours=NULL;
ALTER TABLE user_games ADD CONSTRAINT collection_completionist_only CHECK(goal='completionist');
ALTER TABLE backlog_entries ADD CONSTRAINT queue_completionist_only CHECK(goal='completionist');
-- Existing sessions remain archived in play_sessions. No session rows are removed.
