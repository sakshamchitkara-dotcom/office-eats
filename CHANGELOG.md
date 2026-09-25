# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [0.4.0] - 2026-09-25

### Added
- `office-eats poll invite POLL NAME... [--base-url]`: signed personal voting links. After the first invite the web page only accepts votes carrying a valid token, under the name the token was made for. CLI and Slack votes are unaffected. Existing databases gain the column automatically.
- `rotate --ics FILE`: a calendar invite (RFC 5545, folded and escaped) for the week's pick at the `--at` time, in UTC when the office time zone is known.
- `--wheelchair` on `recommend`, `batch` and `poll create`: keep only venues tagged `wheelchair=yes|designated` in OSM. Markdown reports show the tag.
- Real v0.4 outputs in `examples/live/v0.4/`.

## [0.3.0] - 2026-09-25

### Added
- `office-eats team member TEAM NAME --diet ...` (and `--remove`): per-person dietary needs, listed by `team show`.
- `rotate` uses members' diets as coverage, not a hard filter. Places with an option for everyone come first, then those covering the most people, and the pick names anyone left without a tagged option. A vegan + halal + kosher team now gets a pick instead of "no places match".
- `office-eats feedback TEAM NAME up|down [--week]`: rate a rotation pick. Each net vote moves that place's score by 5 points in later rotations, capped at ±20.
- A web voting page for teams without Slack. `GET /poll/<id>` shows the poll and `POST /poll/<id>` records a vote from a plain HTML form (no JavaScript, strict CSP, cross-site posts refused).
- `serve --web-only`: run only the voting pages, with no Slack signing secret.
- CI on Python 3.14.
- Real v0.3 outputs in `examples/live/v0.3/`.

### Fixed
- `opening_hours` values with a date rule such as `Mo-Su 11:00-22:00; Dec 25 off` no longer mark the venue closed every day.
- A malformed `--at` or `at:` (such as `fri 7pm`) now gets an error that shows the accepted forms, not an `int()` traceback message.
- `/eats` validates `party`, `n` and `walk`. `n:0` no longer returns an empty list, and `party:-2` or `walk:nan` are rejected.
- A bad `diet` or `party` in one batch CSV row no longer stops the whole batch. That row fails and the others still run.
- `~` in `OFFICE_EATS_DB` and `OFFICE_EATS_CACHE` is expanded, where it used to create a literal `~` directory.
- The web voting page sends `Referrer-Policy: same-origin`. With `no-referrer`, browsers sent `Origin: null`, so every browser vote was refused.

## [0.2.0] - 2026-09-25

### Added
- `--routing osrm|ors`: walking times from the FOSSGIS OSRM foot server (no key) or the OpenRouteService matrix API (`ORS_API_KEY`). Results are cached for 30 days, and any failure falls back to straight-line × 1.3. Reports state which source was used.
- Office time zone lookup from coordinates: `--tz`, then the optional `timezonefinder` package (`[tz]` extra), then OSM boundary `timezone` tags. `--at` (including `now`) is evaluated on the office's clock.
- Price provenance (`price_source`: provider, tag, brand, keyword, guess). Guessed prices are shown as `~$$`, and template blurbs hedge them.
- A brand table for well-known chains, and a name-keyword table that fixes misleading OSM tags (for example, a caviar bar tagged `cafe`).
- `office-eats poll create|vote|tally|close`: team polls stored in SQLite (`OFFICE_EATS_DB`), rendered as text or a Slack Block Kit message with vote buttons.
- `POST /slack/interact` on `serve`: signature-checked vote-button clicks, with the poll redrawn in place.
- `office-eats team set|show|list` for saved team profiles (office, diets, party size, time zone).
- `office-eats rotate TEAM`: a weekly lunch pick that avoids places picked in recent weeks and respects the team's diets. Includes `--reroll`, `--history` and `--slack`.
- `-f map`: a self-contained Leaflet HTML map with OSM tiles and attribution.
- `/eats` accepts `route:` and `tz:` options.
- Real v0.2 outputs in `examples/live/v0.2/`.

### Fixed
- An unknown diet in `/eats`, a batch CSV row or a team profile now returns an error message instead of crashing (`/eats` previously dropped the connection).
- A `price_range` tag without `$` signs no longer maps to `$`.

### Changed
- `parse_when` moved from `cli` to `tz`.

## [0.1.0] - 2026-09-25

First release: geocoding (Nominatim), venues (Overpass, plus optional Google, Yelp and Foursquare), enrichment and use-case scoring, Claude or template blurbs, table/Markdown/HTML/JSON/Slack output, batch CSV, the Slack slash-command server, and a polite HTTP client with caching and backoff.
