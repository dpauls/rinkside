---
name: tournament-onboarding
description: >-
  Standardized procedure to onboard a new tournament into Rinkside.
  Use when adding a new tournament (e.g. PTR, Provincials, Rochester, etc.) from an official
  rules document, RAMP league/season IDs, and host site details.
---

# Tournament Onboarding Skill

This skill guides the end-to-end setup and validation of a new tournament in the Rinkside platform.

## When to Use
- Adding a new tournament config in `data/tournaments/<tournament_id>.json`.
- Extracting official game lengths, overtime rules, shootouts, and tiebreakers from an official rules PDF or URL.
- Discovering RAMP REST API parameters (`season_id`, `division_id`, `league_id`).

---

## Workflow Steps

### Step 1: Extract Rules and Tiebreakers
Given an official tournament rules PDF (e.g. hosted on the tournament website or saved locally):

1. Run the rules extractor tool:
   ```bash
   python3 scripts/extract_rules.py --pdf "<pdf_url_or_path>" --out /tmp/rules_spec.json
   ```
2. Verify the extracted tiebreaker sequence against the official text:
   - **Wins** (`wins`)
   - **Head-to-head**: Check whether H2H applies to multi-team ties or strictly 2-way ties (`head_to_head_two_way_only`).
   - **Goal Differential**: Check if the tournament specifies raw differential $GF - GA$ (`goal_diff`) or OWHA percentage $GF / (GF + GA)$.
   - **Fewest Goals Against** (`fewest_goals_against`).
   - **Fewest Penalty Minutes** (`fewest_pim`).
   - **Reversion Policy**: If rules say *"Once a rule has been used, it cannot be used again"*, set `"allow_reversion": false`.

### Step 2: Extract Host Visual Identity & Banner
1. Inspect the tournament host website (or run curl / web inspection) to locate the official font and colors:
   - Example heading font: `'Oswald', sans-serif` (Google Fonts).
   - Banner accent color: e.g. `#ff99cc` (Pink the Rink).
2. Download or link the tournament logo into `docs/images/<tournament_logo>.png`.

### Step 3: Discover Official RAMP REST API IDs
Find the RAMP schedule portal for the tournament division (e.g., on `owha.on.ca` or host association portal):
1. In browser DevTools Network tab, inspect the AJAX call to `api/v1/games` or `api/v1/standings`.
2. Extract:
   - `league_id` (e.g. `3065`)
   - `season_id` (e.g. `14974`)
   - `division_id` (e.g. `25410`)
   - `base_url` (e.g. `https://www.owha.on.ca`)

### Step 4: Create Tournament Configuration
Create `data/tournaments/<tournament_id>.json` incorporating:
1. `"tournament"` metadata (`name`, `location`, `dates`, `banner_text`, `banner_color`, `banner_font`, `banner_font_url`, `logo`).
2. `"ramp"` parameters.
3. `"teams"` mapping (team numbers and pool assignments).
4. `"structure"` definition (e.g. `two_pool_top2_advance` or `eight_pool_top1_advance`).
5. `"tiebreakers"` configuration.
6. `"game_rules"` format details.

### Step 5: Test & Validate
1. Run local generator:
   ```bash
   PYTHONPATH=. python3 src/generate.py --data data/tournaments/<tournament_id>.json
   ```
2. Run test suite:
   ```bash
   PYTHONPATH=. python3 -m unittest discover -s test -p "test_*.py"
   ```
3. Test daemon polling with `--once --skip-push`:
   ```bash
   PYTHONPATH=. python3 src/daemon.py --tournament data/tournaments/<tournament_id>.json --once --skip-push
   ```
