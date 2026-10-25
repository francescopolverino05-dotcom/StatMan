# Auto-tag cost, spend cap and retag policy

## Cost per clip (google/gemini-2.5-flash via OpenRouter)

Calibrated on the nsat1600b test (6 calls at 5 fps: 89.6k prompt tokens, 5.3k-11.1k
completion tokens, $0.047-0.061 per call, $0.31 total).

* Gemini bills ~290 prompt tokens per second of video it samples. Clips are
  time-stretched so each sampled second is one real frame, so
  prompt tokens = 2,600 (prompt text) + 290 x clip seconds x `TAGGER_VIDEO_FPS`.
  Resolution (`TAGGER_VIDEO_HEIGHT`) does not change the token count; it only shrinks the upload.
* Prices: ~$0.375 / M prompt tokens, ~$2.50 / M completion tokens (reasoning included).

| setting | prompt tokens (60 s) | completion | cost per 60 s clip |
|---|---|---|---|
| 5 fps (old default) | 89.6k = $0.034 | ~5-11k = $0.013-0.028 | ~$0.05-0.06 |
| **2 fps, 480p (new default)** | 37.4k = $0.014 | ~5k = $0.0125 (cap 8k = $0.02) | **~$0.027** |
| 3 fps | 54.8k = $0.021 | ~5k | ~$0.033 |

* 3-minute test (4 clips: 60/60/60/16 s): ~$0.09 + ~$0.01 goal re-look; worst case with one
  re-tag on every clip ~$0.20. Hard cap $0.40.
* Full match (~95 min of video, 60 s clips with 5 s overlap ≈ 104 clips): ~$2.8-3.0, plus
  re-tags (only retag-fixable failures, at most 1 per clip). Hard cap $4.

`GET /api/autotag/tagger` shows `estimate_per_60s_clip` for the live settings.

## Settings

| env | default | meaning |
|---|---|---|
| `TAGGER_VIDEO_FPS` | 2 | real frames per second the model sees |
| `TAGGER_VIDEO_HEIGHT` | 480 | encode height |
| `TAGGER_VIDEO_BITRATE` | 150k | per sampled frame |
| `TAGGER_MAX_TOKENS` | 8000 | completion cap per call |
| `STATMAN_RETAG_MAX` | 1 | corrective re-tags per clip |
| `STATMAN_TEST_MAX_COST` | 0.40 | job cap for videos < 10 min |
| `STATMAN_JOB_MAX_COST` | 4.00 | job cap otherwise (and upper bound for tests) |
| `STATMAN_SCOREBUG_LLM_MAX_CALLS` | 20 | score-bug crop fallback calls per run |

`POST /api/autotag/matches/{id}/run` takes `max_cost` (USD); it overrides the env caps for that run.

## Spend cap and cancel

Every model call (clip tag, the tagger's internal retries, re-tags, goal re-look, score-bug
fallback) first checks cancel and `spent + estimated next call <= cap`. When blocked, the job
stops (`cancelled` or `budget_stopped`, `partial: true`, `stop_reason`) and still merges and
saves the events of the clips tagged so far, the review queue and the per-clip quality records.

## Retag policy

* Retag-fixable: bad JSON, fixed cadence, even spacing, coords out of range, too few passes,
  no failed passes, missing end points / coordinates, clock outside clip, duplicates, silent stretch.
* Not fixable (camera / footage): no team seen (`team_missing`). Sent straight to review with
  the reason, no re-tag. Unreadable shirt numbers (`no_shirt_numbers`) are a warning only.

## Per-clip inspection

`GET /api/autotag/matches/{id}/clips` (add `?include_tags=true` for the cached tags) and
`GET /api/autotag/matches/{id}/clips/{index}`: window, events count, calls, tokens, cost,
error, quality score, issues (with `fixable`), attempts, stop / review reason.
