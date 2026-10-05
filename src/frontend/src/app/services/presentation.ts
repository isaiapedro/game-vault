import { Game, trophyProgress } from './api';

// Editorial browsing tags for this fixed catalogue, not provider metadata.
// Specific series precede broad matches. Unrecognized releases stay unclassified.
const GENRES: [RegExp, string[]][] = [
  [/alien: isolation|dead space|evil within/i, ['Survival horror', 'Action']],
  [/resident evil|shadows of the damned|dead island/i, ['Action', 'Horror']],
  [/bioshock|metro:|darkness ii|resistance|killzone|wolfenstein|battlefield|call of duty|modern warfare/i, ['Shooter']],
  [/borderlands/i, ['Shooter', 'RPG']],
  [/mass effect/i, ['RPG', 'Shooter']],
  [/xcom/i, ['Strategy', 'Turn-based']],
  [/final fantasy|ni no kuni|south park/i, ['RPG', 'Turn-based']],
  [/dark souls|demon.s souls|dragon.s dogma|kingdoms of amalur/i, ['Action RPG']],
  [/dragon age|skyrim|elder scrolls|fallout/i, ['RPG', 'Exploration']],
  [/deus ex/i, ['Stealth', 'RPG']],
  [/metal gear solid|splinter cell|hitman|dishonored|^thief$/i, ['Stealth']],
  [/heavy rain|beyond:|sherlock|murdered:|l.a. noire/i, ['Adventure', 'Mystery']],
  [/gran turismo|need for speed/i, ['Racing']],
  [/fifa|nba 2k|sports champions/i, ['Sports']],
  [/mortal kombat|smackdown/i, ['Fighting']],
  [/ratchet|jak |jak ii|sly |rayman|littlebigplanet|prince of persia|^ico$|lego/i, ['Platformer', 'Adventure']],
  [/devil may cry|god of war|metal gear rising|splatterhouse/i, ['Action', 'Hack & slash']],
  [/zone of the enders/i, ['Action', 'Mecha']],
  [/vanquish|spec ops|yakuza.*dead souls/i, ['Shooter', 'Action']],
  [/hotline miami/i, ['Action', 'Arcade']],
  [/batman: arkham asylum/i, ['Action', 'Adventure']],
  [/assassin|batman|infamous|sleeping dogs|prototype|just cause|mafia|mercenaries|far cry/i, ['Action', 'Open world']],
  [/uncharted|tomb raider|shadow of the colossus|darksiders|force unleashed|medieval moves/i, ['Action', 'Adventure']],
  [/mirror.s edge/i, ['Platformer', 'Parkour']],
];

export function genres(game: Game): string[] {
  const label: Record<string, string> = {
    'Role-playing (RPG)': 'RPG', "Hack and slash/Beat 'em up": 'Hack & slash',
    'Sport': 'Sports', 'Platform': 'Platformer', 'Simulator': 'Simulation',
    'Real Time Strategy (RTS)': 'RTS', 'Turn-based strategy (TBS)': 'Turn-based',
    'Tactical': 'Tactics',
  };
  const supplied = (game.genres ?? []).filter((value) => typeof value === 'string' && value.trim())
    .map(value => label[value] ?? value);
  const original = game.specifications?.['catalog_title_before_psn'];
  const title = typeof original === 'string' ? original : game.title;
  const editorial = GENRES.find(([pattern]) => pattern.test(title))?.[1] ?? [];
  const combined = [...new Set([...editorial, ...supplied])];
  return combined.sort((a, b) => (a === 'Adventure' ? 1 : 0) - (b === 'Adventure' ? 1 : 0)).slice(0, 2);
}

export function displayTitle(game: Game): string {
  const title = game.specifications?.['display_title'];
  return typeof title === 'string' && title.trim() ? title : game.title;
}

export function releaseYear(game: Game): string | null {
  const year = game.release_date?.slice(0, 4);
  return year && /^\d{4}$/.test(year) ? year : null;
}

export function igdbScore(game: Game): number | null {
  const value = game.specifications?.['igdb_user_rating'];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
}

export function igdbScoreCount(game: Game): number | null {
  const value = game.specifications?.['igdb_user_rating_count'];
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

export function specificationList(game: Game, key: string, limit = 4): string[] {
  const value = game.specifications?.[key];
  return Array.isArray(value) ? value.filter((item): item is string =>
    typeof item === 'string' && !!item.trim()).slice(0, limit) : [];
}

export function artwork(game: Game): string[] {
  return specificationList(game, 'igdb_artwork_urls', 2)
    .filter(url => /^\/artwork\/[0-9]+-[12]\.jpg$/.test(url));
}

export function platinum(game: Game): boolean {
  return !!game.platinum_earned || (!game.platinum_manual_override && (game.psn_earned_platinum ?? 0) > 0);
}

export function finished(game: Game): boolean {
  return platinum(game) || game.is_completed === true || game.play_state === 'finished' || trophyProgress(game) === 100;
}

export function trophyCounts(game: Game): { earned: number; total: number; scope: string } | null {
  if (game.psn_total_trophies != null && game.psn_total_trophies > 0 && game.psn_earned_trophies != null)
    return { earned: game.psn_earned_trophies, total: game.psn_total_trophies, scope: 'PSN summary' };
  if (game.trophy_count && game.trophy_count > 0)
    return { earned: game.earned_count ?? 0, total: game.trophy_count, scope: 'Saved trophy details' };
  return null;
}

export function variety<T extends Game>(games: T[], limit = 3): T[] {
  const picked: T[] = [], seen = new Set<string>();
  for (const game of games) {
    if (game.ownership === 'wanted' || finished(game) || game.play_state === 'dropped' || game.platinum_feasibility === 'blocked') continue;
    const genre = genres(game)[0];
    if (!genre || seen.has(genre)) continue;
    picked.push(game); seen.add(genre);
    if (picked.length === limit) break;
  }
  return picked;
}
