-- StatMan durable storage.
-- JSON documents back the current match-pack, import, video-job, and season
-- stores. The relational tables are unused in this phase; Phase 2 (AI video
-- tagger, review queue, squads, lineups/subs) writes them directly.

CREATE TABLE IF NOT EXISTS documents (
    collection TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, doc_key)
);

CREATE INDEX IF NOT EXISTS documents_collection_updated_idx
    ON documents (collection, updated_at DESC);

COMMENT ON TABLE documents IS
    'JSON blobs for match packs, imports, video jobs, and season caches. Video binaries are not stored here.';

CREATE TABLE IF NOT EXISTS squads (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    competition_id INTEGER,
    season_id INTEGER,
    external_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE squads IS
    'Stable squad identity across matches. Phase 2 links players and lineups here.';

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    squad_id TEXT REFERENCES squads (id) ON DELETE SET NULL,
    display_name TEXT NOT NULL,
    shirt_number INTEGER,
    external_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS players_squad_idx ON players (squad_id);

COMMENT ON TABLE players IS
    'Stable player ids. external_ids maps provider keys (statsbomb, opta, ...) to this row.';

COMMENT ON COLUMN players.id IS
    'Stable id (uuid or provider id). Do not reuse an id for a different person.';

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    competition_id INTEGER,
    season_id INTEGER,
    external_id TEXT,
    kickoff_at TIMESTAMPTZ,
    home_team_name TEXT,
    away_team_name TEXT,
    home_squad_id TEXT REFERENCES squads (id) ON DELETE SET NULL,
    away_squad_id TEXT REFERENCES squads (id) ON DELETE SET NULL,
    home_score INTEGER,
    away_score INTEGER,
    status TEXT NOT NULL DEFAULT 'scheduled',
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS matches_external_idx ON matches (external_id);

COMMENT ON TABLE matches IS
    'One row per match. id may be a match-pack id or another stable key. external_id is the provider game id.';

CREATE TABLE IF NOT EXISTS lineups (
    match_id TEXT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players (id),
    team_side TEXT NOT NULL CHECK (team_side IN ('home', 'away')),
    role TEXT NOT NULL CHECK (role IN ('starter', 'sub')),
    shirt_number INTEGER,
    position TEXT,
    on_clock_ms INTEGER,
    off_clock_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, player_id)
);

COMMENT ON TABLE lineups IS
    'Match squad: starters and subs. on_clock_ms/off_clock_ms are match-clock offsets in milliseconds (null while still on the pitch).';

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    period INTEGER,
    clock_ms BIGINT,
    video_ts_ms BIGINT,
    team TEXT,
    player_id TEXT REFERENCES players (id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    outcome TEXT,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    end_x DOUBLE PRECISION,
    end_y DOUBLE PRECISION,
    body_part TEXT,
    headed BOOLEAN,
    line_broken BOOLEAN,
    flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        review_status IN ('pending', 'confirmed', 'corrected')
    ),
    source TEXT NOT NULL DEFAULT 'ai' CHECK (source IN ('ai', 'human')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_match_clock_idx
    ON events (match_id, period, clock_ms);

CREATE INDEX IF NOT EXISTS events_review_queue_idx
    ON events (confidence, created_at)
    WHERE review_status = 'pending';

COMMENT ON TABLE events IS
    'Phase 2 tagged actions, one row per event. team is home/away or a team name. headed and line_broken are first-class flags; flags holds any further booleans. confidence is 0..1. review_status pending rows are the human review queue (see event_review_queue). source is ai or human.';

COMMENT ON COLUMN events.clock_ms IS
    'Milliseconds on the match clock (period clock, not a wall timestamp).';

COMMENT ON COLUMN events.video_ts_ms IS
    'Milliseconds from the start of the video file.';

COMMENT ON COLUMN events.player_id IS
    'Nullable until a player is resolved. Insert the players row before setting this.';

CREATE TABLE IF NOT EXISTS corrections (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    match_id TEXT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    reviewer TEXT,
    before JSONB NOT NULL,
    after JSONB NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS corrections_event_idx
    ON corrections (event_id, created_at);

CREATE INDEX IF NOT EXISTS corrections_match_idx
    ON corrections (match_id, created_at);

COMMENT ON TABLE corrections IS
    'Append-only human corrections log. before/after are JSON snapshots of the fields that changed (or the whole event).';

CREATE OR REPLACE VIEW event_review_queue AS
SELECT *
FROM events
WHERE review_status = 'pending'
ORDER BY confidence ASC NULLS FIRST, created_at ASC;

COMMENT ON VIEW event_review_queue IS
    'Human review queue: events still pending, lowest confidence first. Filter further on confidence in Phase 2.';
