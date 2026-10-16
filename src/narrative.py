#!/usr/bin/env python3
"""
Tournament narrative and event commentary generation using Gemini 3.8 Flash.

Provides hierarchical context distillation:
1. High-thinking tournament stakes digest (generated when games go final).
2. Low-thinking, sub-second live event commentary and goal quips.
3. Authentic Coach's Corner Don Cherry commentary for minor girls' hockey.
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MAX_TOKENS = 600
LLM_LOG_PATH = Path(__file__).parent.parent / 'logs' / 'llm_interactions.log'


def _call(prompt, max_tokens=MAX_TOKENS, label='unknown', thinking_level=None, temperature=None):
    """Call LLM via pluggable LLMRouter with thinking level and temperature controls."""
    try:
        from llm import get_router
    except ImportError:
        from src.llm import get_router

    router = get_router()
    return router.generate(
        prompt=prompt,
        purpose=label,
        max_tokens=max_tokens,
        thinking_level=thinking_level,
        temperature=temperature
    )


def _log_interaction(label, phase, content):
    """Log an LLM interaction to the log file."""
    try:
        LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        separator = '=' * 80
        with open(LLM_LOG_PATH, 'a') as f:
            f.write(f'\n{separator}\n')
            f.write(f'[{timestamp}] {label} — {phase}\n')
            f.write(f'{separator}\n')
            f.write(content)
            f.write(f'\n{separator}\n\n')
    except Exception:
        pass


def _rank_str(r):
    """Format ranking for prompt: '#18' or '' if no ranking."""
    rank = r.get('ranking')
    return f' (ranked #{rank} provincially)' if rank else ''


def _format_date(iso_date):
    """Convert ISO date to readable format like 'Fri Oct 16, 2:15 PM'."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime('%a %b %d, %I:%M %p').replace(' 0', ' ')
    except (ValueError, TypeError):
        return str(iso_date)


def generate_tournament_digest(standings, scenarios, our_pool='B', advance_count=2,
                               our_team_name='Kanata Rangers', tournament_name='Pink the Rink XV - U18C',
                               advancement_round='playoffs'):
    """High-thinking distillation of the raw standings and scenarios matrix.
    
    Produces a 2-3 bullet point baseline stakes digest that feeds into fast live goal quips.
    """
    standings_str = '\n'.join(
        f"  {r['name']}: {r['w']}W-{r['l']}L-{r['t']}T, {r['pts']}pts (GF={r['gf']} GA={r['ga']} GD={r.get('gd', r['gf']-r['ga'])})"
        + (' ← US' if r.get('is_us') else '')
        for r in standings
    )
    rem_games = scenarios.get('remaining_games', 0) if scenarios else 0
    sc_total = scenarios.get('total', 0) if scenarios else 0
    our_adv = scenarios.get('our_count', 0) if scenarios else 0

    adv_target = f"the {advancement_round}" if advancement_round != 'playoffs' else "the playoffs"
    prompt = f"""You are the senior tournament analyst for {our_team_name} at {tournament_name}.
We play in Pool {our_pool}, where the top {advance_count} team(s) advance to {adv_target}.

Current Standings in Pool {our_pool}:
{standings_str}

Scenario Engine Status:
{rem_games} pool game(s) remaining ({sc_total} mathematical outcome combinations).
{our_team_name} advances in {our_adv} of {sc_total} scenarios.

Synthesize a concise, 2-3 bullet point TOURNAMENT STAKES DIGEST.
Focus on:
1. Exactly what {our_team_name} needs to advance or lock the #1 seed (points, win/tie, or margin).
2. Key rival games in our pool and what concurrent outcomes help or hurt us.
3. Crucial tiebreaker factors (goal differential, head-to-head) that parents must watch closely.

Keep it strictly factual, direct, and under 90 words total."""

    return _call(prompt, max_tokens=220, label="tournament_digest", thinking_level="high", temperature=1.0)


