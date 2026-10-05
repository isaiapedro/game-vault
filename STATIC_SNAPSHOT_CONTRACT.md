# Static Game Vault snapshot contract

## Immutable runtime data

The normal Game Vault release reads exactly one private JSON snapshot. It contains the complete
defined game list and the already-reviewed collection, queue, wishlist, PSN summary, trophy,
metadata, estimate, and statistics projections needed by the UI. The runtime never opens
PostgreSQL and never contacts PSN, IGDB, HowLongToBeat, PSNProfiles, or remote image hosts.
Wishlist projections include two explicit price slots per game: one reviewed Mercado Livre
disc listing (new or used), and one manually observed PS3 console-store digital price. Missing, stale, or
unavailable observations project as empty slots; retailer lookups never occur at runtime.

The snapshot has a format version, UTC capture time, latest PSN observation time, and a SHA-256
checksum over its canonical content. Startup validates the version, required projections,
referential integrity, unique game IDs, and checksum before serving collection data.

## Release preparation

PostgreSQL and provider clients are authoring tools, not runtime services. After deliberately
reviewing or refreshing the source database, run:

```sh
venv/bin/python -m scripts.export_static_snapshot --download-covers
```

The export reads cached database facts and writes `.local/game-vault-snapshot.json` atomically.
It also reads reviewed price observations from private `.local/price-observations.json` when
present. Snapshot format version 3 validates Mercado Livre and PS3 Store price slots. The reader accepts older
versions 1 and 2 for continuity; version 2 disc slots display as one offer. Version 1 has only explicit missing-price display until
a deliberate replacement export and restart. The price-only preparation command
`python -m scripts.refresh_price_snapshot` can update these slots from reviewed private
observations without opening PostgreSQL; it writes atomically and still requires a restart.
It does not perform PSN, IGDB, or HLTB synchronization. `--download-covers` performs the optional
one-time cover download; later data-only exports retain cached covers. After confirmed-release
image choices are saved, `--download-artwork` caches up to two landscape images per game locally.
Failed or invalid images become the built-in fallback. Any desired
provider refresh must be invoked and reviewed separately before this command.

## Privacy and publication

The snapshot, locally cached covers and artwork, environment file, database dumps, screenshots, provider IDs,
and collection-derived records are private runtime artifacts under `.local/`. They are ignored by
source control, excluded from the container build context, mounted read-only, and must not be
committed or published with application implementation.

## Replacement semantics

A new export replaces the whole snapshot atomically. There is no browser mutation, scheduled
refresh, background sync, or partial in-place update. Restart the container after replacement so
one process lifetime always observes one internally consistent dataset.
