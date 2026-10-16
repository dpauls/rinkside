#!/usr/bin/env python3
"""
RAMP JSON API client for Ontario Women's Hockey Association (OWHA) tournament data.

Fetches standings and game data from the RAMP platform's REST API.
No HTML scraping -- uses the same JSON endpoints the website calls via AJAX.
"""
import json
import logging
import random
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# Default constants (Provincials 2026 legacy defaults)
BASE_URL = 'https://www.owha.on.ca'
LEAGUE_ID = 2910
SEASON_2026 = 13788
SEASON_2025 = 11769  # for testing
DIVISION_U15B_2026 = 16870
DIVISION_U15B_2025 = 16862  # for testing

# Game type IDs
GT_ROUND_ROBIN = 5383
GT_FINALS = 5384
GT_BRONZE = 5428

# Standard modern browser User-Agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# SSL context allowing SSL fallback if municipal certificates expire
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

MAX_RETRIES = 5
RETRY_DELAYS = [0.5, 1.0, 1.5, 2.0, 3.0]


def _fetch_json(url):
    """Fetch JSON from a URL with generalized exponential backoff retry logic.

    Retries on transient HTTP errors (500, 502, 503, 504, 429), timeouts, and
    network resets.
    """
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
    }

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=_ssl_ctx, timeout=12)
            raw = resp.read().decode('utf-8')
            if not raw:
                return []
            data = json.loads(raw)
            if attempt > 0:
                log.info(f'Succeeded on attempt {attempt + 1}: {url}')
            else:
                log.debug(f'Fetched {url}')
            return data
        except urllib.error.HTTPError as e:
            # 404: on some RAMP servers it indicates a transient routing blip or non-existent endpoint
            if e.code == 404:
                if attempt < 2:
                    delay = RETRY_DELAYS[attempt] + random.uniform(0.1, 0.3)
                    log.debug(f'404 received (attempt {attempt + 1}), retrying in {delay:.2f}s...')
                    time.sleep(delay)
                    continue
                log.warning(f'404 Not Found for {url}')
                return None

            # Retry on 5xx or 429
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt] + random.uniform(0.1, 0.4)
                log.warning(f'HTTP {e.code} for {url} (attempt {attempt + 1}/{MAX_RETRIES}), retry in {delay:.2f}s')
                time.sleep(delay)
                continue

            log.error(f'HTTP {e.code} for {url}')
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt] + random.uniform(0.1, 0.4)
                log.warning(f'Network error {e} (attempt {attempt + 1}/{MAX_RETRIES}), retry in {delay:.2f}s')
                time.sleep(delay)
                continue
            log.error(f'Failed after {MAX_RETRIES} attempts: {url}: {e}')
            raise


def fetch_games(season_id=SEASON_2026, division_id=DIVISION_U15B_2026, game_type=0,
                base_url=BASE_URL, league_id=LEAGUE_ID):
    """Fetch all games for a division from RAMP API.

    Returns list of game dicts with keys including:
        gameNumber, HomeTeamName, AwayTeamName, homeScore, awayScore,
        completed, liveScores, sDateString, sDate, ArenaName,
        homePIM, awayPIM, homeTID, awayTID, GID
    """
    url = f'{base_url}/api/leaguegame/get/{league_id}/{season_id}/0/{division_id}/{game_type}/0/0'
    data = _fetch_json(url)
    if data is None:
        return []
    return data


def fetch_standings(season_id=SEASON_2026, division_id=DIVISION_U15B_2026,
                    base_url=BASE_URL, league_id=LEAGUE_ID):
    """Fetch pool-structured standings for a division.

    Returns list of dicts. Pool headers have SID=0 and SubDivName="POOL X".
    Team rows have stats: TeamName, GamesPlayed, Wins, Losses, Ties,
    Points, GF, GA, PIM, PlusMinus, etc.
    """
    url = f'{base_url}/api/leaguegame/getstandings3wsdcached/{league_id}/{season_id}/0/0/{division_id}/0'
    data = _fetch_json(url)
    if data is None:
        return []
    return data


def fetch_bracket_games(season_id=SEASON_2026, division_id=DIVISION_U15B_2026,
                        base_url=BASE_URL, league_id=LEAGUE_ID):
    """Fetch bracket games (finals + bronze) if present."""
    finals = fetch_games(season_id, division_id, GT_FINALS, base_url, league_id) or []
    bronze = fetch_games(season_id, division_id, GT_BRONZE, base_url, league_id) or []
    return finals + bronze


def parse_team_id_from_name(team_name):
    """Extract team number from name like 'Kanata Rangers #1777' or 'Kanata Rangers #1777 (3)'."""
    import re
    m = re.search(r'#?(\d+)', team_name or '')
    return m.group(1) if m else None


def parse_score_from_name(team_name):
    """Extract in-game score appended to team name like 'Kanata Rangers #1777 (3)'."""
    import re
    m = re.search(r'\((\d+)\)\s*$', team_name or '')
    return int(m.group(1)) if m else None


