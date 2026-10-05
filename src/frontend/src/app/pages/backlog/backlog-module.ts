import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GameCard } from '../../game-card';
import { FilterDropdown } from '../../filter-dropdown';
import { FormsModule } from '@angular/forms';
import { BacklogRoutingModule } from './backlog-routing-module';
import { BacklogComponent } from './backlog/backlog';

@NgModule({
  declarations: [BacklogComponent],
  imports: [CommonModule, GameCard, FilterDropdown, FormsModule, BacklogRoutingModule],
})
export class BacklogModule {}
