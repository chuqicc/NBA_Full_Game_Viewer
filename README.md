# NBA Full Game Viewer

An interactive desktop tool for watching full NBA games from SportVU player-tracking data — smooth animation, scrubable timeline, and real-time roster context.

> Python ≥ 3.8 · matplotlib ≥ 3.4 · MIT license

---

## Preview

**Q1 — Tip-off**

![Q1 tip-off](assets/screenshot_q1.png)

**Mid-game**

![Mid-game](assets/screenshot_midgame.png)

---

## Quick Start

```bash
pip install matplotlib numpy
python full_game_main.py --path data/0021500485.json
```

---

## Controls

| Input | Action |
|---|---|
| Timeline slider | Scrub to any moment |
| **Q1 / Q2 / Q3 / Q4** | Jump to quarter start |
| **▶ / ⏸** | Play / Pause |
| **0.5× 1× 2× 4×** | Playback speed |
| `Space` | Play / Pause |
| `← →` | Step ±1 second |
| `1 2 3 4` | Jump to quarter |
| `?` | Toggle shortcut overlay |

---

## Data Format

Expects standard **SportVU** tracking JSON (2015-16 NBA season).
Two example games are included in `data/`.

---

## Acknowledgements

Court image and original animation structure inspired by
[linouk23/NBA-Player-Movements](https://github.com/linouk23/NBA-Player-Movements)
