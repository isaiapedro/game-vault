# Game Vault

A local, PlayStation-first view of one defined game collection. The released application is a
single read-only FastAPI process serving the Angular UI, JSON endpoints, fixed private data, and
locally cached cover art. It does not need PostgreSQL, provider credentials, or Node at runtime.

## Run the fixed release

The private snapshot must exist at `.local/game-vault-snapshot.json`. Then run:

```sh
docker compose up --build -d --wait
```

Open `http://127.0.0.1:4200`. The container restarts unless stopped and binds to loopback by
default. The snapshot, covers, and artwork are mounted read-only; they are not baked
into the image.

For an explicitly authorized, trusted same-Wi-Fi session, identify this computer's Wi-Fi IPv4
address with `ip -4 addr show`, then start with that exact private address:

```sh
GAME_VAULT_BIND_HOST=192.168.1.16 docker compose up --build -d --wait
```

Open `http://192.168.1.16:4200` on the phone. This address may change when Wi-Fi reconnects;
substitute the current Wi-Fi IPv4. The server refuses wildcard and public addresses. LAN mode
has **no login**: anyone on the same reachable network can read the fixed game collection. Use
only a trusted network, avoid router port forwarding, and return to loopback when finished:

```sh
docker compose down
docker compose up -d --wait
```

Host firewall rules and Wi-Fi client isolation can still block the phone. The browser and API
use the same origin, so no remote provider or separate API address is needed.

For local runtime development after building the frontend:

```sh
cd src/frontend && npm ci && npm run build && cd ../..
venv/bin/uvicorn src.api.static_main:app --host 127.0.0.1 --port 4200 --reload
```

## Fixed data model

The interface focuses on choosing a game and celebrating trophy progress. Game cards fill in
proportion to saved progress; earned platinums get a distinct multicolor treatment across pages.
Cards and details use reviewed, readable display titles and release years while retaining the
original PSN title for identity and search. Gameplay tags normalize IGDB's longer genre names
and prioritize local editorial specificity without changing the provider's raw metadata.
The queue includes genre filters and varied picks from available unfinished games. Genre tags
are local editorial categories where provider metadata is missing. Game details open to About,
with Trophies one tab away. The interface uses 15px regular and 25px display typography on all
screens. The wishlist shows current manually reviewed Brazilian offers when available, with
one Mercado Livre disc offer (new or used) separate from manually observed PS3 console-store prices. Missing or stale
prices remain explicit. There is no live retailer lookup or buying recommendation.

The release contains the exact exported game list, ownership and play state, queue order, wishlist,
PSN account summaries, cached detailed trophies, time estimates, and statistics. The browser can
filter and inspect that information but cannot add, remove, reorder, enrich, synchronize, or edit
it. All remote cover URLs are either downloaded during preparation and rewritten to same-origin
paths, or replaced by the built-in typographic fallback.

The snapshot is validated at startup for format version, unique IDs, internal references, required
projections, and SHA-256 checksum. One running process therefore observes one internally consistent
dataset until an operator deliberately replaces it and restarts the service.

## Prepare a replacement snapshot

The older PostgreSQL-backed API and provider clients are retained only as authoring tools. Configure
`config/.env`, migrate the private database, perform any desired provider refreshes deliberately,
review their matches, and then export the already-cached state:

```sh
venv/bin/python -m scripts.migrate --check
venv/bin/python -m scripts.export_static_snapshot --download-covers
docker compose restart app
```

The export itself does not synchronize PSN, IGDB, or HowLongToBeat. That separation prevents a
normal start, rebuild, or snapshot export from silently changing the collection. Detailed trophy
sets not already cached remain absent rather than being fetched implicitly.

### Review wishlist prices

Reviewed offer observations and their history stay in `.local/price-observations.json`. Use
`python -m scripts.prepare_prices --help` for the manual authoring command. Provide one private
JSON observation file with its wishlist `game_id`, exact listing title and edition, PS3 platform,
source and listing ID, Brazil region, BRL item price, shipping price or `null`, availability,
UTC observation time, and `review_status: "confirmed"`. For example:

```sh
venv/bin/python -m scripts.prepare_prices add --input .local/reviewed-offer.json \
  --confirm-title 'Exact listing title' --confirm-platform PS3
```

Confirm the exact release, listing URL, edition, condition, and current price before saving an
observation. Physical offers require a Mercado Livre listing URL; new and used discs compete in one
slot, with condition shown in its details. A manually observed PS3 console-store price may have no
web URL.
The export reads that private file and includes only current reviewed observations; a missing
file produces an explicit unavailable state for every wishlist game. PS3 Store prices require
manual observation in the console store. Publish price changes without PostgreSQL with:

```sh
venv/bin/python -m scripts.refresh_price_snapshot
docker compose restart app
```

The full database exporter also includes reviewed prices. No retailer or PSN request occurs
during browsing or snapshot preparation.

