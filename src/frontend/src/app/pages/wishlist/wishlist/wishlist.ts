import { Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService, Game, PriceOffer, PriceOffers, errorMessage } from '../../../services/api';

@Component({ selector: 'app-wishlist', standalone: false, templateUrl: './wishlist.html',
  styleUrl: './wishlist.scss', changeDetection: ChangeDetectionStrategy.OnPush })
export class WishlistComponent implements OnInit, OnDestroy {
  readonly offerKinds = ['mercado_livre', 'ps3_store'] as const;
  games: Game[] = []; loading = true; error = '';
  private destroy$ = new Subject<void>();
  constructor(private api: ApiService, private cdr: ChangeDetectorRef) {}
  safeOfferUrl(offer: PriceOffer): string | null {
    if (!offer.url) return null;
    try {
      const url = new URL(offer.url);
      return url.protocol === 'https:' ? url.href : null;
    } catch { return null; }
  }
  offerTotal(offer: PriceOffer): number | null {
    return offer.shipping_price == null ? null : offer.item_price + offer.shipping_price;
  }
  offerFor(game: Game, kind: 'mercado_livre' | 'ps3_store'): PriceOffer | null {
    const offers = game.price_offers;
    if (!offers) return null;
    if (kind === 'ps3_store') return offers.ps3_store;
    if ('mercado_livre' in offers) return offers.mercado_livre ?? null;
    const candidates = [offers.physical_new, offers.physical_used].filter((offer): offer is PriceOffer => !!offer);
    return candidates.sort((a, b) => (this.offerTotal(a) ?? a.item_price) - (this.offerTotal(b) ?? b.item_price))[0] ?? null;
  }
  ngOnInit() { this.load(); }
  ngOnDestroy() { this.destroy$.next(); this.destroy$.complete(); }
  load() {
    this.loading = true; this.error = '';
    this.api.getWishlist().pipe(takeUntil(this.destroy$)).subscribe({
      next: games => { this.games = games; this.loading = false; this.cdr.markForCheck(); },
      error: e => { this.error = errorMessage(e); this.loading = false; this.cdr.markForCheck(); }
    });
  }
}
