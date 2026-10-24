# Vision tagger benchmark (Napoli-Bodo, 7 x 15 s clips)
Clips: goal 31' (Riccio, ast Pereyra) @1848, FK @798, corners @4096/@4415, open play @600/@1824/@4060.
Ground truth is approximate: ball (2-4 px) not visible to the annotator either; pass counts are loose ranges.
Key recall over 5 key events (goal, shot, FK, 2 corners), ±2 s with lenient in-clip fallback.

| variant | key recall | prec | cost/clip | /90 min (540 clips) |
|---|---|---|---|---|
| A prod: flash2.5 10f 768/480p schema | 2/5 | .40 | .0020 | $1.08 |
| C flash2.5 10f 1280 schema (run 1 / run 2) | 4/5 / 4/5 | .44 / .67 | .004 | $2.1-2.3 |
| B/D 30f 768/1280 | 3/5 / 3/5 | .30/.14 | .006/.008 | $3.2/$4.4 |
| E-H v2 prompt 30f / 3fps / crop | 1-2/5 | .25-.50 | .008 | ~$4.2 |
| I 7.5 s clips 15f | 3/5 | .30 | .007 | $3.9 |
| J native video flash2.5 | 3/5 | .33 | .006 | $3.3 |
| K/S/T v2 json_object 30f/10f/15f | 3/5, 2-3/5, 3/5 | .38-.50 | .004-.008 | $2.3-4.4 |
| L + reasoning | 2/5 | .29 | .016 | $8.4 |
| M pro2.5 30f 1280 | 4/5 | .36 | .055 | $30 |
| R pro2.5 video | 2/5 | .50 | .066 | $36 |
| N/O/P/Q flash3.8 | 0-2/5 | .5-1.0 | .013-.051 | $7-28 |
| U flash3.5 low reasoning | 1/5 | .50 | .045 | $24 |
