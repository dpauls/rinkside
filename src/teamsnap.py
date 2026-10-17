#!/usr/bin/env python3
"""
TeamSnap Tournaments REST API client.

Fetches schedules, divisions, matches, seedings, and venues directly from the public
TeamSnap Tournaments REST API endpoints used by the mobile app and web frontend.
"""
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)

BASE_URL = 'https://tournaments-api.teamsnap.com/public'
DEFAULT_EVENT_ID = 51005       # Pink The Rink XV
DEFAULT_DIVISION_ID = 170739   # U18 C

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://events.teamsnap.com',
    'Referer': 'https://events.teamsnap.com/',
}


def _get(endpoint: str, timeout: int = 10) -> Any:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('data')
    except urllib.error.HTTPError as e:
        log.error(f"TeamSnap HTTP {e.code} for {url}: {e.read().decode('utf-8', errors='ignore')}")
        raise
    except Exception as e:
        log.error(f"TeamSnap error for {url}: {e}")
        raise


def fetch_event(event_id: int = DEFAULT_EVENT_ID) -> Dict[str, Any]:
    """Fetch event metadata."""
    return _get(f"events/{event_id}") or {}


def fetch_divisions(event_id: int = DEFAULT_EVENT_ID) -> List[Dict[str, Any]]:
    """Fetch all divisions in the event."""
    return _get(f"events/{event_id}/divisions") or []


def fetch_venues(event_id: int = DEFAULT_EVENT_ID) -> Dict[int, Dict[str, Any]]:
    """Fetch venues and subvenues map keyed by venueId."""
    raw = _get(f"events/{event_id}/venues") or []
    return {v['id']: v for v in raw}


def fetch_matches(event_id: int = DEFAULT_EVENT_ID, division_id: Optional[int] = DEFAULT_DIVISION_ID) -> List[Dict[str, Any]]:
    """Fetch matches, optionally filtered by division."""
    matches = _get(f"events/{event_id}/matches") or []
    if division_id is not None:
        return [m for m in matches if m.get('divisionId') == division_id]
    return matches


def fetch_schedule_items(event_id: int = DEFAULT_EVENT_ID, division_id: int = DEFAULT_DIVISION_ID) -> List[Dict[str, Any]]:
    """Fetch schedule items for a division (requires ?lastUpdate=0)."""
    return _get(f"events/{event_id}/divisions/{division_id}/schedule-items?lastUpdate=0") or []


def fetch_match_participants(event_id: int = DEFAULT_EVENT_ID, division_id: int = DEFAULT_DIVISION_ID) -> List[Dict[str, Any]]:
    """Fetch match participants and seed rules for a division."""
    return _get(f"events/{event_id}/divisions/{division_id}/match-participants?lastUpdate=0") or []


def get_division_games(event_id: int = DEFAULT_EVENT_ID, division_id: int = DEFAULT_DIVISION_ID) -> List[Dict[str, Any]]:
    """Return unified, chronologically sorted list of all division games."""
    venues_map = fetch_venues(event_id)
    matches_map = {m['id']: m for m in fetch_matches(event_id, division_id)}
    sched_items = fetch_schedule_items(event_id, division_id)

    games = []
    for s in sched_items:
        mid = s.get('matchId')
        m = matches_map.get(mid, {})
        vid = s.get('venueId')
        svid = s.get('subvenueId')
        v = venues_map.get(vid, {})
        vname = v.get('name', 'Unknown Arena')
        sv_name = ''
        for sv in v.get('subvenues', []):
            if sv.get('id') == svid:
                sv_name = sv.get('name', '')
                break
        arena_full = f"{vname} - {sv_name}" if sv_name else vname

        games.append({
            'match_id': mid,
            'schedule_item_id': s.get('id'),
            'date': s.get('startDate'),
            'start_time': s.get('startTime'),
            'end_time': s.get('endTime'),
            'arena': arena_full,
            'venue_id': vid,
            'subvenue_id': svid,
            'game_type': m.get('gameType'),
            'game_number': m.get('gameNumber'),
            'round_number': m.get('roundNumber'),
            'name': m.get('name'),
            'completed': m.get('completed', False),
            'home_score': m.get('homeScore'),
            'away_score': m.get('awayScore'),
        })

    games.sort(key=lambda g: (g['date'] or '', g['start_time'] or ''))
    return games


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(f"Connecting to TeamSnap Tournaments (Event {DEFAULT_EVENT_ID}, Division {DEFAULT_DIVISION_ID})...")
    games = get_division_games()
    print(f"\nRetrieved {len(games)} games from TeamSnap:")
    for g in games:
        print(f"  {g['date']} {g['start_time']} | {g['arena']} | Type: {g['game_type']} | Name: {g['name'] or 'Round ' + str(g['round_number'])}")
