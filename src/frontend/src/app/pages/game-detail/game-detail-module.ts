import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { FilterDropdown } from '../../filter-dropdown';
import { GameDetailRoutingModule } from './game-detail-routing-module';
import { GameDetailComponent } from './game-detail/game-detail';

@NgModule({
  declarations: [GameDetailComponent],
  imports: [CommonModule, FilterDropdown, FormsModule, GameDetailRoutingModule],
})
export class GameDetailModule {}
