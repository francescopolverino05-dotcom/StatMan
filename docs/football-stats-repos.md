# Football stats repos for EnjoyStats

Survey of GitHub repositories that can collect, or help you compute, the match statistics a site like EnjoyStats needs: expected goals and pressing (PPDA), possession, shots, passes and passing accuracy, progressive passes, and defensive actions (aerials, tackles, interceptions, clearances).

Stars and “last push” dates were checked on **11 October 2026**. “Good” here means a maintained library, a real open dataset, or a specialist tool with a clear job. One-off notebooks and archived scrapers are listed only when they still teach a definition or cover a gap.

The short version: the schema that matches this stat list is **SPADL** (Soccer Player Action Description Language) in [`ML-KULeuven/socceraction`](https://github.com/ML-KULeuven/socceraction). It tags passes, shots, tackles and interceptions in one table. Aerial duels are **not** a SPADL type; they have to be counted from the raw Opta/WhoScored or StatsBomb event before that conversion. Progressive passes and PPDA are **derived** from coordinates, not stored as their own event. Understat is the public source that already publishes xG and PPDA.

## What each number actually is

| Stat | What you are counting | Where it already exists | Where you have to compute it |
| --- | --- | --- | --- |
| xG | Probability a shot is a goal | StatsBomb `shot.statsbomb_xg`; Understat shot `xG`; Impect shot KPIs | Train [`soccer_xg`](https://github.com/ML-KULeuven/soccer_xg) or a distance/angle model on SPADL shots |
| npxG | xG excluding penalties | Understat `npxG` | Same models, drop `shot_penalty` |
| PPDA | Opponent passes in their own 60% of the pitch, divided by your tackles + interceptions + fouls in that zone. Lower means a harder press | Understat match `ppda` (`att / def`) via soccerdata | Count those SPADL types inside the zone. Do not mix this with StatsBomb “pressures”; that is a different event |
| Possession % | Share of time (or of on-ball actions) a team has the ball | Sofascore / FotMob / WhoScored team stat; StatsBomb `possession` id on every event | [`databallpy`](https://github.com/Alek050/databallpy) team possession from synced events, or individual possession from tracking |
| Shots | Attempts, with on/off target, body part, situation | SPADL `shot`, `shot_freekick`, `shot_penalty`; Understat shot rows; Opta miss/post/saved/goal | Filter the event table |
| Passes and accuracy | Attempted passes, and successful / attempted | SPADL `pass` (plus cross, free kick, corner, throw-in) with `success` / `fail` | `accuracy = success / (success + fail)` |
| Progressive passes | Completed passes that move the ball substantially toward the opponent goal | Not an event type. Old FBref/StatsBomb definition: a completed pass that advances the ball at least 10 yards toward goal, or any completed pass into the box. Some vendors use “25% of the remaining distance” instead | Filter SPADL passes on `start_x` / `end_x`. Name the definition on the site |
| Tackles | Ground duels to win the ball | SPADL `tackle`; Opta `tackle`; StatsBomb duel type Tackle | Count `type_name == tackle` |
| Interceptions | Reading a pass and taking the ball | SPADL `interception` | Count that type. socceraction marks an interception as failed if the same team does not keep the next action |
| Aerials | Aerial duels won and lost | Opta/WhoScored event `aerial`; StatsBomb duel type Aerial | **Not in SPADL.** The Opta and StatsBomb converters turn non-tackle duels into `non_action` and drop them. Count aerials on the raw event feed |
| Clearances | Ball put out of a dangerous area | SPADL `clearance` | Count that type |

Passing accuracy, progressive passes and PPDA only mean something if the pitch coordinates are consistent. [`PySport/kloppy`](https://github.com/PySport/kloppy) and socceraction both normalise provider coordinates. Do not compare a WhoScored progressive-pass count with a StatsBomb one without saying which definition you used.

## The stack that covers the whole list

Use these four together. Everything else is a specialised source, a model, or a video tagger.

1. **Collect events.** [`probberechts/soccerdata`](https://github.com/probberechts/soccerdata) (2.1k stars, pushed 9 Oct 2026, Apache-2.0) scrapes Club Elo, ESPN, FBref, Football-Data.co.uk, Sofascore, SoFIFA, Understat and WhoScored into pandas frames with shared column names. WhoScored `read_events()` can return raw Opta JSON, a flat event table, **SPADL**, or atomic-SPADL. That one call is the closest open path to shots, passes, tackles, interceptions and (on the raw feed) aerials.
2. **Normalise whatever feed you actually license.** [`PySport/kloppy`](https://github.com/PySport/kloppy) (562 stars, pushed 10 Oct 2026, BSD-3) loads event and tracking data into one model: StatsBomb (including 360 freeze frames), Wyscout v2/v3, Opta F7/F24/F73, Stats Perform MA1/MA3/MA25, Impect, Metrica, SkillCorner, Sportec, Tracab, Hawkeye, Signality, DataFactory, and partial Second Spectrum / PFF. Query patterns such as `shot.goal`, then export to pandas or polars.
3. **Tag and value on-ball actions.** [`ML-KULeuven/socceraction`](https://github.com/ML-KULeuven/socceraction) (818 stars, MIT, Python 3.9–3.12) is the SPADL implementation. Loaders cover StatsBomb, Opta, Wyscout, Stats Perform and WhoScored. SPADL action types are: `pass`, `cross`, `throw_in`, `freekick_crossed`, `freekick_short`, `corner_crossed`, `corner_short`, `take_on`, `foul`, `tackle`, `interception`, `shot`, `shot_penalty`, `shot_freekick`, `keeper_save`, `keeper_claim`, `keeper_punch`, `keeper_pick_up`, `clearance`, `bad_touch`, `dribble`, `goalkick`. Results include success, fail, offside, own goal, cards. Body parts include foot, head, left and right foot. It also ships Expected Threat (xT) and VAEP, which value every on-ball action, not only shots. The authors say the package is maintained for research reproducibility, not as a product roadmap.
4. **Join tracking to events when you have both.** [`Alek050/databallpy`](https://github.com/Alek050/databallpy) (105 stars, pushed 30 Sep 2026) synchronises tracking and events with Needleman–Wunsch, then computes team possession, individual player possession from tracking, a simple xG model, Karun Singh xT, pressure, and pitch-control models. Event providers include Opta, Stats Perform, Metrica, Instat, SciSports, Sportec, StatsBomb and FIFA. It can ingest any kloppy provider.

[`floodlight-sports/floodlight`](https://github.com/floodlight-sports/floodlight) (133 stars, pushed 4 May 2026) is the scientific-computing alternative to kloppy: Opta F24, StatsBomb, Stats Perform, Sportradar, Second Spectrum, SkillCorner, Tracab, DFL/Sportec, Kinexon, plus possession codes and physical models (metabolic power, Voronoi). Use it when the question is tracking physics. Use kloppy when the question is event stats.

## xG and the stats that sit next to it

| Repo | Stars | What it gives you | Limit |
| --- | --- | --- | --- |
| [hudl/open-data](https://github.com/hudl/open-data) | 3.7k | StatsBomb events, lineups, and 360 frames for selected competitions. Shots carry StatsBomb’s own xG. Events include Pass, Shot, Duel, Interception, Clearance, Block, Carry, Ball Recovery, Pressure, and a possession id | Selected competitions only. Read `LICENSE.pdf` before putting numbers on a public site. Attribute StatsBomb if you publish |
| [hudl/statsbombpy](https://github.com/hudl/statsbombpy) | 747 | Python client for the open-data repo and the StatsBomb API | Same licence as the data |
| [hudl/StatsBombR](https://github.com/hudl/StatsBombR) | 312 | Same, for R | Same |
| [ML-KULeuven/soccer_xg](https://github.com/ML-KULeuven/soccer_xg) | 261 | Train and apply xG on Opta, Wyscout and StatsBomb. Ships logistic and XGBoost pipelines for open play, plus separate penalty and free-kick models | Research package. Open-play models must be combined with the set-piece models or penalties and free kicks are wrong |
| [probberechts/soccerdata](https://github.com/probberechts/soccerdata) Understat module | (inside soccerdata) | Match xG, npxG, npxGD, **PPDA**, deep completions, expected points. Player xG, npxG, xGChain, xGBuildup, shots. Shot rows with x, y, body part, situation, result, assist | Big-five leagues, some cups and a few extra leagues. No passes, tackles or aerials |
| [amosbastian/understat](https://github.com/amosbastian/understat) | 186 | Async Python client for the same Understat pages | Shot and team xG, not a full event stream |
| [ewenme/understatr](https://github.com/ewenme/understatr) | 86 | R client for Understat | Last meaningful updates are older |
| [collinb9/understatAPI](https://github.com/collinb9/understatAPI) | 48 | Another Understat scraper | Use soccerdata or amosbastian first |
| [andrewRowlinson/expected-goals-thesis](https://github.com/andrewRowlinson/expected-goals-thesis) | 57 | Comparison of xG fits on StatsBomb and Wyscout | Reference, not a library |
| [andrewsimplebet/expected_goals_deep_dive](https://github.com/andrewsimplebet/expected_goals_deep_dive) | 36 | Calibration and cross-validation for soccer xG | Tutorial |
| [Dato-Futbol/xg-model](https://github.com/Dato-Futbol/xg-model) | 81 | Worked xG model in R on the public Wyscout events | One competition family, R |
| [martineastwood/penaltyblog](https://github.com/martineastwood/penaltyblog) | 233 | Understat and Club Elo scrapers, an xT module with a pretrained grid, StatsBomb and Opta streaming via MatchFlow, Dixon–Coles and other score models | xT and score models, not a player-stat warehouse |
| [ML-KULeuven/un-xPass](https://github.com/ML-KULeuven/un-xPass) | 63 | Pass selection, pass success and pass value on StatsBomb 360. This is the “how good was the pass that was *not* a shot” companion to xG | Needs 360 data. Creativity rating, not a pass-accuracy counter |
| [ImpectAPI/open-data](https://github.com/ImpectAPI/open-data) | 54 | Bundesliga 2023/24 events plus Impect KPIs (bypassed opponents, packing-style values) and player-match aggregates. Loads through kloppy | One season. Check their terms before republishing |
| [gkrhines/xThreatR](https://github.com/gkrhines/xThreatR) | 25 | Karun Singh xT in R, input is SPADL | Thin wrapper. socceraction and penaltyblog are the maintained versions |
| [withqwerty/nutmeg](https://github.com/withqwerty/nutmeg) | 52 | Agent toolkit whose metric cards name the published variants of xG, npxG, xA, PPDA, progressive passes, progressive carries, xT, VAEP and pass completion, and refuse to mix variants | A definition layer for analysts, not a database |

Karun Singh’s original xT write-up is a blog post, not a repo. The implementations to use are socceraction, penaltyblog’s `xt` module, and databallpy.

## Possession

Possession is three different numbers. A site should say which one it shows.

| Kind | Repo | How |
| --- | --- | --- |
| Provider possession chains | [hudl/statsbombpy](https://github.com/hudl/statsbombpy), [PySport/kloppy](https://github.com/PySport/kloppy) | StatsBomb stamps a possession id and possession team on each event. Duration is the gap between the first and last event in that chain |
| Team possession from events | [Alek050/databallpy](https://github.com/Alek050/databallpy) | `Team Possession` on synchronised event data |
| Player possession from tracking | [Alek050/databallpy](https://github.com/Alek050/databallpy) | Individual possession from tracking, following Vidal-Codina et al. 2022 |
| Possession codes on tracking feeds | [floodlight-sports/floodlight](https://github.com/floodlight-sports/floodlight) | Tracab/ChyronHego and DFL feeds include possession codes |
| Broadcast tracking, 10 matches | [SkillCorner/opendata](https://github.com/SkillCorner/opendata) (433 stars, MIT) | Tracking only. Derive possession from who is closest to the ball. [znstrider/Skillcorner_Opendata_Match_Analysis](https://github.com/znstrider/Skillcorner_Opendata_Match_Analysis) walks through it |
| Full-pitch sample tracking + events | [metrica-sports/sample-data](https://github.com/metrica-sports/sample-data) (503 stars) | Three anonymised matches. [Friends-of-Tracking-Data-FoTD/LaurieOnTracking](https://github.com/Friends-of-Tracking-Data-FoTD/LaurieOnTracking) (359 stars) is the standard notebook set. [metrica-sports/codeball](https://github.com/metrica-sports/codeball) (135 stars) queries events such as passes into the box and can write Metrica Play annotations. It is still aimed at Metrica Elite files |
| Possession from a broadcast video | [tryolabs/soccer-video-analytics](https://github.com/tryolabs/soccer-video-analytics) (309 stars) | YOLO ball and player tracking, then a possession counter and a pass counter. Demo quality, not Opta-accurate |
| Same idea, other codebases | [JanSkn/football-computer-vision](https://github.com/JanSkn/football-computer-vision), [Tony-Luna/soccer-video-analytics](https://github.com/Tony-Luna/soccer-video-analytics), [ialibanadeem/football-analysis-cv](https://github.com/ialibanadeem/football-analysis-cv) | Camera-compensated tracking and a possession estimate. Useful prototypes, not a stats feed |
| Possession without seeing the ball | [hyunsungkim-ds/pathcrf](https://github.com/hyunsungkim-ds/pathcrf) | KDD 2026. Infers events from player trajectories only |

WhoScored, Sofascore and FotMob also publish a ready-made possession percentage on the match page. That number is what most stat sites display. It is not the same as “share of passes”.

## Shots, passes, progressive passes

**Already tagged**

- WhoScored events through soccerdata, output format `events` or `spadl`. Passes keep start and end coordinates, so progressive passes are a filter. Accuracy is the success flag. Shot events are Opta’s miss, post, attempt saved and goal, which SPADL collapses to `shot` / `shot_penalty` / `shot_freekick`.
- StatsBomb open data through statsbombpy or kloppy. Pass outcome, pass length, body part, and shot xG are on the event. Progressive passes are still a filter you apply.
- Wyscout public events: [koenvo/wyscout-soccer-match-event-dataset](https://github.com/koenvo/wyscout-soccer-match-event-dataset) (102 stars) mirrors the Pappalardo seven-competition release (top five leagues, World Cup 2018, Euro 2016). [Friends-of-Tracking-Data-FoTD/mapping-match-events-in-Python](https://github.com/Friends-of-Tracking-Data-FoTD/mapping-match-events-in-Python) (138 stars) is Luca Pappalardo’s plotting code. socceraction converts this feed to SPADL.
- Impect open data, for packing and bypassed-opponent values on passes rather than a plain completion percentage.

**Pass models, once the events exist**

- [ML-KULeuven/un-xPass](https://github.com/ML-KULeuven/un-xPass): probability a pass is completed, and whether the chosen pass was the valuable one.
- socceraction xT and VAEP: a value for every pass, carry and defensive action.
- [sanjeevnara7/FootballPassPrediction](https://github.com/sanjeevnara7/FootballPassPrediction): pass-receiver prediction from tracking and a graph network. Research, not a collector.

**Passing networks** (counts of who passed to whom, which is the raw material for accuracy by pair)

- [Friends-of-Tracking-Data-FoTD/passing-networks-in-python](https://github.com/Friends-of-Tracking-Data-FoTD/passing-networks-in-python) (136 stars)
- [Dato-Futbol/passing-networks](https://github.com/Dato-Futbol/passing-networks) (51 stars), StatsBomb events and Metrica tracking
- [JoGall/passing-networks](https://github.com/JoGall/passing-networks) (6 stars) and the wider [JoGall/soccermatics](https://github.com/JoGall/soccermatics) (337 stars)

There is no widely used library whose job is only “progressive passes”. The good implementations are ten lines on top of SPADL or StatsBomb coordinates, and the site has to publish the rule (10 yards, into the box, or 25% of remaining distance).

## Aerials, tackles, interceptions

| Action | Count it from | Do not count it from |
| --- | --- | --- |
| Tackle | SPADL `tackle`; raw Opta `tackle`; StatsBomb duel type Tackle | A generic “duel won” column, which mixes ground and aerial |
| Interception | SPADL `interception`; raw Opta `interception`; StatsBomb Interception | Blocked passes, unless you want Opta’s habit of folding some blocked passes into interceptions (socceraction does this) |
| Aerial won / lost | Raw WhoScored/Opta `aerial`; StatsBomb duel type Aerial, outcome won or lost | SPADL. Both converters drop aerial duels. A `header` body part on a shot or pass is not an aerial duel |
| Clearance | SPADL `clearance` |  |
| Block | StatsBomb Block; Opta qualifiers on shots and passes | SPADL has no block type |
| Pressure / pressing action | StatsBomb Pressure events | PPDA. Pressures are a denser, different count |

WhoScored’s match centre is the public page that already shows aerials, tackles and interceptions as team and player totals, and the event stream behind it is what soccerdata downloads. A second, newer client is [Ali-Hasan-Khan/Scrape-Whoscored-Event-Data](https://github.com/Ali-Hasan-Khan/Scrape-Whoscored-Event-Data) (55 stars, pushed Aug 2026): one request per match, events as a dataframe, optional expected-possession-value column. Older Selenium scrapers ([RamisLao/scraper-whoscored](https://github.com/RamisLao/scraper-whoscored), [canggihpw/whoscoredscraper](https://github.com/canggihpw/whoscoredscraper), [deeppomal/whoscored_scraper](https://github.com/deeppomal/whoscored_scraper)) still exist and are brittle.

For a licensed Opta XML or JSON feed (F24, F7, F73, MA1, MA3), skip the scrapers and use kloppy or `socceraction.data.opta`.

## Scrapers and match-stat APIs

These return finished tables (possession, shots, pass counts, sometimes tackles) rather than a full event stream.

| Repo | Stars | Sources | Use it for |
| --- | --- | --- | --- |
| [probberechts/soccerdata](https://github.com/probberechts/soccerdata) | 2.1k | FBref, WhoScored, Understat, Sofascore, ESPN, Club Elo, Football-Data.co.uk, SoFIFA | The default scraper. FBref coverage in the current code is `standard`, `shooting`, `keeper`, `playing_time`, `misc`, plus match summary, lineups, and timeline events (goals, cards, substitutions). It does **not** pull a pass-by-pass FBref feed. The old FBref pages for progressive passes and pressures depended on StatsBomb and are not what this scraper reads now |
| [JaseZiv/worldfootballR](https://github.com/JaseZiv/worldfootballR) | 598 | FBref, Transfermarkt, Understat | **Archived.** The README says it will no longer be maintained. Keep it as a reference for the old FBref stat pages, not as a dependency |
| [manucabral/EasySoccerData](https://github.com/manucabral/EasySoccerData) | 50 | Sofascore live events, lineups, match statistics; Promiedos; FBref only on the git version | Live Sofascore stat lines (possession, shots, passes, duels and the rest of Sofascore’s match stats). soccerdata’s Sofascore module currently stops at leagues, tables and the schedule |
| [tunjayoff/sofascore_scraper](https://github.com/tunjayoff/sofascore_scraper) | 43 | Sofascore, 21 sports | Self-hosted store, CSV/parquet export, follow leagues and players. Heavier than EasySoccerData |
| [pseudo-r/Public-FotMob-API](https://github.com/pseudo-r/Public-FotMob-API) | 11 | FotMob’s website JSON | Match details include the stat groups FotMob shows (possession, shots, passes, tackles, interceptions, aerials, xG where FotMob has it). The repo’s own scope note says FotMob’s terms restrict automated collection, and the examples are documentation rather than a client you should run against the live site for a product |
| [maxencelobry/fotmob](https://github.com/maxencelobry/fotmob) | 11 | FotMob | Small JavaScript wrapper |
| [felipeall/transfermarkt-api](https://github.com/felipeall/transfermarkt-api) | 460 | Transfermarkt | Squads, values, injuries, transfers. Not xG or event stats, but the identity layer a stats site needs |
| [dcaribou/transfermarkt-scraper](https://github.com/dcaribou/transfermarkt-scraper) | 177 | Transfermarkt | Scraper rather than an API service |
| [withqwerty/reep](https://github.com/withqwerty/reep) | 236 | Crosswalk | Maps player, team and coach ids across Transfermarkt, FBref, UEFA, Sofascore and 25 other providers. Use this when joining WhoScored events to Understat xG to Transfermarkt names |
| [Torvaney/statsbombapi](https://github.com/Torvaney/statsbombapi) | 56 | StatsBomb | Pipeline-oriented client. statsbombpy is the usual choice |
| [parth1902/Scrape-FBref-data](https://github.com/parth1902/Scrape-FBref-data) | 141 | FBref | Older notebook from when FBref still exposed the StatsBomb advanced tables. Do not build on it |

Club Elo (team strength, not event stats) is inside soccerdata and penaltyblog. [Torvaney/regista](https://github.com/Torvaney/regista) (94 stars) and [Torvaney/mezzala](https://github.com/Torvaney/mezzala) are for team-strength models once you have goals or xG, not for collecting the event stats themselves.

## Open datasets worth loading before you scrape anything

| Repo | What is in the files |
| --- | --- |
| [hudl/open-data](https://github.com/hudl/open-data) | The only large free event stream with native xG, possession ids, pressures, tackles, interceptions and aerial duels |
| [koenvo/wyscout-soccer-match-event-dataset](https://github.com/koenvo/wyscout-soccer-match-event-dataset) | Public Wyscout events for seven competitions. Passes, shots, duels, with coordinates |
| [ImpectAPI/open-data](https://github.com/ImpectAPI/open-data) | Bundesliga 2023/24, event KPIs included |
| [metrica-sports/sample-data](https://github.com/metrica-sports/sample-data) | Tracking and events, three matches, for possession and sync work |
| [SkillCorner/opendata](https://github.com/SkillCorner/opendata) | Ten matches of broadcast tracking |
| [spoho-datascience/idsse-data](https://github.com/spoho-datascience/idsse-data) | Synchronised tracking and events. Also loadable from floodlight and databallpy as the Sportec/DFL open games (CC BY 4.0; seven Bundesliga matches, see the Nature data descriptor linked from databallpy) |

## Tagging the actions from video

Use this only if you do not have an event feed. Broadcast spotting will not reproduce Opta aerial-duel counts.

| Repo | Stars | Classes it can tag |
| --- | --- | --- |
| [SoccerNet/sn-spotting](https://github.com/SoccerNet/sn-spotting) | 105 | Action spotting on 500 games (17 sparse classes: goals, cards, substitutions, and similar). The 2024 ball-action set is 7 games and **12 dense classes: Pass, Drive, Header, High Pass, Out, Cross, Throw In, Shot, Ball Player Block, Player Successful Tackle, Free Kick, Goal** |
| [lRomul/ball-action-spotting](https://github.com/lRomul/ball-action-spotting) | 139 | First place, SoccerNet ball-action spotting 2023. Passes and drives |
| [recokick/ball-action-spotting](https://github.com/recokick/ball-action-spotting) | 30 | That solution adapted to the 12-class 2024 label set |
| [SoccerNet/SoccerNet-v3](https://github.com/SoccerNet/SoccerNet-v3) | 80 | Frame-level annotations, including players and the ball, for spotting work |
| [SoccerNet/sn-tracking](https://github.com/SoccerNet/sn-tracking) | 112 | Player tracking benchmark |
| [SoccerNet/sn-gamestate](https://github.com/SoccerNet/sn-gamestate) | 464 | End-to-end tracking and identification onto a minimap. A base for possession-from-video, not a stat counter |
| [OpenSportsLab/opensportslib](https://github.com/OpenSportsLab/opensportslib) | 21 | Action recognition and spotting toolkit |
| [DonsetPG/narya](https://github.com/DonsetPG/narya) | 179 | Track players from a camera and value them with an expected-discounted-goal agent |
| [tryolabs/soccer-video-analytics](https://github.com/tryolabs/soccer-video-analytics) | 309 | Possession and a pass count from one video |

Header in SoccerNet is a spotted action. It is not “aerial duels won”. Successful tackle is one class, with no lost tackles and no interceptions.

## Plotting and catalogues

These do not collect the stats, but they are how you check that a collector is right.

- [andrewRowlinson/mplsoccer](https://github.com/andrewRowlinson/mplsoccer) (549 stars): pitch plots, shot maps, pass maps, and StatsBomb loaders.
- [Torvaney/ggsoccer](https://github.com/Torvaney/ggsoccer) (206 stars): Opta-style pitches in ggplot2.
- [probberechts/d3-soccer](https://github.com/probberechts/d3-soccer) (78 stars): event-stream visuals in D3.
- [Friends-of-Tracking-Data-FoTD/SoccermaticsForPython](https://github.com/Friends-of-Tracking-Data-FoTD/SoccermaticsForPython) (427 stars): the usual first notebooks on Wyscout and tracking.
- [eddwebster/football_analytics](https://github.com/eddwebster/football_analytics) (2.8k stars): a large personal catalogue of projects and public data links. Browse it; do not vendor it.
- [matiasmascioto/awesome-soccer-analytics](https://github.com/matiasmascioto/awesome-soccer-analytics) (633 stars): community list, last real curation around 2020, so treat links as historical.
- [diegopastor/awesome-football-analytics](https://github.com/diegopastor/awesome-football-analytics) (218 stars): a second curated list.

Sync tools, if event times and tracking frames disagree: [ML-KULeuven/ETSY](https://github.com/ML-KULeuven/ETSY), [huffyhenry/sync.soccer](https://github.com/huffyhenry/sync.soccer), [hyunsungkim-ds/elastic](https://github.com/hyunsungkim-ds/elastic), and databallpy’s synchroniser.

## What not to build the site on

- **SPADL alone for aerials.** They are deleted in the conversion. Keep the raw Opta or StatsBomb duel next to the SPADL table.
- **FBref, via current scrapers, for progressive passes and PPDA.** soccerdata’s FBref reader no longer requests those tables, and worldfootballR is archived.
- **Understat for tackles, passes or aerials.** It is a shot and pressing source.
- **SoccerNet’s 17-class action spotting for a stat site.** Those classes are goals, cards and set pieces, not a pass log. The 12-class ball-action set is the relevant one, and it is seven games.
- **A public EnjoyStats feed scraped from WhoScored, Sofascore, FotMob or FBref.** Those sites’ terms restrict automated collection, the HTML breaks, and republishing their figures is a separate rights question. The same caution applies to StatsBomb open data: it is published for research and genuine analytical interest, with an attribution requirement, and `LICENSE.pdf` is the document that decides whether a public website is allowed.
- **Mixing providers in one column.** Understat PPDA, a SPADL PPDA you compute yourself, and a StatsBomb pressure count are three different numbers. Nutmeg’s metric cards are a good checklist for keeping them apart.

## A practical order for EnjoyStats

1. Decide the definition row first: StatsBomb-style xG, Understat PPDA, time-based possession, FBref’s 10-yard progressive pass, Opta aerials. Write those definitions on the stat page.
2. For a prototype on free data, load [hudl/open-data](https://github.com/hudl/open-data) with statsbombpy or kloppy, convert to SPADL with socceraction, and compute shots, pass accuracy, progressive passes, tackles, interceptions, clearances, possession chains and your own PPDA. Count aerials from the raw StatsBomb duel type before the SPADL conversion. Add Understat through soccerdata where you want a published xG and PPDA to compare against.
3. For coverage beyond the open competitions, the durable input is a licensed Opta, StatsBomb, Wyscout or Impect feed, read with kloppy or socceraction. [withqwerty/reep](https://github.com/withqwerty/reep) is the identity map when those feeds do not share player ids.
4. Use video spotting only for competitions nobody sells an event feed for, and label those numbers as model output.