def games_to_tournament_format(games, team_id_map, teams_dict=None):
    """Convert RAMP API game data to internal tournament game format.

    Args:
        games: list of game dicts from fetch_games()
        team_id_map: dict mapping OWHA team number (str) to our short ID, e.g. {'1777': 'KAN'}
        teams_dict: optional dict mapping team ID to team metadata (containing 'pool')

    Returns list of game dicts in normalized format.
    """
    result = []
    for g in games:
        home_num = parse_team_id_from_name(g.get('HomeTeamName'))
        away_num = parse_team_id_from_name(g.get('AwayTeamName'))

        home_id = team_id_map.get(str(home_num)) if home_num else None
        away_id = team_id_map.get(str(away_num)) if away_num else None

        if not home_id or not away_id:
            # If not in our tracked teams map, check if it's a TBD playoff game or other game
            home_id = home_id or (g.get('HomeTeamName') or 'TBD')
            away_id = away_id or (g.get('AwayTeamName') or 'TBD')

        # Determine pool
        pool = None
        if teams_dict:
            pool = teams_dict.get(home_id, {}).get('pool') or teams_dict.get(away_id, {}).get('pool')

        # Determine game status
        if g.get('completed'):
            status = 'final'
        elif g.get('homeScore') is not None and g.get('awayScore') is not None:
            status = 'in_progress'
        else:
            status = 'scheduled'

        # Robust game ID fallback: gameNumber or GID
        game_id = g.get('gameNumber') or g.get('GID')

        result.append({
            'game_id': game_id,
            'gid': g.get('GID'),
            'pool': pool,
            'date': g.get('sDate'),
            'date_str': g.get('sDateString'),
            'arena': g.get('ArenaName'),
            'home': home_id,
            'away': away_id,
            'home_name': g.get('HomeTeamName'),
            'away_name': g.get('AwayTeamName'),
            'home_score': g.get('homeScore'),
            'away_score': g.get('awayScore'),
            'home_pim': g.get('homePIM'),
            'away_pim': g.get('awayPIM'),
            'status': status,
            'completed': g.get('completed', False),
            'live_scores': g.get('liveScores', False),
        })

    result.sort(key=lambda g: g.get('date') or '')
    return result


def standings_to_pool_map(standings):
    """Convert RAMP standings to pool -> teams structure."""
    pools = {}
    current_pool = None
    for entry in standings:
        if entry.get('SID') == 0:
            current_pool = entry.get('SubDivName', '').replace('POOL ', '').strip()
            pools[current_pool] = []
        elif current_pool:
            num = parse_team_id_from_name(entry.get('TeamName'))
            pools[current_pool].append({
                'name': entry.get('TeamName', '').split('#')[0].strip(),
                'number': num,
                'gp': entry.get('GamesPlayed', 0),
                'w': entry.get('Wins', 0),
                'l': entry.get('Losses', 0),
                't': entry.get('Ties', 0),
                'pts': entry.get('Points', 0),
                'gf': entry.get('GF', 0),
                'ga': entry.get('GA', 0),
                'pim': entry.get('PIM', 0),
                'plus_minus': entry.get('PlusMinus', 0),
            })
    return pools


def detect_changes(prev_games, curr_games):
    """Compare two game lists and detect changes.

    Returns list of change dicts:
        {'type': 'score_change'|'game_final'|'game_started'|'correction',
         'game_id': ..., 'prev': ..., 'curr': ...}
    """
    prev_map = {g['game_id']: g for g in prev_games if g.get('game_id') is not None}
    changes = []

    for g in curr_games:
        gid = g.get('game_id')
        if gid is None:
            continue
        prev = prev_map.get(gid)
        if not prev:
            continue

        # Game started
        if prev['status'] == 'scheduled' and g['status'] == 'in_progress':
            changes.append({
                'type': 'game_started',
                'game_id': gid,
                'prev': prev,
                'curr': g,
            })
        # Score change during game
        elif prev['status'] == 'in_progress' and g['status'] == 'in_progress':
            if prev['home_score'] != g['home_score'] or prev['away_score'] != g['away_score']:
                changes.append({
                    'type': 'score_change',
                    'game_id': gid,
                    'prev': prev,
                    'curr': g,
                })
        # Game completed (either from in_progress or directly from scheduled)
        elif prev['status'] != 'final' and g['status'] == 'final':
            changes.append({
                'type': 'game_final',
                'game_id': gid,
                'prev': prev,
                'curr': g,
            })
        # Correction
        elif prev['status'] == 'final' and g['status'] == 'final':
            if prev['home_score'] != g['home_score'] or prev['away_score'] != g['away_score']:
                changes.append({
                    'type': 'correction',
                    'game_id': gid,
                    'prev': prev,
                    'curr': g,
                })

    return changes


class MockDataSource:
    """Reads API responses from local JSON files for testing."""

    def __init__(self, mock_dir):
        self.mock_dir = Path(mock_dir)
        self._files = sorted(self.mock_dir.glob('step_*.json'))
        self._step_file = self.mock_dir / '.mock_step'
        self.step = self._load_step()
        log.info(f'MockDataSource: {len(self._files)} steps in {mock_dir}, starting at step {self.step}')

    def _load_step(self):
        if self._step_file.exists():
            try:
                return int(self._step_file.read_text().strip())
            except ValueError:
                return 0
        return 0

    def _save_step(self):
        self._step_file.write_text(str(self.step))

    def reset(self):
        self.step = 0
        self._save_step()

    def fetch_games(self):
        if self.step >= len(self._files):
            log.info('MockDataSource: no more steps, returning last')
            return json.loads(self._files[-1].read_text())
        data = json.loads(self._files[self.step].read_text())
        log.info(f'MockDataSource: step {self.step} -> {self._files[self.step].name}')
        self.step += 1
        self._save_step()
        return data


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'games'
    print(f'Running scraper test command: {cmd}')
    if cmd == 'ptr':
        games = fetch_games(season_id=14974, division_id=25410, league_id=3065, base_url='https://www.owha.on.ca')
        print(f'Fetched {len(games)} games for Pink the Rink U18C')
        for g in games[:5]:
            print(f'  {g.get("sDateString")}: {g.get("HomeTeamName")} vs {g.get("AwayTeamName")} ({g.get("ArenaName")})')
