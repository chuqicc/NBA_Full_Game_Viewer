"""
NBA Full Game Tracking Viewer
------------------------------
Usage:
    # From the visualization_tool root directory:
    python full_game_viewer/full_game_main.py --path 0021500485.json

    # Or with an absolute path:
    python full_game_viewer/full_game_main.py --path /some/path/game.json

Controls:
    ▶ Play / ⏸ Pause  — toggle animation
    Q1 / Q2 / Q3 / Q4 — jump to quarter start
    Speed radio        — 0.5x / 1x / 2x / 4x playback speed
    Timeline slider    — drag to any moment in the game
    Space              — play / pause
    ← / →              — step back / forward ~1 second (25 frames)
    1 / 2 / 3 / 4      — jump to that quarter
"""

import argparse
import os
import sys

# Ensure parent directory is on path (for Moment, Player, Ball, Team, Constant)
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))
sys.path.insert(0, _here)

from GameTimeline import GameTimeline
from FullGameViewer import FullGameViewer


def resolve_path(raw_path):
    """Accept absolute paths or paths relative to cwd or to the parent folder."""
    if os.path.isabs(raw_path) and os.path.exists(raw_path):
        return raw_path
    # Relative to current working directory
    cwd_path = os.path.join(os.getcwd(), raw_path)
    if os.path.exists(cwd_path):
        return cwd_path
    # Relative to visualization_tool root (one level up from this script)
    parent_path = os.path.join(os.path.dirname(_here), raw_path)
    if os.path.exists(parent_path):
        return parent_path
    return raw_path   # Return as-is; will raise a clear error on open()


def main():
    parser = argparse.ArgumentParser(
        description='NBA Full Game Tracking Viewer — watch the entire game interactively.'
    )
    parser.add_argument(
        '--path', type=str, required=True,
        help='Path to the game JSON file (e.g. 0021500485.json)'
    )
    args = parser.parse_args()

    json_path = resolve_path(args.path)

    if not os.path.exists(json_path):
        print(f"Error: file not found — {json_path}")
        sys.exit(1)

    # Load timeline
    timeline = GameTimeline(json_path)
    timeline.load()

    # Launch viewer
    viewer = FullGameViewer(timeline)
    viewer.show()


if __name__ == '__main__':
    main()
