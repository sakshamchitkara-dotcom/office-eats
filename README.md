# office-eats

Finds good places to eat near an office and ranks them for the job at hand: a **quick team lunch**, a **client dinner**, **office catering**, or a **coffee meeting**. Give it an address, a company name, `lat,lon`, or a CSV of offices. You get back a terminal table, Markdown, HTML, JSON, or a Slack message, and every venue links to OpenStreetMap.

```
$ office-eats recommend "345 Park Ave, San Jose, CA 95110" --name "Adobe HQ" -u lunch --party 8 --at "2026-09-29 12:15"
Quick team lunch near Adobe HQ
345, Park Avenue, Buena Vista, San Jose, Santa Clara County, California, 95110, United States  (100 candidates)

#  Score  Name                     Kind        Cuisine                 Walk  $   Diet                    Open
-  -----  -----------------------  ----------  ----------------------  ----  --  ----------------------  ----
1  72     Grace Deli & Cafe        fast_food   sandwich                5m    $   -                       ?
2  71     iJAVA Cafe               cafe        coffee_shop, breakfast  6m    $   halal/vegan/vegetarian  yes
3  70     El Jalapeño Rojo         restaurant  mexican                 4m    $$  -                       ?
...
```

That output came from a live run against Nominatim and Overpass on 2026-09-25. More real outputs are in [`examples/live/`](examples/live).

## Data sources and ethics

- **Geocoding: [Nominatim](https://operations.osmfoundation.org/policies/nominatim/).** The tool makes at most 1 request per second, sends an identifying `User-Agent`, and caches results for 30 days.
- **Venues: [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API).** It queries `amenity=restaurant|cafe|fast_food|food_court|pub` and reads `cuisine`, `diet:*`, `opening_hours`, `website`, `capacity`, `takeaway`, `delivery` and `reservation`. Requests are spaced 2 s apart, results are cached for 7 days, and the client backs off on 429/5xx (honouring `Retry-After`).
- **Optional official APIs:** Google Places API (New), Yelp Fusion and Foursquare Places. They sit behind the same provider interface and are used only when you pass `--provider` and set the matching key. **Nothing is scraped** from Yelp, Google Maps or similar sites.
- **Restaurant websites (`--menus`):** reads only the venue's own homepage to find a menu link, and only when `robots.txt` allows it. It follows RFC 9309: a 4xx for robots.txt means allowed, while a 5xx or an unreachable server means disallowed.
- All reports carry the "© OpenStreetMap contributors, ODbL" attribution.

Set `OFFICE_EATS_USER_AGENT` to identify yourself (see `.env.example`).

## Install

```bash
pip install -e ".[llm,dev]"      # the llm extra (anthropic SDK) is optional
cp .env.example .env              # then export the values you need
```

Requires Python 3.10+. The core has no third-party dependencies.

## Usage

```bash
# Client dinner Thursday 7pm for 4. Drops places closed (or closing mid-meal) and looks for menu links.
office-eats recommend "345 Park Ave, San Jose, CA 95110" --name "Adobe HQ" \
  -u dinner --party 4 --at "thu 19:00" --open-only --menus -f md -o dinner.md

# Coffee near a company, found by name
office-eats recommend "Salesforce Tower, San Francisco" -u coffee --at now

# Vegan catering as JSON; halal + gluten-free lunch within a 10-minute walk
office-eats recommend "37.3295,-121.8948" -u catering --diet vegan -f json
office-eats recommend "37.3295,-121.8948" --diet halal,gluten-free --max-walk 10

# Every office in a CSV (name + address or lat/lon; optional use_case, diet, party columns)
office-eats batch examples/offices.csv -f html --out-dir out/

# Post to Slack via an incoming webhook, or print the Block Kit payload
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... office-eats recommend "..." --slack
office-eats recommend "..." -f slack
```

Formats: `table` (default), `md`, `html`, `json`, `slack`. The `--at` option takes `now`, an ISO datetime, or `<day> HH:MM` (the next occurrence), in the office's local time.

### Use cases and scoring

Each venue gets a score from 0 to 100. The score is a weighted mix of the parts below, and the weights change with the use case (see `scoring.py`):

| Part | What it measures |
|---|---|
| distance | Exponential decay on walking time. The decay is steep for coffee and lunch and gentle for catering. |
| kind | How well the venue type fits: cafés suit coffee, restaurants suit dinner, and so on. |
| price | Distance from the target price: $ for lunch and coffee, $$$ for client dinners. |
| group | Estimated seats compared with the party size. |
| open | Whether the venue stays open for the whole visit: lunch 45 min, dinner 90, coffee 30. |
| quality | Whether the OSM entry has hours, a website and a cuisine, plus the provider rating when one exists. |
| catering | Whether the venue has `catering`, `delivery` or `takeaway` tags (catering use case only). |

Dietary constraints (`vegan`, `vegetarian`, `halal`, `kosher`, `gluten_free`) are a **hard filter**. They come from OSM `diet:*` tags and from cuisines that imply them (for example `vegan` or `falafel`). `--open-only` drops venues known to be closed and keeps the ones whose hours are unknown.

### Claude blurbs (optional)

When `ANTHROPIC_API_KEY` is set, or with `--llm on`, the tool sends the top ~2×N candidates as structured JSON to `claude-opus-5-5`. Claude picks the shortlist and writes a one-sentence "why go here" for each pick. The request uses a JSON-schema output format and `effort: low`, and the system prompt tells the model that venue data is crowd-sourced and must be treated as data, not instructions. The tool then checks that every returned id was in the candidate set. If anything fails (missing SDK, auth, network, refusal, bad output), it prints the reason to stderr and falls back to the deterministic ranker and template blurbs. `--llm off` forces the deterministic path.

### Slack slash command

```bash
SLACK_SIGNING_SECRET=... office-eats serve --host 0.0.0.0 --port 8080
# Slack app -> Slash command /eats -> Request URL https://<your-host>/slack/command
/eats dinner party:6 diet:vegan at:fri_19:00 415 Mission St, San Francisco
```

The server:

- verifies Slack's `v0` HMAC signature and rejects timestamps more than 5 minutes old;
- acknowledges within Slack's 3-second limit, then posts the result to `response_url`;
- refuses to start without a signing secret unless you pass `--insecure`, which is for local testing only.

### Caching

Responses are cached in SQLite at `~/.cache/office-eats/cache.sqlite3` (override with `OFFICE_EATS_CACHE`). Use `--no-cache` to skip the cache for one run and `office-eats clear-cache` to wipe it. API keys are never part of cache keys.

## Development

```bash
pytest -q          # fully offline: recorded Nominatim/Overpass fixtures + fakes
ruff check src tests
```

The Nominatim and Overpass fixtures in `tests/fixtures/` were recorded from real responses for Adobe HQ in San Jose. The Google, Yelp and Foursquare fixtures are **hand-written** from each API's documented response shape because no keys were available.

## Limitations

- OSM has no prices. Price level comes from cuisine and venue kind, so a caviar bar tagged `cafe` reads as `$`. Provider prices, when available, always override the heuristic.
- Group size is a heuristic. It uses `capacity` when that tag is mapped, and otherwise guesses from the venue kind, `reservation`, building footprint and outdoor seating.
- Walking time is straight-line distance × 1.3 at 80 m/min, not routed.
- `opening_hours` support covers weekday rules, overnight spans, `off` and `24/7`. Public-holiday, month and sunrise rules are ignored, and a venue with unparseable hours is treated as unknown rather than guessed.
- Times are interpreted as the office's local time, and no time-zone conversion is done.

## License

MIT. Map data © OpenStreetMap contributors, ODbL 1.0.
