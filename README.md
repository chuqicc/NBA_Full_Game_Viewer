# NBA Full Game Viewer

An interactive desktop tool for visualising full NBA games from SportVU player-tracking JSON data.
Watch every moment of a game with smooth animation, a scrubable timeline, and real-time roster context.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![matplotlib](https://img.shields.io/badge/matplotlib-3.4%2B-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

| Feature | Details |
|---|---|
| **Full-game playback** | All 4 quarters merged into one continuous ~80,000-frame timeline |
| **Scrubable timeline** | Drag the slider to any moment; Q1–Q4 boundary markers shown |
| **Quarter jump buttons** | One click to jump to Q1 / Q2 / Q3 / Q4; active quarter is highlighted |
| **Variable speed** | 0.5× · 1× · 2× · 4× button group with active-state indicator |
| **Scoreboard strip** | Full-width header with team names, team colours, live game clock & shot clock |
| **Shot clock urgency** | Shot clock turns **red** when ≤ 5 seconds remain |
| **On-court roster** | Both full rosters displayed; the 5 players currently on court are highlighted (●) in white/bold — bench is dimmed |
| **Home / away distinction** | Home = solid circle · Away = solid circle + inner white ring |
| **Ball elevation** | Ball size scales with real z-height — visibly rises during shots and long passes |
| **Ball trail** | 8-frame fading trail shows recent ball movement direction |
| **Dark-team visibility** | Very dark team colours (BKN, WAS, IND …) are auto-brightened for readability |
| **Keyboard shortcuts** | Press `?` on screen to toggle the shortcut overlay |

---

## Preview

```
┌── HOU  Houston Rockets ──── Q2  08:42  Shot: 14.3 ──── Golden State Warriors  GSW ──┐
│                                                                                       │
│  [Q1] [Q2] [Q3] [Q4]        ⏸  Pause        [0.5×] [1×] [2×] [4×]  [?]             │
│ ┌───────────────────────────────────────────────────────────────┐  ┌───────────────┐ │
│ │                                                               │  │  HOU   │  GSW │ │
│ │     ●  ●  ●  ●  ●     ○     ●  ●  ●  ●  ●                    │  │● #1 T… │● #30…│ │
│ │                                                               │  │● #12 P…│● #11…│ │
│ └───────────────────────────────────────────────────────────────┘  │  #13 J…│  #23…│ │
│  ├──────────────────●────────────── Q1│Q2│Q3│Q4 ───────────────┤  │  ...   │  ... │ │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Requirements

```
Python     >= 3.8
matplotlib >= 3.4
numpy      >= 1.21   (pulled in by matplotlib)
```

```bash
pip install matplotlib numpy
```

No additional frameworks needed — fully self-contained.

---

## Data Format

Expects the standard **SportVU** tracking JSON from the 2015-16 NBA season dataset.

```
match.json
├── gameid
├── gamedate
└── events [ ]
    ├── eventId
    ├── home    { teamid, name, abbreviation,
    │             players [ { firstname, lastname, playerid, jersey, position } ] }
    ├── visitor { … }
    └── moments [ ]
        └── [ quarter,  timestamp_ms,  game_clock,  shot_clock,  null,
               [ [ teamid, entityid, x, y, z ],   ← ball   (index 0)
                 [ teamid, playerid, x, y, z ],   ← players 1–10
                 … ] ]
```

> **Court coordinates** — 94 ft × 50 ft.  `x` runs along the long axis, `y` across the short axis.
> **`z`** for the ball is its height in feet above the floor (used to scale ball size).
> **`game_clock`** counts **down** from 720 s (12 min) toward 0 each quarter.

---

## Usage

```bash
# From the project root (or any directory):
python full_game_viewer/full_game_main.py --path 0021500485.json

# Absolute path also works:
python full_game_viewer/full_game_main.py --path /data/nba/0021500001.json
```

On launch the viewer prints a loading summary then opens the interactive window:

```
Loading: 0021500485.json
Found 470 events. Deduplicating moments...
Loaded 79,302 unique frames (from 199,056 raw) across 4 quarters.
  Q1: frames 0       – 19,979   (19,980 frames)
  Q2: frames 19,980  – 40,405   (20,426 frames)
  Q3: frames 40,406  – 60,026   (19,621 frames)
  Q4: frames 60,027  – 79,301   (19,275 frames)
```

---

## Controls

### Mouse / Buttons

| Control | Action |
|---|---|
| Timeline slider | Drag to scrub to any frame in the game |
| **Q1 / Q2 / Q3 / Q4** | Jump to that quarter's first frame (active quarter stays highlighted) |
| **▶ Play / ⏸ Pause** | Toggle animation |
| **0.5× 1× 2× 4×** | Change playback speed (active speed stays highlighted) |
| **?** | Show / hide keyboard shortcut overlay on court |

### Keyboard

| Key | Action |
|---|---|
| `Space` | Play / Pause |
| `←` / `→` | Step back / forward ~1 second (25 frames) |
| `1` / `2` / `3` / `4` | Jump to start of that quarter |

---

## Project Structure

```
full_game_viewer/
├── full_game_main.py   # CLI entry point
├── GameTimeline.py     # Data layer — loads JSON, deduplicates & sorts all frames
├── FullGameViewer.py   # Interactive viewer — matplotlib figure, widgets, render loop
└── README.md
```

### Architecture

```
sportvu.json
    │
    ▼
GameTimeline.load()
    • reads all 470 events
    • deduplicates overlapping moments by (quarter, timestamp_ms)
    • sorts into one chronological list  →  ~79,302 unique frames
    • indexes quarter start frames
    │
    ▼
FullGameViewer
    • builds matplotlib figure with explicit axis placement
    • drives animation via fig.canvas.new_timer (variable speed, pause-safe)
    • _render(frame_idx) updates only patch centres + text — no figure rebuild
```

---

## Acknowledgements

- Court image and original single-event animation structure inspired by
  [linouk23/NBA-Player-Movements](https://github.com/linouk23/NBA-Player-Movements)

---

## License

MIT — free to use and modify for research and personal projects.