def generate_overall_narrative(standings, scenarios, our_team_name='Kanata Rangers', our_pool='B',
                                qf_pool_standings=None, completed_games=None, upcoming_games=None,
                                live_games=None, tournament_name='Pink the Rink XV - U18C'):
    """Generate 2-3 paragraph tournament overview for the main page."""
    standings_str = '\n'.join(
        f"  {r['name']}: {r['w']}W-{r['l']}L-{r['t']}T, {r['pts']}pts (GF={r['gf']} GA={r['ga']})"
        + (' ← US' if r.get('is_us') else '')
        for r in standings
    )

    completed_str = '\n'.join(
        f"  FINAL: {g['home_name']} {g['home_score']}-{g['away_score']} {g['away_name']}"
        for g in (completed_games or [])
    ) or '  No games completed yet.'

    live_str = '\n'.join(
        f"  IN PROGRESS: {g['home_name']} {g.get('home_score',0)}-{g.get('away_score',0)} {g['away_name']}"
        for g in (live_games or [])
    ) or ''

    upcoming_str = '\n'.join(
        f"  SCHEDULED: {g['home_name']} vs {g['away_name']} — {_format_date(g['date'])}"
        for g in (upcoming_games or [])[:4]
    ) or '  No upcoming games.'

    our_next = None
    for g in (upcoming_games or []):
        if g.get('home') == 'KAN' or g.get('away') == 'KAN' or \
           'Kanata' in g.get('home_name', '') or 'Kanata' in g.get('away_name', ''):
            our_next = g
            break
    our_next_str = ''
    if our_next:
        opp = our_next['away_name'] if 'Kanata' in our_next.get('home_name', '') else our_next['home_name']
        our_next_str = f'\nOUR NEXT GAME: {our_team_name} vs {opp} — {_format_date(our_next["date"])}'

    qf_str = '\n'.join(
        f"  {r['name']}: {r['w']}W-{r['l']}L-{r['t']}T, {r['pts']}pts"
        for r in (qf_pool_standings or [])
    ) or '  No data yet.'

    if scenarios and scenarios.get('total', 0) > 1:
        sc_summary = (f"Out of {scenarios['total']} possible combinations of remaining game outcomes, "
                      f"{our_team_name} advances in {scenarios['our_count']} of them.")
    elif scenarios and scenarios.get('total') == 1:
        sc_summary = "All pool games are complete."
    else:
        sc_summary = "No scenario data available."

    prompt = f"""You are the tournament analyst for the {our_team_name} at {tournament_name}.

=== FACTS (use these exactly, do NOT invent schedule details) ===
SCORING RULES: Win = 2 points, Tie = 1 point each, Loss = 0 points. Hockey, NOT soccer.

Pool {our_pool} standings:
{standings_str}

Games in progress right now:
{live_str or '  None'}

Completed games:
{completed_str}

Upcoming scheduled games:
{upcoming_str}
{our_next_str}

Scenario analysis: {sc_summary}

Other Pool Watch:
{qf_str}
=== END FACTS ===

TONE RULES:
- NEVER call any game "winnable" or "easy". Every team earned their spot.
- NEVER say "X% chance" or "probability". Scenario counts describe possible paths, not likelihood.
- VOICE: Always use "we", "us", "our" for {our_team_name}. Never "them" or "they" for our team.

Write a structured update using **bold section headings** for hockey parents on phones:
**Where We Stand** 1-2 sentences on our current position.
**Our Next Game** 1-2 sentences about our upcoming game (ONLY reference game from OUR NEXT GAME).
**Around the Pool** 1-2 sentences on concurrent games.

Keep it crisp, under 140 words total."""

    return _call(prompt, label='overall_narrative', thinking_level="high")


