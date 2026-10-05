import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GameCard } from '../../game-card';
import { FormsModule } from '@angular/forms';
import { StatisticsRoutingModule } from './statistics-routing-module';
import { StatisticsComponent } from './statistics/statistics';

@NgModule({
  declarations: [StatisticsComponent],
  imports: [CommonModule, GameCard, FormsModule, StatisticsRoutingModule],
})
export class StatisticsModule {}
