# Game data coverage plan

This is a release-preparation plan. The static app remains read-only and never calls providers.
Collection-specific inventories, provider IDs, and results belong in the ignored `.local/` directory.

## 1. Inventory every defined game

Generate a private, one-row-per-game coverage report from the authoring database or static
snapshot. Record platform, ownership/backlog/wishlist state, canonical display title, historical
catalog title, confirmed PSN identity, confirmed metadata identity, cover, genre, developer,
publisher, release date, description, time estimate, trophy summary, trophy list, and observation
timestamp. Mark each field as `confirmed`, `missing`, `not_applicable`, or `needs_review`, with
provider and source ID. Keep missing fields visible rather than substituting guesses.

## 2. Resolve titles and release identities

Search with the current title and preserved catalog title. For metadata, also inspect provider
alternative names, platform and edition/version relationships. Normalize punctuation and display
marks for search, but never collapse sequel numbers, remasters, HD collections, regional editions,
or platform releases into one identity. Automatically accept only an exact, unambiguous title match
under the applicable provider policy. Put every other candidate in a review queue showing both
titles, platform, edition, provider ID, and source. Persist a confirmed ID and provenance before
using its metadata. Once confirmed, use the ID for refreshes rather than fuzzy title search.

## 3. Complete characteristics and artwork

For each confirmed release, fill cover, genre, developer, publisher, release date, and a short
description. Use the existing IGDB authoring integration when credentials are configured. Reuse
already cached PlayStation artwork for confirmed PSN releases. Record source and retrieval date,
review regional/platform discrepancies, and use the built-in cover fallback until an image is
licensed and cached locally. Do not hotlink images from the static app.

## 4. Complete trophy coverage

Use PSN as the authority for account ownership, earned state, trophy IDs, grades, names, and
descriptions. Fetch missing trophy lists once for confirmed PSN mappings before export. For
wishlist or otherwise unavailable PSN titles, evaluate a public trophy-guide/catalog source for
general trophy count, missables, online requirements, difficulty and guide notes. These are
third-party *reference* facts, not earned-state facts. Check access terms and reuse rights before
automating retrieval or caching text/images; prefer short attributed summaries and source links.
Never infer that a trophy was earned from a guide. Keep unmatched games explicitly `unknown`.

## 5. Time estimates and price-ready wishlist

Continue treating HowLongToBeat as optional, low-priority context. The original catalog title is
now a fallback search term; alias-only matches and multiple matches require review before an
estimate is stored. Never turn completionist hours into a platinum-time claim.

Keep wishlist games in the same coverage report, with ownership status and release identity.
Reserve fields for Brazilian storefront, currency, current price, historical low, observed date,
and product/edition ID, but do not show a buy recommendation until a separately approved price
source and comparison policy exist. Distinguish base game, deluxe edition, and DLC pricing.

## 6. Release gate

Review the private report until every defined game has either required characteristics and
appropriate trophy coverage or an explicit `missing`/`needs_review` reason. Verify no provider
identity conflicts, no cross-platform trophy merges, and no unattributed third-party content.
Then export the snapshot, run tests, restart the static container, and verify that runtime network
requests stay local. Repeat this preparation workflow only when deliberately updating the fixed
collection.
