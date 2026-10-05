import { Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { Subject, forkJoin } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService, Game, Statistics, trophyProgress, errorMessage } from '../../../services/api';
import { platinum, finished } from '../../../services/presentation';

@Component({ selector: 'app-statistics', standalone: false, templateUrl: './statistics.html',
  styleUrl: './statistics.scss', changeDetection: ChangeDetectionStrategy.OnPush })
export class StatisticsComponent implements OnInit, OnDestroy {
  games: Game[] = []; stats: Statistics | null = null; loading = true; error = '';
  readonly tiers = ['bronze','silver','gold','platinum'];
  private destroy$ = new Subject<void>();
  constructor(private api: ApiService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.load(); }
  ngOnDestroy() { this.destroy$.next(); this.destroy$.complete(); }
  load() {
    this.loading = true; this.error = '';
    forkJoin({games: this.api.getGames(), stats: this.api.getStatistics()}).pipe(takeUntil(this.destroy$)).subscribe({
      next: ({games,stats}) => { this.games = games; this.stats = stats; this.loading = false; this.cdr.markForCheck(); },
      error: e => { this.error = errorMessage(e); this.loading = false; this.cdr.markForCheck(); }
    });
  }
  get platinums() { return this.games.filter(platinum); }
  get known() { return this.games.filter(g => trophyProgress(g) != null); }
  get average() { return this.known.length ? this.known.reduce((n,g) => n + trophyProgress(g)!,0) / this.known.length : null; }
  get close() { return this.games.filter(g => !finished(g) && (trophyProgress(g) ?? 0) > 0 && g.platinum_feasibility !== 'blocked')
    .sort((a,b) => trophyProgress(b)! - trophyProgress(a)!).slice(0,3); }
  tierCount(tier: string, kind: string) { return this.stats?.trophies[(tier === 'platinum' ? 'platinum_trophy' : tier) + '_' + kind] ?? 0; }
}
