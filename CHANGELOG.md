# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

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