def generate_overall_narrative_with_context(standings, scenarios, our_team_name='Kanata Rangers', our_pool='B',
                                             qf_pool_standings=None, completed_games=None, upcoming_games=None,
                                             live_games=None, recent_changes=None, rooting_guide=None,
                                             prev_narrative=None, tournament_name='Pink the Rink XV - U18C'):
    """Generate narrative incorporating memory of previous update and concurrent rooting context."""
    standings_str = '\n'.join(
        f"  {r['name']}: {r['w']}W-{r['l']}L-{r['t']}T, {r['pts']}pts (GF={r['gf']} GA={r['ga']})"
        + (' ← US' if r.get('is_us') else '')
        for r in standings
    )

    completed_str = '\n'.join(
        f"  FINAL: {g['home_name']} {g['home_score']}-{g['away_score']} {g['away_name']}"
        for g in (completed_games or [])
    ) or '  No games completed yet.'

    live_str = '\n'.join(
        f"  IN PROGRESS: {g['home_name']} {g.get('home_score',0)}-{g.get('away_score',0)} {g['away_name']}"
        for g in (live_games or [])
    ) or ''

    upcoming_str = '\n'.join(
        f"  SCHEDULED: {g['home_name']} vs {g['away_name']} — {_format_date(g['date'])}"
        for g in (upcoming_games or [])[:4]
    ) or '  No upcoming games.'

    our_next = None
    for g in (upcoming_games or []):
        if g.get('home') == 'KAN' or g.get('away') == 'KAN' or \
           'Kanata' in g.get('home_name', '') or 'Kanata' in g.get('away_name', ''):
            our_next = g
            break
    our_next_str = ''
    if our_next:
        opp = our_next['away_name'] if 'Kanata' in our_next.get('home_name', '') else our_next['home_name']
        our_next_str = f'\nOUR NEXT GAME: {our_team_name} vs {opp} — {_format_date(our_next["date"])}'

    qf_str = '\n'.join(
        f"  {r['name']}: {r['w']}W-{r['l']}L-{r['t']}T, {r['pts']}pts"
        for r in (qf_pool_standings or [])
    ) or '  No data yet.'

    if scenarios and scenarios.get('total', 0) > 1:
        sc_summary = (f"Out of {scenarios['total']} possible combinations of remaining game outcomes, "
                      f"{our_team_name} advances in {scenarios['our_count']} of them.")
    elif scenarios and scenarios.get('total') == 1:
        sc_summary = "All pool games are complete."
    else:
        sc_summary = "No scenario data available."

    changes_str = ''
    if recent_changes:
        changes_str = '\nWhat just happened:\n' + '\n'.join(f'  - {c}' for c in recent_changes)

    rooting_str = ''
    if rooting_guide:
        rooting_str = '\nRooting Guide for concurrent games:\n' + '\n'.join(
            f"  - {r['home_name']} vs {r['away_name']}: {r['reasoning']}" for r in rooting_guide
        )

    context_str = ''
    if prev_narrative:
        context_str = f"""
Here is what you wrote in your PREVIOUS update:
---
{prev_narrative}
---
Build on this. Update the story without repeating yourself.
"""

    prompt = f"""You are the tournament analyst for {our_team_name} at {tournament_name}.
{context_str}

=== FACTS ===
Pool {our_pool} standings:
{standings_str}

Games in progress:
{live_str or '  None'}

Completed games:
{completed_str}

Upcoming games:
{upcoming_str}
{our_next_str}

Scenario analysis: {sc_summary}
{changes_str}
{rooting_str}

Other Pool Watch:
{qf_str}
=== END FACTS ===

VOICE: Always use "we", "us", "our" for {our_team_name}.
Write a structured update using **bold section headings**:
**Where We Stand** 1-2 sentences on current position.
**Our Next Game** 1-2 sentences (ONLY from OUR NEXT GAME above).
**Around the Pool** 1-2 sentences on concurrent action.

Keep it under 140 words."""

    return _call(prompt, label="narrative_with_context", thinking_level="high")


