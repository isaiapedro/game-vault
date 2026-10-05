# Brazilian wishlist price search — implementation plan

Status: manual baseline and token-gated Mercado Livre candidate discovery implemented;
historical buying signal pending. No source request has run without a configured token.
No reviewed offer observations have been added by this implementation.

## Goal and current constraint

Help choose when and where to buy a wishlist game without turning Game Vault into a live shopping service. The current private snapshot has 24 wishlist entries, all for PS3. Keep price data secondary to the game's identity and trophy information, and never invent an offer, discount, or savings claim.

PS3 is a special case: Sony says PS3 content has not been purchasable through its web/mobile store since 2020; purchases have instead been available on the console. Sony also says the PS3 Store in Brazil will close in July 2027. Consequently, a web PS Store search is not a reliable way to obtain these games' digital prices. Record a PS3 console-store price manually when one is actually observed; otherwise show “PS3 Store price unavailable.” Never substitute a PS4/PS5 release or remaster.

## Source strategy

1. Start with Brazilian physical listings. Mercado Livre's documented search API requires an access token. The preparation-only candidate command uses that token when configured; do not assume anonymous access or create an external account as part of this plan.
2. Permit manually reviewed product URLs and prices as the baseline. Add another retailer only after confirming a usable API/feed or permission to fetch its pages. Do not bypass anti-bot controls or scrape sites whose terms disallow it.
3. Treat PS Store Brazil as a separate digital source. For the current PS3 wishlist, only a manually observed console-store offer counts as a price. A future wishlist with PS4/PS5 games can be evaluated separately for an authorized, reliable digital price source.
4. Do not scrape PlayStation's website: its Brazilian website terms restrict automated scraping, and its web store omits PS3 purchases.

## Data and matching

Keep the game's internal ID and canonical platform as the anchor. A reviewed offer should record source, listing/product ID, URL, exact title and edition, platform, region, physical/digital format, new/used condition, seller, currency, item price, shipping price or `unknown`, availability, observed-at timestamp, and review status. Preserve raw source evidence privately for troubleshooting, but export only the fields needed by the UI.

Search by public game identity only. Never send the private wishlist, PSN account, purchase history, notes, or credentials to a retailer. Candidate matching must reject or flag another platform, remaster, bundle, DLC, account/key sale, and mismatched edition. A fuzzy title match alone must not become a displayed offer. Unknown availability or shipping remains unknown, not zero.

Compare like with like. Show one Mercado Livre physical offer, regardless of new or used condition, separately from PS3 Store digital. Rank by delivered total only when shipping is known for the relevant destination; otherwise label the result “item price; shipping unknown.” A delivery postcode, if the owner later chooses to provide one, stays local and is not included in the static public-facing search query without a specific privacy decision.

## Release-preparation flow

1. Run an explicit, read-only discovery command against approved sources for the fixed wishlist titles, with conservative request limits and source-specific failure handling.
2. Generate a private candidate-review report. Confirm the exact release/listing mapping before saving an offer observation; allow “no suitable listing” and “needs review.”
3. Save confirmed observations and history in the preparation database or a private local authoring file under `.local/`; never in source control. Record source errors and stale observations separately from genuine absence.
4. Extend the snapshot exporter and validator to include reviewed price projections. Export atomically, then restart the existing read-only service. Normal browsing and the browser make no retailer or PSN requests.

## UI and buying signal

Replace the wishlist's “coming later” area with compact offer information: best verified Mercado Livre physical listing, a separate PS Store row, condition, shipping status, source link, and observation date. Show “no verified offer” or “price unavailable” explicitly. Keep the game card focused on the game; offer details can expand in the wishlist or About view. External links should open safely with `rel="noopener noreferrer"`.

Start with “current observed offer,” not “good deal.” After repeated observations create a meaningful history, show a simple comparison with the lowest observed comparable price over a stated window (for example, 90 days). Do not infer an MSRP, fabricate a discount, or compare item-only prices to delivered totals. Expire or mark stale observations so an old listing cannot look current; recheck availability during each deliberate refresh.

## Delivery phases and acceptance criteria

1. **Manual baseline:** private offer schema, reviewed URL/price entry, snapshot projection, and wishlist display. Acceptance: all 24 games can show an accurate offer or explicit missing state; PS3 digital stays separate.
2. **Approved-source lookup:** validate Mercado Livre API access and terms, then add candidate discovery with review. Acceptance: wrong-platform/edition listings never auto-publish, source failures do not erase prior observations, and no runtime network calls occur.
3. **History:** retain comparable observations and add a cautious buying signal. Acceptance: the UI gives source/date/condition/shipping context and never labels an insufficient-history price a bargain.

Used discs and Mercado Livre are approved. Discovery does not restrict Brazilian sellers or send a delivery postcode. Shipping remains unknown unless a listing has a verified estimate for the destination. No key is needed for the manual baseline; Mercado Livre discovery requires a developer access token. Do not request or store a PSN password for price research.

## References checked 2026-09-27

- [PlayStation Brazil: important notices, PS3 web-store purchase limitation and regional closure](https://www.playstation.com/pt-br/support/important-notice/)
- [PlayStation Brazil: website terms of use](https://www.playstation.com/pt-br/legal/website-terms-of-use/)
- [Mercado Livre Developers: item searches](https://developers.mercadolivre.com.br/itens-e-buscas)

Implementation must continue to honor [STATIC_SNAPSHOT_CONTRACT.md](STATIC_SNAPSHOT_CONTRACT.md) and the future-price constraints in [DECISIONS.md](DECISIONS.md).
