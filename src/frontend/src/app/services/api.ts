import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { tap } from 'rxjs/operators';

export type Ownership = 'owned' | 'wanted' | 'available';
export type PlayState = 'not_started' | 'playing' | 'paused' | 'finished' | 'dropped';
export type Goal = 'completionist';
export interface PriceOffer {
  source: string;
  url: string | null;
  title: string;
  condition: string;
  currency: string;
  item_price: number;
  shipping_price: number | null;
  observed_at: string;
  availability: string;
}
export interface PriceOffers {
  mercado_livre?: PriceOffer | null;
  physical_new?: PriceOffer | null;
  physical_used?: PriceOffer | null;
  ps3_store: PriceOffer | null;
}
export interface Game {
  price_offers?: PriceOffers;
  genres?: string[];
  description?: string;
  developer?: string;
  publisher?: string;
  psn_earned_platinum?: number;
  platinum_manual_override?: boolean;
  remaining_hours?: number | null;
  progress_pct?: number | null;
  progress_source?: 'psn_summary' | 'loaded_trophies' | 'unknown';
  is_completed?: boolean;
  manual_play_state?: PlayState;
  completion_reason?: 'manual' | 'platinum' | 'trophy_progress' | null;
  id: number;
  game_id?: number;
  title: string;
  platform: string;
  cover_url?: string;
  release_date?: string;
  ownership: Ownership;
  play_state: PlayState;
  goal: Goal;
  status?: string;
  notes?: string;
  next_action?: string;
  trophy_count?: number;
  earned_count?: number;
  psn_progress?: number;
  psn_earned_trophies?: number;
  psn_total_trophies?: number;
  psn_summary_at?: string;
  platinum_earned?: boolean;
  in_backlog?: boolean;
  hltb_main_hours?: number;
  hltb_extra_hours?: number;
  hltb_completionist_hours?: number;
  platinum_hours?: number;
  platinum_feasibility?: string;
  platinum_blocker_reason?: string;
  platinum_evidence_url?: string;
  platinum_checked_at?: string;
  added_at?: string;
  specifications?: Record<string, unknown>;
  user_notes?: string;
  time_estimates?: {
    provider: string;
    match_confidence?: string;
    retrieved_at?: string;
    category?: string;
    hours?: number;
  }[];
}
export interface Trophy {
  id: number;
  name: string;
  description?: string;
  trophy_type: string;
  earned: boolean;
  earned_at?: string;
  is_hidden?: boolean;
  group_id?: string;
  group_name?: string;
  is_dlc?: boolean;
}
export interface QueueEntry extends Game {
  target_date?: string;
  game_id: number;
  position: number;
  estimated_hours?: number;
  estimate_kind?: string;
  available?: boolean;
}
export interface QueueSummary {
  total_estimated_hours: number;
  known_estimate_count: number;
  unknown_estimate_count: number;
  available_count: number;
  unavailable_count: number;
  total_count: number;
  coverage_pct: number;
}
export interface Backlog extends QueueSummary {
  entries: QueueEntry[];
}
export interface Statistics {
  library: Record<string, number>;
  this_month?: { earned_trophies: number };
  trophies: Record<string, number>;
  backlog: QueueSummary;
  insights?: { finish_soon: (QueueEntry & { reason: string })[]; blocked: Game[] };
  milestones?: { game_id: number; title: string; name: string; earned_at: string }[];
}
export interface Candidate {
  igdb_id: number;
  id?: number;
  title: string;
  name?: string;
  cover_url?: string;
  release_date?: string;
  specifications?: { platforms?: string[] };
}
export interface JobStatus {
  running: boolean;
  done_games?: number;
  total_games?: number;
  current_game?: string;
  error?: string;
  errors?: unknown[];
  failed_games?: number;
  done?: number;
  total?: number;
  message?: string;
  failed?: number;
  skipped?: number;
  unmatched_titles?: {
    np_communication_id: string;
    title_name: string;
    platforms: string[];
    local_matches?: {
      game_id: number;
      title: string;
      platform: string;
      match_state: 'legacy' | 'suggested';
      match_reason:
        | 'existing_unconfirmed_id'
        | 'same_normalized_title_and_platform'
        | 'character_similarity_and_platform';
      match_score?: number;
      automatic?: boolean;
    }[];
  }[];
  captured_at?: string;
  last_sync?: string;
}
export function errorMessage(error: unknown): string {
  if (error instanceof HttpErrorResponse && typeof error.error?.detail === 'string')
    return error.error.detail;
  return 'Could not complete the request. Please try again.';
}
export function trophyProgress(game: Game): number | null {
  const progress = game.progress_pct ?? game.psn_progress;
  if (progress != null) return Math.max(0, Math.min(100, progress));
  return game.trophy_count
    ? Math.max(0, Math.min(100, ((game.earned_count || 0) / game.trophy_count) * 100))
    : null;
}
export function completed(game: Game): boolean {
  return (
    game.is_completed ??
    (game.play_state === 'finished' || !!game.platinum_earned || trophyProgress(game) === 100)
  );
}
export function goalHours(game: Game): number | undefined {
  if (completed(game)) return 0;
  if (game.remaining_hours != null) return game.remaining_hours;
  const progress = trophyProgress(game),
    total = game.hltb_completionist_hours;
  return total != null && total > 0 && progress != null
    ? Math.round(total * (1 - progress / 100) * 10) / 10
    : undefined;
}
export function label(value: string | undefined): string {
  return (value || 'unknown').replaceAll('_', ' ');
}
// The static release is served by the same FastAPI process as the UI.
const BASE = '/api';
@Injectable({ providedIn: 'root' })
export class ApiService {
  private cache = new Map<string, { data: unknown; ts: number }>();
  private generation = 0;
  constructor(private http: HttpClient) {}
  private cached<T>(key: string, request: Observable<T>): Observable<T> {
    const hit = this.cache.get(key),
      generation = this.generation;
    if (hit && Date.now() - hit.ts < 30000) return of(hit.data as T);
    return request.pipe(
      tap((data) => {
        if (generation === this.generation) this.cache.set(key, { data, ts: Date.now() });
      }),
    );
  }
  private mutate<T>(request: Observable<T>): Observable<T> {
    return request.pipe(tap(() => this.invalidateAll()));
  }
  invalidate(...keys: string[]) {
    this.generation++;
    keys.forEach((key) => this.cache.delete(key));
  }
  invalidatePrefix(prefix: string) {
    this.generation++;
    for (const key of this.cache.keys()) if (key.startsWith(prefix)) this.cache.delete(key);
  }
  invalidateAll() {
    this.generation++;
    this.cache.clear();
  }
  getGames() {
    return this.cached('games', this.http.get<Game[]>(BASE + '/games'));
  }
  getGame(id: number) {
    return this.cached('game:' + id, this.http.get<Game>(BASE + '/games/' + id));
  }
  searchIgdb(q: string) {
    return this.http.get<Candidate[]>(BASE + '/enrich/igdb/search', { params: { q } });
  }
  addGame(payload: { title: string; platform: string; ownership: Ownership; igdb_id?: number }) {
    return this.mutate(this.http.post<Game>(BASE + '/games', payload));
  }
  updateCollection(
    id: number,
    payload: Partial<
      Pick<
        Game,
        | 'ownership'
        | 'play_state'
        | 'notes'
        | 'next_action'
        | 'platinum_feasibility'
        | 'platinum_blocker_reason'
        | 'platinum_evidence_url'
      >
    >,
  ) {
    return this.mutate(this.http.patch<Game>(BASE + '/games/' + id + '/collection', payload));
  }
  getBacklog() {
    return this.cached('backlog', this.http.get<Backlog>(BASE + '/backlog'));
  }
  addToBacklog(game_id: number) {
    return this.mutate(this.http.post(BASE + '/backlog', { game_id }));
  }
  removeFromBacklog(id: number) {
    return this.mutate(this.http.delete(BASE + '/backlog/' + id));
  }
  reorderBacklog(ordered_game_ids: number[], expected_game_ids?: number[]) {
    return this.mutate(
      this.http.put(BASE + '/backlog/reorder', { ordered_game_ids, expected_game_ids }),
    );
  }
  getWishlist() {
    return this.cached('wishlist', this.http.get<Game[]>(BASE + '/wishlist'));
  }
  removeFromWishlist(id: number) {
    return this.mutate(this.http.delete(BASE + '/wishlist/' + id));
  }
  getTrophies(id: number) {
    return this.cached('trophies:' + id, this.http.get<Trophy[]>(BASE + '/trophies/' + id));
  }
  getTrophyGuide(id: number) {
    return this.http.get<{ psnprofiles_url?: string; content?: string }>(
      BASE + '/trophies/' + id + '/guide',
    );
  }
  earnTrophy(id: number) {
    return this.mutate(this.http.post(BASE + '/user-trophies/' + id + '/earn', {}));
  }
  unearnTrophy(id: number) {
    return this.mutate(this.http.delete(BASE + '/user-trophies/' + id + '/earn'));
  }
  getStatistics() {
    return this.cached('statistics', this.http.get<Statistics>(BASE + '/statistics'));
  }
  syncPsn() {
    return this.mutate(this.http.post(BASE + '/sync/psn', {}));
  }
  getSyncStatus() {
    return this.http.get<JobStatus>(BASE + '/sync/status');
  }
  startHltbEnrich() {
    return this.mutate(this.http.post(BASE + '/enrich/hltb', {}));
  }
  getHltbStatus() {
    return this.http.get<JobStatus>(BASE + '/enrich/hltb/status');
  }
  applyMetadata(id: number, igdb_id: number) {
    return this.mutate(this.http.post(BASE + '/enrich/igdb/' + id, { igdb_id, confirmed: true }));
  }
  bindPsn(id: number, np_communication_id: string) {
    return this.mutate(
      this.http.put(BASE + '/sync/mappings/' + id, { np_communication_id, confirmed: true }),
    );
  }
  getIgdbStatus() {
    return this.http.get<{ configured: boolean }>(BASE + '/enrich/igdb/status');
  }
}