def generate_in_game_comment(game, our_team, our_team_name, scenarios_if_holds,
                              scenarios_if_reversed, total_scenarios, tournament_name='Pink the Rink XV - U18C'):
    """Generate 1 sentence about a game in progress that our team is not playing in."""
    home_name = game.get('home_name', game['home'])
    away_name = game.get('away_name', game['away'])
    hs = game.get('home_score', 0)
    as_ = game.get('away_score', 0)

    prompt = f"""A pool game is in progress at {tournament_name}. {our_team_name} is NOT playing in this game.

Current score: {home_name} {hs} - {as_} {away_name}
If this score holds: {our_team_name} advances in {scenarios_if_holds} of {total_scenarios} remaining scenarios.
If the other team comes back to win: {our_team_name} advances in {scenarios_if_reversed} of {total_scenarios} scenarios.

Write exactly 1 fun, brief sentence about who we're rooting for and why. Reference the scenario numbers."""

    return _call(prompt, max_tokens=100, label="in_game_comment", thinking_level="low")


def generate_correction_comment(game, old_score, new_score, our_team_name):
    """Generate a note about a post-game score correction."""
    home_name = game.get('home_name', game['home'])
    away_name = game.get('away_name', game['away'])

    return (f"Score correction: {home_name} vs {away_name} changed from "
            f"{old_score[0]}-{old_score[1]} to {new_score[0]}-{new_score[1]}. "
            f"Analysis has been updated.")


def evaluate_narrative(current_narrative, changes, prev_scenarios, curr_scenarios,
                       our_team, our_team_name):
    """Decide whether to regenerate the main page narrative. Returns True/False."""
    if not current_narrative:
        return True

    for c in changes:
        if c['type'] == 'game_final':
            log.info('Narrative eval: REGENERATE (game final)')
            return True
        if c['type'] == 'correction':
            log.info('Narrative eval: REGENERATE (score correction)')
            return True

    log.info('Narrative eval: KEEP (no finals or corrections)')
    return False


def generate_game_final_comment(game, standings, prev_scenarios, curr_scenarios,
                                 our_team, our_team_name, our_pool, teams=None,
                                 tournament_name='Pink the Rink XV - U18C',
                                 game_events=None):
    """Generate 1-2 sentence commentary when a game finishes."""
    is_our_game = (game['home'] == our_team or game['away'] == our_team)
    game_pool = game.get('pool')

    standings_str = ', '.join(
        f"{r['name'].split('#')[0].strip()} {r['pts']}pts (GD={r.get('gd', r['gf']-r['ga'])})"
        for r in (standings or [])
    )

    home_name = game.get('home_name', game['home'])
    away_name = game.get('away_name', game['away'])

    arc_str = ''
    if game_events:
        fmt_events = [
            f"{e.get('headline', '')} — {e.get('detail') or ''}" if isinstance(e, dict) else str(e)
            for e in game_events[-6:]
        ]
        arc_str = '\nIn-game scoring progression & earlier commentary:\n' + '\n'.join(f'  - {fe}' for fe in fmt_events) + '\n'

    if game_pool is None:
        gid = game.get('game_id') or game.get('gid')
        round_label = "Championship Final" if gid == 2074871 else ("Semifinal" if gid in (2074858, 2074861) else "Consolation Game")
        prompt = f"""A {round_label} game just finished at {tournament_name}.

Result: {home_name} {game['home_score']} - {game['away_score']} {away_name} ({round_label})
{'This was OUR game!' if is_our_game else f'We ({our_team_name}) were not playing in this game.'}
{arc_str}
Write 1-2 energetic sentences using "we/us/our" when referring to {our_team_name}. Highlight the outcome of this {round_label} and what it means for the championship bracket!"""
    elif game_pool != our_pool:
        prompt = f"""A cross-pool game in Pool {game_pool} just finished at {tournament_name}.

Result: {home_name} {game['home_score']} - {game['away_score']} {away_name} (Pool {game_pool})
Note: {our_team_name} is in Pool {our_pool}, so this Pool {game_pool} game does NOT affect our Pool {our_pool} advancement scenarios, but it shapes Pool {game_pool} standings for potential Semifinal crossover matchups (Pool A 1st plays Pool B 2nd; Pool B 1st plays Pool A 2nd).
Updated Pool {game_pool} standings: {standings_str}

Write 1-2 concise sentences using "we/us/our" for {our_team_name}, noting the Pool {game_pool} result and how it shapes the Pool {game_pool} race for Semifinal crossover seeding. Do NOT mention Pool {our_pool} scenario counts."""
    else:
        prev_count = prev_scenarios.get('our_count', '?') if prev_scenarios else '?'
        prev_total = prev_scenarios.get('total', '?') if prev_scenarios else '?'
        curr_count = curr_scenarios.get('our_count', '?') if curr_scenarios else '?'
        curr_total = curr_scenarios.get('total', '?') if curr_scenarios else '?'

        clinch_note = ''
        if curr_scenarios and curr_count == curr_total and curr_total > 0:
            clinch_note = f'\n{our_team_name} has CLINCHED a Semifinal spot in Pool {our_pool}!'
        elif curr_scenarios and curr_count == 0 and curr_total > 0:
            clinch_note = f'\n{our_team_name} has been ELIMINATED from Semifinal contention in Pool {our_pool}.'

        prompt = f"""A Pool {our_pool} game just finished at {tournament_name}.

Result: {home_name} {game['home_score']} - {game['away_score']} {away_name} (Pool {our_pool})
{'This was OUR game.' if is_our_game else 'We were not playing in this game.'}
{arc_str}
Updated Pool {our_pool} standings: {standings_str}
Scenario impact: Out of {curr_total} remaining outcome combinations, {our_team_name} advances in {curr_count} (was {prev_count} of {prev_total}).
{clinch_note}

Write 1-2 sentences using "we/us/our" when referring to {our_team_name}. If in-game progression is shown above, tie the final result to how the game unfolded (e.g. holding off a push, rallying back, pulling away late), and state the concrete playoff implications."""

    return _call(prompt, max_tokens=180, label="game_final_comment", thinking_level="high")


