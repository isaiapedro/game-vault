import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Game, trophyProgress } from './services/api';
import { displayTitle, platinum } from './services/presentation';

@Component({
  selector: 'gv-game-card', standalone: true, imports: [CommonModule, RouterModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a class="game-card progress-surface" [class.is-platinum]="platinum(game)"
      [style.--fill]="(progress(game) ?? 0) + '%'" [routerLink]="['/games', game.game_id ?? game.id]">
      <span class="card-rank" *ngIf="rank">{{ rank | number:'2.0' }}</span>
      <img *ngIf="game.cover_url && !imageFailed; else fallback" class="cover" [src]="game.cover_url" alt="" loading="lazy" (error)="imageFailed = true" />
      <ng-template #fallback><span class="cover cover-fallback" aria-hidden="true">{{ displayTitle(game).slice(0, 2).toUpperCase() }}</span></ng-template>
      <div class="card-copy">
        <h3>{{ displayTitle(game) }}</h3>
      </div>
      <div class="card-progress" [attr.aria-label]="progress(game) == null ? 'Trophy progress unknown' : (progress(game) | number:'1.0-1') + '% trophy progress'">
        <strong>{{ progress(game) == null ? '—' : (progress(game) | number:'1.0-1') + '%' }}</strong>
        <small>{{ progress(game) == null ? 'No PSN progress' : 'trophies' }}</small>
      </div>
      <span class="card-progress-line" aria-hidden="true"></span>
    </a>
  `,
})
export class GameCard {
  @Input({ required: true }) game!: Game;
  @Input() rank: number | null = null;
  imageFailed = false;
  progress = trophyProgress; platinum = platinum; displayTitle = displayTitle;
}
