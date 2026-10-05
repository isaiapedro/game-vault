import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GameCard } from '../../game-card';
import { WishlistRoutingModule } from './wishlist-routing-module';
import { WishlistComponent } from './wishlist/wishlist';

@NgModule({
  declarations: [WishlistComponent],
  imports: [CommonModule, GameCard, WishlistRoutingModule],
})
export class WishlistModule {}