def generate_event_impact(event_type, home_name, away_name, home_score, away_score,
                          is_our_game, our_team_name, scenarios_if_holds=None,
                          total_scenarios=None, tournament_context=None,
                          in_progress_games=None, round_robin_phase="mid",
                          tournament_name="Pink the Rink XV - U18C",
                          recent_events=None, game_pool=None, our_pool="B"):
    """Generate a 1-sentence impact comment for any live game event.
    
    Uses low thinking level for fast, sub-second delivery to parents on mobile.
    """
    score_str = f"{home_name} {home_score}-{away_score} {away_name}"

    active_games_str = "None"
    if in_progress_games:
        active_games_str = "; ".join(
            f"{g.get('home_name', g.get('home'))} {g.get('home_score',0)}-{g.get('away_score',0)} {g.get('away_name', g.get('away'))}"
            for g in in_progress_games
        )

    ctx_block = ""
    if tournament_context:
        digest = tournament_context.get('digest') or tournament_context.get('standings_summary', '')
        ctx_block = f"""=== BASELINE TOURNAMENT STAKES ===
{digest}
=== END BASELINE ===\n"""

    story_block = ""
    if recent_events:
        fmt_evs = [
            f"{ev.get('headline', '')} — {ev.get('detail') or ''}" if isinstance(ev, dict) else str(ev)
            for ev in recent_events[-6:]
        ]
        story_lines = "\n".join(f"  - {line}" for line in fmt_evs)
        story_block = f"""=== RECENT COMMENTARY STORY ARC ===
{story_lines}
=== END STORY ARC ===\n"""

    math_impact = ""
    if scenarios_if_holds is not None and total_scenarios:
        math_impact = f"\nMathematical projection: If this score holds as final, we advance in {scenarios_if_holds} of {total_scenarios} scenarios."

    phase_guide = (
        "EARLY PHASE (Game 1): Keep commentary focused on game action and setting the tournament tone. Do NOT make premature clinch claims."
        if round_robin_phase == "early"
        else "MID/LATE PHASE (Games 2 & 3): Make astute observations on goal differential, lead changes, and semifinal berths."
    )

    pool_desc = 'OUR GAME' if is_our_game else ('Playoff Game' if game_pool is None else (f'Pool {game_pool} Game' if game_pool != our_pool else f'Pool {our_pool} Game'))

    prompt = f"""You are the live rinkside commentator for {our_team_name} at {tournament_name}.
{ctx_block}{story_block}=== CURRENT LIVE STATE ===
This game: {score_str} ({pool_desc})
Concurrent games in progress: {active_games_str}{math_impact}

=== EVENT JUST OCCURRED ===
Event: {event_type.upper().replace('_', ' ')}: {score_str}

=== INSTRUCTIONS ===
Write EXACTLY 1 punchy, informative sentence for parents reading live on their phones.
- Use "we", "us", "our" for {our_team_name}.
- {phase_guide}
- CONTINUITY: If recent commentary is provided above, connect this moment to the unfolding game story (e.g. answering right back, erasing an early deficit, trading goals, or building a cushion) and do NOT repeat phrases or sentence structures from earlier events.
- CALIBRATION:
  * High-impact (lead change, breaking a deadlock, extending cushion): highlight what it means for our pool standing.
  * Routine (insurance goal, minor score): deliver energetic, fun hockey commentary.
- NEVER say "guarantees" or "clinched" unless mathematically locked.
- NEVER cite probability percentages."""

    return _call(prompt, max_tokens=100, label=f"event_impact_{event_type}", thinking_level="low", temperature=1.0)


