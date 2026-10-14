# Rinkside 🏒

**Real-Time Tournament Companion & Clinch Engine for Minor Hockey Teams**

Live site: [dpauls.github.io/rinkside](https://dpauls.github.io/rinkside/)

Rinkside provides parents, coaches, and distant family with a real-time tournament command center that tracks live game scores, calculates tiebreakers, solves mathematical clinches, and provides live stream links right to their phones and smart watches.

---

## Key Features

- 🔮 **Clinch Watch**: Exhaustive mathematical scenario solver ($3^n$ game outcomes) that proves locked seeds, playoff berths, and eliminations without premature placement.
- ⚡ **Rink Mode (Keep Awake)**: HTML5 Screen Wake Lock keeps phone screens lit while propped against the arena glass.
- ⌚ **Smart Watch Notifications**: Silent, vibrating score change notifications that mirror directly to parents' watches without arena noise.
- 🔴 **Live Stream Integration**: Attach YouTube livestream URLs on the fly as broadcasts go live right before game time.
- 🎯 **Bench Coach Matrix**: Live margin-of-victory and tiebreaker analysis to inform coaching strategies on the bench.
- 🤖 **Coach's Corner**: Tactical pre-game talking points and classic Don Cherry commentary.
- 🏛️ **Polymorphic Tournament Engine**: Pluggable tournament structures (`TwoPoolTop2AdvanceStructure`, `MultiPoolCrossoverStructure`) and configurable tiebreaker registries (`OWHA`, `PTR`, custom).
- ☁️ **Decoupled State**: Clean state management via local files or cloud object storage (S3/R2) without polluting git commit history.

---

## Architecture & Technical Deep-Dive 📐

For a comprehensive explanation of Rinkside's design patterns, hybrid cloud architecture, tiebreaker engines, and clinch calculation mathematics, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

Key architecture highlights include:
- **Hybrid Cloud Topology**: Autonomous Always-Free Oracle Cloud VM daemon + Edge CDN GitHub Pages static client.
- **Pluggable Tiebreaker System**: Strategy pattern supporting non-reverting tiebreaker chains, raw GD vs ratio formulas, and custom tournament rules.
- **Deterministic Scenario Solver**: $3^n$ outcome space traversal with mathematical clinch proofs and GD margin threshold calculus.
- **Bench Coach Tactical Calculus**: Real-time goalie-pull risk vs reward indicator and score-margin matrix.
- **Hierarchical AI Commentary**: Two-tier Gemini 3 Flash reasoning (sub-second quips vs deep thought tournament digests) with spend safety circuit breaker.
- **Mobile-First Live Rink UX**: Screen Wake Lock "Rink Mode", multi-pool pill navigation, and smart watch haptic alerts.

---

## Quick Start

### 1. Requirements & Setup
```bash
# Clone the repository
git clone https://github.com/dpauls/rinkside.git
cd rinkside

# Python 3.10+ required
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Polling Daemon
```bash
# Live daemon polling RAMP API:
python3 src/daemon.py

# Or run one-shot update:
python3 src/daemon.py --once
```

### 3. Attach a YouTube Live Stream
When a parent begins streaming from the rink:
```bash
# Attach live stream to a game
python3 src/stream.py 2074770 https://youtu.be/abc123xyz

# View active streams
python3 src/stream.py --list

# Remove a stream
python3 src/stream.py --remove 2074770
```

### 4. Run Test Suite
```bash
PYTHONPATH=. python3 -m unittest discover -s test -p "test_*.py"
```

---

## Project Structure

```
├── data/
│   ├── tournament.json            # Active tournament config & cache
│   ├── tournaments/
│   │   ├── pink_the_rink_2026.json # Pink the Rink XV (U18C #1777)
│   │   └── provincials_2026.json   # OWHA Provincials 2026
│   └── streams.json               # Dynamic YouTube live stream mappings
├── docs/                          # Static Frontend (GitHub Pages)
│   ├── index.html                 # Main dashboard with Clinch Watch & Rink Mode
│   ├── bench.html                 # Bench Coach matrix
│   ├── scenarios.html             # Detailed scenario explorer
│   └── data/
│       └── state.json             # Live tournament state payload
├── src/
│   ├── analyze.py                 # Clinch engine & scenario enumeration
│   ├── structure.py               # Tournament format abstractions
│   ├── tiebreakers/               # Pluggable tiebreaker rule registry
│   ├── bench.py                   # Bench differential matrix generator
│   ├── scraper.py                 # RAMP API integration
│   ├── daemon.py                  # Polling daemon & event detector
│   ├── stream.py                  # Live stream manager CLI
│   └── storage.py                 # S3/R2/Local storage adapter
└── test/                          # Unit & integration test suite
```

---

## Deployment (GitHub Pages)

The frontend is completely static and located in the `/docs` directory. It fetches `docs/data/state.json` (or cloud storage in production) to render real-time updates client-side.