Mercado Livre discovery requires a privately configured developer access token. Search an
individual public game title with `MERCADO_LIVRE_ACCESS_TOKEN` in the local environment:

```sh
venv/bin/python -m scripts.discover_mercado_livre --title 'Public game title'
```

This creates `.local/mercado-livre-candidates.json` for review; it does not publish an offer.
Confirm the exact PS3 release, edition, seller, listing price, and availability before using
the manual authoring command. No postcode is sent; shipping stays unknown unless an estimate
for the intended destination is separately confirmed.

All collection-derived outputs are private: `config/.env`, `.local/game-vault-snapshot.json`, cached
covers, database dumps, and verification screenshots are ignored and must not be committed or
published.

### One-time coverage preparation

Generate a private, one-row-per-game report without provider calls or database changes:

```sh
venv/bin/python -m scripts.prepare_coverage
```

This writes `.local/coverage-report.json`. Explicit preparation commands are:

```sh
venv/bin/python -m scripts.prepare_coverage --search-igdb
venv/bin/python -m scripts.prepare_coverage --refresh-igdb-scores
venv/bin/python -m scripts.prepare_coverage --refresh-igdb-artwork
venv/bin/python -m scripts.prepare_coverage --fetch-psn-details --psn-limit 10
venv/bin/python -m scripts.prepare_coverage --refresh-hltb
venv/bin/python -m scripts.prepare_coverage --make-hltb-review
venv/bin/python -m scripts.prepare_coverage --make-guide-review
```

IGDB search needs `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in `config/.env`. It searches
the PSN display title and preserved catalog title, keeps same-platform candidates, and writes
`.local/igdb-review.json`. Inspect editions and alternate names, put the chosen candidate ID in
`selected_igdb_id`, then run `--apply-igdb-review`. Unselected entries stay untouched.
For explicit choices already checked against candidates, `--select-reviewed-igdb-ids game_id:igdb_id,...`
records the selections without applying them; the subsequent apply
skips provider identities already saved in the database.
After reviewing IDs, `--curate-display-titles` saves readable labels from the confirmed IGDB
titles without modifying PSN names or trophy identities.
`--refresh-igdb-scores` reads IGDB user `rating` and `rating_count` by confirmed ID, backs up the
local database, and caches available scores for the next static export. No rating is fabricated
when IGDB has none.
`--refresh-igdb-artwork` records at most two landscape images for each confirmed ID. Run
`venv/bin/python -m scripts.export_static_snapshot --download-artwork` to cache them locally;
subsequent snapshot exports retain cached covers and artwork without contacting image hosts.
Use `--download-covers` once to prefer the confirmed IGDB portrait covers over older wide title
icons; later exports reuse the cached portraits.

PSN detail fetching uses the existing `PSN_NPSSO`. It fetches only confirmed releases without
a cached detailed set and never converts summary counts to trophy rows. HLTB refresh needs no
key; only unique exact title results are applied. Historical-title matches
and ambiguous results are kept as review outcomes in the local authoring job record. The
`--make-hltb-review` command writes `.local/hltb-review.json`; inspect candidates, set
`selected_source_id` for confirmed releases, and use `--apply-hltb-review` to apply them.

The optional guide template accepts `selected_guide_url` for reviewed PSNProfiles or PlayStationTrophies guide
pages; apply with `--apply-guide-review`. The UI shows only an external reference link, not
scraped guide text or inferred earned trophies. No guide key is required.

Each applying/fetching command first saves a private logical JSONL ZIP of the authoring database
under `.local/`. It does not replace a PostgreSQL schema dump; keep the existing migration files
for schema recovery.

After reviewing the authoring data, export a new snapshot, run verification, and restart the
container. Rerun the report after export to see updated coverage. Reports and review files are
private `.local/` artifacts.

## Data semantics

Completionist remains the single goal. Approximate time remaining is the HLTB completionist estimate
multiplied by the unearned trophy percentage. Trophy effort is not linear, so this is a planning
approximation. Missing progress or estimates remain unknown. Summary trophy counts are not presented
as detailed trophy rows, and provider observation dates remain visible as capture provenance.

## Verification

```sh
venv/bin/python -m unittest tests.test_static_snapshot -v
venv/bin/python tests/visual_progress_browser.py
cd src/frontend && npm run build
docker compose config --quiet
```

The PostgreSQL-backed authoring suite remains available when intentionally changing the source
dataset:

```sh
venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

See [static snapshot contract](STATIC_SNAPSHOT_CONTRACT.md), [API contract](API_CONTRACT.md), and
[architecture decisions](DECISIONS.md).

## Workspace boundary

This directory is locally maintained under PIOS. Registry currently resolves it to the workspace
root, whose content policy excludes application source. Do not commit or push application
implementation to that root. A dedicated registered application repository is required before
publication; governance contracts, credentials, snapshots, provider data, cached covers, and
collection screenshots must remain outside published application contents.