def generate_pregame_talking_points(our_team_name, opponent_name, opponent_ranking,
                                     our_recent_results, our_pim, standings,
                                     scenarios_summary, what_at_stake,
                                     tournament_name='Pink the Rink XV - U18C',
                                     opponent_results=None, common_opponents=None,
                                     prev_talking_points=None,
                                     our_ranking='?', rankings_confidence=0):
    """Generate pre-game talking points for the team meeting."""
    results_str = '\n'.join(f'  - {r}' for r in (our_recent_results or [])) or '  No games played yet.'
    opp_results_str = '\n'.join(f'  - {r}' for r in (opponent_results or [])) or '  No games played yet.'
    common_str = '\n'.join(f'  - {c}' for c in (common_opponents or [])) or '  None yet.'

    is_opener = not our_recent_results and not opponent_results

    has_both_rankings = (
        our_ranking and str(our_ranking) != '?' and
        opponent_ranking and str(opponent_ranking) != '?'
    )
    conf = int(rankings_confidence or 0)
    if not has_both_rankings or conf <= 0:
        rankings_guide = (
            "Provincial rankings: Not available or too early in the season to be meaningful. "
            "Do NOT mention provincial rankings or seedings (and never confuse the division 'U18C' with a #18 ranking)."
        )
    elif conf <= 25:
        rankings_guide = (
            f"Provincial rankings ({our_team_name}: #{our_ranking}, {opponent_name}: #{opponent_ranking} — "
            f"Early-season confidence: {conf}/100): Very few games have been played so far this season. "
            f"You may mention rankings only as a very light footnote, and emphasize that on-ice play matters far more right now."
        )
    elif conf <= 65:
        rankings_guide = (
            f"Provincial rankings ({our_team_name}: #{our_ranking}, {opponent_name}: #{opponent_ranking} — "
            f"Confidence: {conf}/100): Moderate-confidence rankings; use as a rough gauge of relative strength alongside tournament results."
        )
    else:
        rankings_guide = (
            f"Provincial rankings ({our_team_name}: #{our_ranking}, {opponent_name}: #{opponent_ranking} — "
            f"High confidence: {conf}/100): Established rankings — factor this relative strength directly into how we prepare for {opponent_name}."
        )

    prev_block = ''
    if prev_talking_points:
        prev_block = f"""
=== PREVIOUS GAME TALKING POINTS (for story continuity) ===
{prev_talking_points}
=== END PREVIOUS ===
Build naturally on our weekend progression without repeating the same phrases.
"""

    if is_opener:
        instructions = f"""Since this is the TOURNAMENT OPENER and neither team has played a game yet, be creative and engaging!
Write 3 short talking points using **bold headings** followed by 1-2 sentences each:
**Mindset** — Channel opening-game energy, shake off the highway travel legs to Etobicoke, and set the tone on the very first shift.
**The Opponent** — Offer a creative, insightful angle on {opponent_name} (for example, if both teams are from the Ottawa region like Kanata and Nepean, note the fun Ottawa-area rivalry playing out on Toronto ice; what to expect in a tight opening matchup; never call any game "easy" or "winnable").
**What We Need** — Explain the tournament format ({what_at_stake}), why banking 2 points and a positive goal differential in Game 1 sets up the whole weekend, and what the coach's locker-room message should be."""
    else:
        instructions = f"""Write 3 short, insightful talking points using **bold headings** followed by 1-2 sentences each:
**Mindset** — Address our most recent result directly (bounce back from a tough result or build on momentum) and frame the locker-room focus.
**The Opponent** — Provide genuine scouting insight on {opponent_name} based on their tournament history above: who they've played, how our results against common opponents compare, what their scoring/defensive numbers reveal about how good they are, and how we match up. Never say "easy" or "winnable".
**What We Need** — Concrete points, tiebreaker/goal-differential awareness, and the coach's closing message for what it takes to advance ({what_at_stake})."""

    prompt = f"""You are helping the coaching staff of {our_team_name}
prepare talking points for a pre-game team meeting at {tournament_name}.
{prev_block}
=== FACTS ===
Next opponent: {opponent_name}
{rankings_guide}
Our tournament results so far (most recent first):
{results_str}

{opponent_name}'s tournament results so far:
{opp_results_str}

Common opponents comparison in this tournament:
{common_str}

Current pool standings:
{standings}

Scenario outlook: {scenarios_summary}
Tournament advancement stakes: {what_at_stake}
=== END FACTS ===

{instructions}

Practical, motivating, and age-appropriate for minor girls hockey. Keep under 160 words total."""

    return _call(prompt, max_tokens=320, label="pregame_talking_points", thinking_level="high")


