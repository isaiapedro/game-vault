import { Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService, Game, trophyProgress, errorMessage } from '../../../services/api';
import { displayTitle, genres, platinum, finished } from '../../../services/presentation';
import { FilterOption } from '../../../filter-dropdown';

@Component({ selector: 'app-library', standalone: false, templateUrl: './library.html',
  styleUrl: './library.scss', changeDetection: ChangeDetectionStrategy.OnPush })
export class LibraryComponent implements OnInit, OnDestroy {
  games: Game[] = []; loading = true; error = '';
  query = ''; access = 'all'; state = 'all'; genre = 'all'; sort = 'title'; view = 'cards';
  readonly accessOptions: FilterOption[] = [
    { value: 'all', label: 'All games' }, { value: 'ready', label: 'Ready to play' }, { value: 'wanted', label: 'Not owned' },
  ];
  readonly sortOptions: FilterOption[] = [
    { value: 'title', label: 'Title A–Z' }, { value: 'progress', label: 'Most progress' },
  ];
  private destroy$ = new Subject<void>();
  constructor(private api: ApiService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.load(); }
  ngOnDestroy() { this.destroy$.next(); this.destroy$.complete(); }
  load() {
    this.loading = true; this.error = '';
    this.api.getGames().pipe(takeUntil(this.destroy$)).subscribe({
      next: games => { this.games = games; this.loading = false; this.cdr.markForCheck(); },
      error: e => { this.error = errorMessage(e); this.loading = false; this.cdr.markForCheck(); }
    });
  }
  get platinumCount() { return this.games.filter(platinum).length; }
  get startedCount() { return this.games.filter(g => (trophyProgress(g) ?? 0) > 0 && !finished(g)).length; }
  get genreOptions() { return [...new Set(this.games.flatMap(genres))].sort(); }
  get genreFilterOptions(): FilterOption[] {
    return [{ value: 'all', label: 'All genres' }, ...this.genreOptions.map(value => ({ value, label: value }))];
  }
  get filtered() {
    return this.games.filter(g =>
      [displayTitle(g), g.title, g.specifications?.['catalog_title_before_psn']].some(value =>
        typeof value === 'string' && value.toLowerCase().includes(this.query.toLowerCase())) &&
      (this.access === 'all' || (this.access === 'wanted' ? g.ownership === 'wanted' : g.ownership !== 'wanted')) &&
      (this.genre === 'all' || genres(g).includes(this.genre)) &&
      (this.state === 'all' || (this.state === 'platinum' ? platinum(g) :
        this.state === 'playing' ? !finished(g) && (trophyProgress(g) ?? 0) > 0 :
        this.state === 'unknown' ? trophyProgress(g) == null : trophyProgress(g) === 0))
    ).sort((a,b) => this.sort === 'progress' ? (trophyProgress(b) ?? -1) - (trophyProgress(a) ?? -1) || displayTitle(a).localeCompare(displayTitle(b)) : displayTitle(a).localeCompare(displayTitle(b)));
  }
  reset() { this.query = ''; this.access = this.state = this.genre = 'all'; }
}
