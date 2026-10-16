"""Tournament structure coordinator defining pools, advancement counts, and playoff bracket pairings."""
from typing import Dict, List, Optional, Any


class TournamentStructure:
    """Base class for tournament structures."""

    def __init__(self, config: dict):
        self.config = config.get('structure', {})
        self.pools_config = self.config.get('pools', config.get('pools', {}))

    def get_pools(self) -> Dict[str, dict]:
        """Return pool configurations {pool_id: {'teams': [...], 'advance_count': N}}."""
        return self.pools_config

    def get_advance_count(self, pool_id: str) -> int:
        """Return number of teams advancing from the specified pool."""
        pool = self.pools_config.get(pool_id, {})
        return pool.get('advance_count', 1)

    def get_pool_teams(self, pool_id: str) -> List[str]:
        """Return list of team IDs in the pool."""
        pool = self.pools_config.get(pool_id, {})
        return pool.get('teams', [])

    def get_advancement_round_name(self, pool_id: str) -> str:
        """Return the human-readable round name for advancing teams (e.g. 'Playoffs')."""
        return "Playoffs"

    def get_playoff_round_name(self, pool_id: str) -> str:
        """Return the target playoff round (e.g. 'Semifinals', 'Quarterfinals')."""
        return "Playoffs"

    def format_clinch_alert(self, pool_id: str, team_name: str, status_type: str) -> Optional[str]:
        """Format human-readable clinch announcement based on tournament structure."""
        if status_type == 'first':
            return f"{team_name} has mathematically CLINCHED 1st place in Pool {pool_id}!"
        elif status_type == 'berth':
            round_name = self.get_advancement_round_name(pool_id)
            return f"{team_name} has mathematically CLINCHED a {round_name} in Pool {pool_id}!"
        elif status_type == 'eliminated':
            return f"{team_name} is mathematically eliminated from playoff contention."
        return None

    def resolve_playoff_bracket(
        self,
        pool_rankings: Dict[str, Any],
        teams_data: Dict[str, dict],
        official_games: Optional[List[dict]] = None
    ) -> Dict[str, Any]:
        """Resolve playoff matchups using pool rankings."""
        raise NotImplementedError