def generate_don_cherry(context, our_team_name='Kanata Rangers', tournament_name='Pink the Rink XV - U18C',
                        prev_don_cherry=None):
    """Generate authentic Don Cherry commentary for Coach's Corner."""
    prev_block = ""
    if prev_don_cherry:
        prev_block = f"""
=== YOUR PREVIOUS COACH'S CORNER SEGMENT ===
{prev_don_cherry}
=== END PREVIOUS SEGMENT ===
CONTINUITY RULE: Build on the ongoing tournament narrative where natural, but respect whether the game is upcoming, in-progress, or completed. MUST use a DIFFERENT opening phrase than your previous segment above!
"""

    prompt = f"""You are Don Cherry from Coach's Corner on Hockey Night in Canada, commenting on the {our_team_name} girls minor hockey team (Under-18 C division) competing at {tournament_name}.
{prev_block}
=== CURRENT SITUATION ===
{context}
=== END SITUATION ===

YOUR PERSONA & VOICE:
- You are enthusiastic, grandfatherly, fiercely proud, and passionate about Canadian minor girls hockey.
- Deliver rapid-fire, staccato commentary with physical energy (thinking out loud, desk-slapping enthusiasm).
- Champion core hockey virtues: heart, shot blocking, backchecking, unselfish team passing, protecting the goalie, and humble celebrations.
- If they won: fired up, ecstatic, celebrating work ethic and team passing ("THAT is how you play hockey!").
- If they lost: warm, grandfatherly encouragement, reminding them to dust themselves off and stay positive ("Don't hang your heads for one second!").
- If high-stakes / nail-biter: urgent, pulse-pounding excitement ("Holy jumpin', my heart is going ninety miles an hour!").
- If clinched / advancing: ecstatic validation of hard work ("I told ya! Look at that board right there!").
- If eliminated: deeply proud reflection on their season, teamwork, and making parents and coaches proud.

STYLE RULES:
1. Open with an iconic phrase: "Now listen...", "I tell ya right now...", "Boy oh boy oh boy...", "Now look at this right here...", or "You kids out there watching this...".
2. Use punchy, telegraphic clauses separated by hyphens or exclamation marks ("Boom-boom-boom, tape-to-tape, in the net!").
3. Use occasional CAPITAL letters for vocal acoustic punches (e.g., "THAT", "BOOM", "HOLY JUMPIN'", "KABOOM").
4. Incorporate authentic Cherry expressions: "Beauty!", "Double thumbs up!", "Atta girl!", "Worked their socks off!", "Between the pipes", "Tender".
5. NEVER mention team rankings or seedings (and never confuse Under-18 C with a #18 ranking), and NEVER use clichés like "rankings don't score goals" or dry statistical jargon.
6. NEVER be mean, sarcastic, or negative toward kids. You are their biggest cheerleader.
7. LENGTH CONSTRAINT: Exactly 2 to 3 punchy sentences (maximum 75 words total). Must fit cleanly in a mobile card.
8. TEMPORAL ACCURACY: When commenting on an upcoming game, speak in anticipation of the upcoming matchup (e.g. 'heading into this one', 'looking ahead', 'when the puck drops'). NEVER describe an upcoming game as currently being played, tied, or in progress!

Write Don Cherry's commentary:"""

    return _call(prompt, max_tokens=140, label="don_cherry", thinking_level="high", temperature=1.0)


