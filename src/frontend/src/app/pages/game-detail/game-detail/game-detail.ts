import { Component, OnInit, OnDestroy, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subject, forkJoin } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService, Game, Trophy, trophyProgress, errorMessage } from '../../../services/api';
import { artwork, displayTitle, genres, igdbScore, igdbScoreCount, platinum, releaseYear, specificationList, trophyCounts } from '../../../services/presentation';
import { FilterOption } from '../../../filter-dropdown';

@Component({ selector: 'app-game-detail', standalone: false, templateUrl: './game-detail.html',
  styleUrl: './game-detail.scss', changeDetection: ChangeDetectionStrategy.OnPush })
export class GameDetailComponent implements OnInit, OnDestroy {
  game: Game | null = null; trophies: Trophy[] = []; loading = true; error = ''; id = 0;
  activeTab = 'about'; trophyFilter = 'unearned'; groupFilter = 'all'; hideSpoilers = true;
  readonly tiers = ['bronze','silver','gold','platinum'];
  readonly groupOptions: FilterOption[] = [
    { value: 'all', label: 'All sets' }, { value: 'base', label: 'Base game' },
    { value: 'dlc', label: 'DLC' }, { value: 'unknown', label: 'Unknown' },
  ];
  progress = trophyProgress; genres = genres; platinum = platinum; counts = trophyCounts;
  displayTitle = displayTitle; releaseYear = releaseYear;
  igdbScore = igdbScore; igdbScoreCount = igdbScoreCount;
  artwork = artwork; specificationList = specificationList;
  private destroy$ = new Subject<void>(); private reload$ = new Subject<void>();
  constructor(private api: ApiService, private route: ActivatedRoute, private cdr: ChangeDetectorRef) {}
  ngOnInit() {
    this.route.paramMap.pipe(takeUntil(this.destroy$)).subscribe(params => {
      this.id = Number(params.get('id')); this.activeTab = 'about'; this.trophyFilter = 'unearned'; this.groupFilter = 'all'; this.load();
    });
  }
  ngOnDestroy() { this.destroy$.next(); this.destroy$.complete(); this.reload$.next(); this.reload$.complete(); }
  load() {
    this.reload$.next(); this.loading = true; this.error = ''; this.game = null; this.trophies = [];
    forkJoin({game: this.api.getGame(this.id), trophies: this.api.getTrophies(this.id)})
      .pipe(takeUntil(this.reload$), takeUntil(this.destroy$)).subscribe({
        next: ({game,trophies}) => {
          this.game = game; this.trophies = trophies;
          if (trophies.length && trophies.every(t => t.earned)) this.trophyFilter = 'earned';
          this.loading = false; this.cdr.markForCheck();
        },
        error: e => { this.error = errorMessage(e); this.loading = false; this.cdr.markForCheck(); }
      });
  }
  get earned() { return this.trophies.filter(t => t.earned).length; }
  get tierCounts() { return this.tiers.map(tier => ({tier,earned:this.trophies.filter(t => t.trophy_type === tier && t.earned).length,total:this.trophies.filter(t => t.trophy_type === tier).length})); }
  get filteredTrophies() {
    return this.trophies.filter(t => (this.trophyFilter === 'all' || (this.trophyFilter === 'earned' ? t.earned : !t.earned)) &&
      (this.groupFilter === 'all' || (this.groupFilter === 'base' ? t.is_dlc === false : this.groupFilter === 'dlc' ? t.is_dlc === true : t.is_dlc == null)));
  }
  concealed(trophy: Trophy) { return this.hideSpoilers && trophy.is_hidden && !trophy.earned; }
}
