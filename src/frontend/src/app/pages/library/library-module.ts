import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GameCard } from '../../game-card';
import { FilterDropdown } from '../../filter-dropdown';
import { FormsModule } from '@angular/forms';
import { LibraryRoutingModule } from './library-routing-module';
import { LibraryComponent } from './library/library';

@NgModule({
  declarations: [LibraryComponent],
  imports: [CommonModule, GameCard, FilterDropdown, FormsModule, LibraryRoutingModule],
})
export class LibraryModule {}