def generate_tiebreaker_health(our_team_name, standings_summary, yellow_count,
                                green_count, red_count, total, tiebreaker_state,
                                tournament_name='Pink the Rink XV - U18C'):
    """Generate LLM analysis of the tiebreaker health for yellow scenarios."""
    if yellow_count == 0:
        return None

    prompt = f"""You are analyzing tiebreaker scenarios for {our_team_name} at {tournament_name}.

SCORING: Win = 2 points, Tie = 1 point each, Loss = 0 points.

=== SCENARIO BREAKDOWN ===
Total scenarios: {total}
Green (we advance deterministically on points/H2H): {green_count}
Yellow (depends on goal differential / goals for / goals against): {yellow_count}
Red (eliminated deterministically): {red_count}

=== CURRENT STANDINGS ===
{standings_summary}

=== TIEBREAKER METRICS ===
{tiebreaker_state}

Write 2-3 concise sentences explaining our position in the {yellow_count} score-dependent (Yellow) scenarios. Highlight our current Goal Differential (GD) and Goals Against (GA) compared to our pool rivals, and what margin we need to watch for. Use "we/us/our" for {our_team_name}. Keep under 85 words."""

    return _call(prompt, max_tokens=180, label="tiebreaker_health", thinking_level="high")


def generate_bench_commentary(our_team_name, our_score, their_score, opp_name,
                               projections, other_game_info, standings_summary,
                               tiebreaker_state, tournament_name='Pink the Rink XV - U18C'):
    """Generate LLM commentary for yellow bench situations."""
    other_str = 'No concurrent game.'
    if other_game_info:
        o = other_game_info
        other_str = (f"Concurrent game: {o['home']} {o['home_score']}-{o['away_score']} {o['away']} "
                    f"({'tied' if o['home_score'] == o['away_score'] else str(o['margin']) + '-goal lead'})")

    prompt = f"""You are the tactical analyst for {our_team_name} at {tournament_name}.
The coach is on the bench with 2 minutes remaining, trailing by 1 goal ({our_score}-{their_score} against {opp_name}).
The goalie-pull decision is borderline:
{tiebreaker_state}
{other_str}

Provide 2 sentences of direct, objective advice on whether the risk of pulling the goalie is mathematically justified."""

    return _call(prompt, max_tokens=150, label="bench_advice", thinking_level="high", temperature=1.0)