class TwoPoolTop2AdvanceStructure(TournamentStructure):
    """Two pools (e.g. Pool A and Pool B), top 2 advance to Semifinals, 3rd/4th to Consolation.
    
    Format:
      - Semi 1: 1st in Pool A vs 2nd in Pool B
      - Semi 2: 1st in Pool B vs 2nd in Pool A
      - Consolation 1: 3rd in Pool A vs 3rd in Pool B
      - Consolation 2: 4th in Pool A vs 4th in Pool B
      - Championship Final: Winner Semi 1 vs Winner Semi 2
    """

    def get_advancement_round_name(self, pool_id: str) -> str:
        return "Semifinal berth"

    def get_playoff_round_name(self, pool_id: str) -> str:
        return "Semifinals"

    def format_clinch_alert(self, pool_id: str, team_name: str, status_type: str) -> Optional[str]:
        if status_type == 'first':
            return f"{team_name} has mathematically CLINCHED 1st place in Pool {pool_id} (Semifinal seed secured)!"
        elif status_type == 'berth':
            return f"{team_name} has mathematically CLINCHED a Semifinal berth in Pool {pool_id}!"
        elif status_type == 'eliminated':
            return f"{team_name} is mathematically eliminated from Semifinal contention."
        return None

    def resolve_playoff_bracket(
        self,
        pool_rankings: Dict[str, Any],
        teams_data: Dict[str, dict],
        official_games: Optional[List[dict]] = None
    ) -> Dict[str, Any]:
        def get_team_info(pool_id: str, rank_idx: int) -> dict:
            p_data = pool_rankings.get(pool_id, {})
            if isinstance(p_data, dict):
                clinched = p_data.get('clinched_positions', {})
                is_final = p_data.get('is_final', False)
                if rank_idx in clinched:
                    tid = clinched[rank_idx]
                    team_obj = teams_data.get(tid, {})
                    name = team_obj.get('name', tid)
                    return {
                        'id': tid,
                        'name': name,
                        'placeholder': f"{rank_idx+1} in Pool {pool_id}",
                        'resolved': True,
                        'status': 'final' if is_final else 'clinched'
                    }
            elif isinstance(p_data, list):
                if rank_idx < len(p_data):
                    tid = p_data[rank_idx]
                    team_obj = teams_data.get(tid, {})
                    name = team_obj.get('name', tid)
                    return {
                        'id': tid,
                        'name': name,
                        'placeholder': f"{rank_idx+1} in Pool {pool_id}",
                        'resolved': True,
                        'status': 'clinched'
                    }
            return {
                'id': None,
                'name': f"{rank_idx+1} in Pool {pool_id}",
                'placeholder': f"{rank_idx+1} in Pool {pool_id}",
                'resolved': False,
                'status': 'tbd'
            }

        def build_matchup(label: str, home_info: dict, away_info: dict) -> dict:
            if home_info['status'] == 'final' and away_info['status'] == 'final':
                m_status = 'final'
            elif home_info['resolved'] and away_info['resolved']:
                m_status = 'clinched'
            elif home_info['resolved'] or away_info['resolved']:
                m_status = 'partial'
            else:
                m_status = 'tbd'

            return {
                'game': label,
                'home': home_info,
                'away': away_info,
                'status': m_status,
                'is_official': False
            }

        semis = [
            build_matchup('Semi 1', get_team_info('A', 0), get_team_info('B', 1)),
            build_matchup('Semi 2', get_team_info('B', 0), get_team_info('A', 1)),
        ]

        consolations = [
            build_matchup('Consolation 1', get_team_info('A', 2), get_team_info('B', 2)),
            build_matchup('Consolation 2', get_team_info('A', 3), get_team_info('B', 3)),
        ]

        final = {
            'game': 'Championship Final',
            'home': {'id': None, 'name': 'Winner Semi 1', 'placeholder': 'Winner Semi 1', 'resolved': False, 'status': 'tbd'},
            'away': {'id': None, 'name': 'Winner Semi 2', 'placeholder': 'Winner Semi 2', 'resolved': False, 'status': 'tbd'},
            'status': 'tbd',
            'is_official': False
        }

        # Dynamically resolve Championship Final from official playoff games
        if official_games:
            for g in official_games:
                gid = g.get('game_id') or g.get('GID')
                hs = g.get('home_score')
                as_ = g.get('away_score')
                is_final = (g.get('status') == 'final') or g.get('completed', False)

                # Semi 1: 2074858
                if gid == 2074858 or ('Semi 1' in str(g.get('notes', ''))):
                    if is_final and hs is not None and as_ is not None and hs != as_:
                        win_id = g['home'] if hs > as_ else g['away']
                        team_obj = teams_data.get(win_id, {})
                        final['home'] = {
                            'id': win_id,
                            'name': team_obj.get('name', win_id),
                            'placeholder': 'Winner Semi 1',
                            'resolved': True,
                            'status': 'final'
                        }
                # Semi 2: 2074861
                elif gid == 2074861 or ('Semi 2' in str(g.get('notes', ''))):
                    if is_final and hs is not None and as_ is not None and hs != as_:
                        win_id = g['home'] if hs > as_ else g['away']
                        team_obj = teams_data.get(win_id, {})
                        final['away'] = {
                            'id': win_id,
                            'name': team_obj.get('name', win_id),
                            'placeholder': 'Winner Semi 2',
                            'resolved': True,
                            'status': 'final'
                        }
                # Championship Final: 2074871
                elif gid == 2074871 or ('Final' in str(g.get('notes', '')) and 'Semi' not in str(g.get('notes', ''))):
                    if is_final and hs is not None and as_ is not None and hs != as_:
                        win_id = g['home'] if hs > as_ else g['away']
                        team_obj = teams_data.get(win_id, {})
                        final['status'] = 'final'
                        final['winner'] = {'id': win_id, 'name': team_obj.get('name', win_id)}
                    elif g.get('status') in ('in_progress', 'live'):
                        final['status'] = 'in_progress'

            if final['home']['resolved'] and final['away']['resolved'] and final['status'] == 'tbd':
                final['status'] = 'clinched'

        return {
            'type': 'two_pool_top2_advance',
            'semis': semis,
            'consolations': consolations,
            'final': final,
        }


