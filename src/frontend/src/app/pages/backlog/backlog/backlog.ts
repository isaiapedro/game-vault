import { Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { Subject, forkJoin } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService, QueueEntry, errorMessage } from '../../../services/api';
import { genres, finished, variety } from '../../../services/presentation';
import { FilterOption } from '../../../filter-dropdown';

@Component({ selector: 'app-backlog', standalone: false, templateUrl: './backlog.html',
  styleUrl: './backlog.scss', changeDetection: ChangeDetectionStrategy.OnPush })
export class BacklogComponent implements OnInit, OnDestroy {
  entries: QueueEntry[] = []; loading = true; error = ''; genre = 'all'; access = 'ready'; showFinished = false;
  readonly accessOptions: FilterOption[] = [
    { value: 'ready', label: 'Ready to play' }, { value: 'all', label: 'All games' }, { value: 'wanted', label: 'Not owned' },
  ];
  private destroy$ = new Subject<void>();
  constructor(private api: ApiService, private cdr: ChangeDetectorRef) {}
  ngOnInit() { this.load(); }
  ngOnDestroy() { this.destroy$.next(); this.destroy$.complete(); }
  load() {
    this.loading = true; this.error = '';
    forkJoin({ queue: this.api.getBacklog(), games: this.api.getGames() }).pipe(takeUntil(this.destroy$)).subscribe({
      next: ({queue,games}) => {
        const byId = new Map(games.map(g => [g.id,g]));
        this.entries = queue.entries.map(e => ({ ...byId.get(e.game_id), ...e }));
        this.loading = false; this.cdr.markForCheck();
      },
      error: e => { this.error = errorMessage(e); this.loading = false; this.cdr.markForCheck(); }
    });
  }
  get picks() { return variety(this.entries); }
  get genreOptions() { return [...new Set(this.entries.flatMap(genres))].sort(); }
  get genreFilterOptions(): FilterOption[] {
    return [{ value: 'all', label: 'All genres' }, ...this.genreOptions.map(value => ({ value, label: value }))];
  }
  get filtered() { return this.entries.filter(e => (this.showFinished || !finished(e)) &&
    (this.access === 'all' || (this.access === 'ready' ? e.ownership !== 'wanted' : e.ownership === 'wanted')) &&
    (this.genre === 'all' || genres(e).includes(this.genre))); }
}
