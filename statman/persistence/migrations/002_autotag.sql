-- Phase 2 auto-tagging: review states, shirt/player text, per-event metadata.

ALTER TABLE events DROP CONSTRAINT IF EXISTS events_review_status_check;

ALTER TABLE events ADD CONSTRAINT events_review_status_check CHECK (
    review_status IN ('pending', 'auto', 'confirmed', 'corrected', 'rejected')
);

ALTER TABLE events ADD COLUMN IF NOT EXISTS shirt_number INTEGER;

ALTER TABLE events ADD COLUMN IF NOT EXISTS player_name TEXT;

ALTER TABLE events ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN events.review_status IS
    'pending = in the human review queue (below STATMAN_REVIEW_THRESHOLD or flagged); auto = accepted by threshold; confirmed / corrected = reviewed; rejected = deleted by a reviewer (kept for audit, excluded from stats).';

COMMENT ON COLUMN events.flags IS
    'Event attributes from the Phase 2 taxonomy (completed, key_pass, xg, on_target, color, ...).';

COMMENT ON COLUMN events.meta IS
    'Tagger metadata: clip_ids, issues, review_reason.';

CREATE OR REPLACE VIEW event_review_queue AS
SELECT *
FROM events
WHERE review_status = 'pending'
ORDER BY confidence ASC NULLS FIRST, created_at ASC;