class MultiPoolCrossoverStructure(TournamentStructure):
    """Multi-pool format (e.g. Provincials with 8 pools of 4), top 1 advances to Quarterfinals."""

    def get_advancement_round_name(self, pool_id: str) -> str:
        return "Quarterfinal berth"

    def get_playoff_round_name(self, pool_id: str) -> str:
        return "Quarterfinals"

    def format_clinch_alert(self, pool_id: str, team_name: str, status_type: str) -> Optional[str]:
        if status_type == 'first' or status_type == 'berth':
            return f"{team_name} has mathematically CLINCHED Pool {pool_id} and advances to the Quarterfinals!"
        elif status_type == 'eliminated':
            return f"{team_name} is mathematically eliminated from Quarterfinal contention."
        return None

    def resolve_playoff_bracket(
        self,
        pool_rankings: Dict[str, Any],
        teams_data: Dict[str, dict],
        official_games: Optional[List[dict]] = None
    ) -> Dict[str, Any]:
        def get_pool_winner_info(pool_id: str) -> dict:
            p_data = pool_rankings.get(pool_id, {})
            placeholder = f"Winner Pool {pool_id}"
            if isinstance(p_data, dict):
                clinched = p_data.get('clinched_positions', {})
                is_final = p_data.get('is_final', False)
                if 0 in clinched:
                    tid = clinched[0]
                    team_obj = teams_data.get(tid, {})
                    return {
                        'id': tid,
                        'name': team_obj.get('name', tid),
                        'placeholder': placeholder,
                        'resolved': True,
                        'status': 'final' if is_final else 'clinched'
                    }
            elif isinstance(p_data, list):
                if len(p_data) > 0:
                    tid = p_data[0]
                    team_obj = teams_data.get(tid, {})
                    return {
                        'id': tid,
                        'name': team_obj.get('name', tid),
                        'placeholder': placeholder,
                        'resolved': True,
                        'status': 'clinched'
                    }
            return {
                'id': None,
                'name': placeholder,
                'placeholder': placeholder,
                'resolved': False,
                'status': 'tbd'
            }

        playoffs_cfg = self.config.get('playoffs', {})
        qf_list = []
        for qf in playoffs_cfg.get('quarterfinals', []):
            home_pool = qf.get('home_pool')
            away_pool = qf.get('away_pool')
            h_info = get_pool_winner_info(home_pool)
            a_info = get_pool_winner_info(away_pool)

            if h_info['status'] == 'final' and a_info['status'] == 'final':
                m_status = 'final'
            elif h_info['resolved'] and a_info['resolved']:
                m_status = 'clinched'
            elif h_info['resolved'] or a_info['resolved']:
                m_status = 'partial'
            else:
                m_status = 'tbd'

            qf_list.append({
                'game': qf.get('name', 'Quarterfinal'),
                'home': h_info,
                'away': a_info,
                'status': m_status,
                'is_official': False
            })

        return {
            'type': 'multi_pool_crossover',
            'quarterfinals': qf_list,
        }


def build_structure_from_config(tournament_data: dict) -> TournamentStructure:
    """Factory helper to construct TournamentStructure from tournament config dict."""
    struct_cfg = tournament_data.get('structure', {})
    struct_type = struct_cfg.get('type')
    if struct_type == 'two_pool_top2_advance':
        return TwoPoolTop2AdvanceStructure(tournament_data)
    elif struct_type == 'multi_pool_crossover':
        return MultiPoolCrossoverStructure(tournament_data)
    
    # Auto-detect if not specified: if 2 pools and advance_count == 2
    pools = struct_cfg.get('pools', tournament_data.get('pools', {}))
    if len(pools) == 2 and any(p.get('advance_count') == 2 for p in pools.values()):
        return TwoPoolTop2AdvanceStructure(tournament_data)

    return MultiPoolCrossoverStructure(tournament_data)
