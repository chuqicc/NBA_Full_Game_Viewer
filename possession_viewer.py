"""
PossessionViewer — visualize a single NBA possession from CSV tracking data.

Usage
-----
    python possession_viewer.py
    python possession_viewer.py --path data/0021500001_1_5.csv
    python possession_viewer.py --path data/my_poss.csv --players data/player_data.csv

Controls
--------
    ▶ / ⏸      Play / Pause
    0.5× 1× 2× 4×  Playback speed
    Timeline slider  Scrub to any frame
    Space            Play / Pause
    ← →              Step ±1 second (~25 frames)
    ?                Toggle shortcut overlay
"""

import argparse
import os
import sys
from collections import deque

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.widgets as mwidgets
from matplotlib.patches import Circle, Rectangle

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

from Constant import Constant
from Team import Team


# ── Data loading ──────────────────────────────────────────────────────────────

def load_possession(csv_path, player_csv_path):
    """
    Load possession CSV + player_data CSV.

    Returns
    -------
    frames : list[dict]
        One dict per tracking row with keys:
        quarter, quarter_clock, shot_clock,
        ball_x, ball_y, ball_z, players (list of dicts)
    player_dict : dict  {player_id -> (name, jersey_str, team_id)}
    """
    poss_df   = pd.read_csv(csv_path)
    player_df = pd.read_csv(player_csv_path)

    # Build player lookup from player_data.csv
    player_dict = {}
    for _, row in player_df.iterrows():
        pid = int(row['player_id'])
        jersey = str(int(row['jersey_number'])) if pd.notna(row['jersey_number']) else '?'
        player_dict[pid] = (str(row['player_name']), jersey, int(row['team_id']))

    # Parse every row into a frame
    frames = []
    for _, row in poss_df.iterrows():
        players = []
        for i in range(1, 11):
            pid = row.get(f'player_{i}_id')
            tid = row.get(f'player_{i}_team_id')
            px  = row.get(f'player_{i}_x')
            py  = row.get(f'player_{i}_y')
            if pd.notna(pid) and pd.notna(px) and pd.notna(py):
                players.append({
                    'id':      int(pid),
                    'team_id': int(float(tid)),
                    'x':       float(px),
                    'y':       float(py),
                })

        sc_raw = row.get('shot_clock', float('nan'))
        frames.append({
            'quarter':       int(row['quarter']),
            'quarter_clock': float(row['quarter_clock']) if pd.notna(row['quarter_clock']) else None,
            'shot_clock':    float(sc_raw) if pd.notna(sc_raw) else None,
            'ball_x':        float(row['ball_x']),
            'ball_y':        float(row['ball_y']),
            'ball_z':        float(row['ball_radius']),
            'players':       players,
        })

    return frames, player_dict


def _get_two_teams(frames):
    """Return the two team IDs present in the possession (sorted)."""
    seen = set()
    for f in frames:
        for p in f['players']:
            seen.add(p['team_id'])
    teams = sorted(seen)
    t1 = teams[0] if len(teams) > 0 else None
    t2 = teams[1] if len(teams) > 1 else None
    return t1, t2


# ── Viewer ────────────────────────────────────────────────────────────────────

class PossessionViewer:

    # Playback
    SPEED_LABELS     = ['0.5×', '1×', '2×', '4×']
    SPEED_VALUES     = [0.5, 1.0, 2.0, 4.0]
    BASE_INTERVAL_MS = 40          # ms per frame @ 1× (25 FPS)
    STEP_FRAMES      = 25          # arrow-key step (~1 s)
    TRAIL_LEN        = 8

    # Sizing
    PLAYER_R    = Constant.PLAYER_CIRCLE_SIZE
    BALL_BASE_R = Constant.PLAYER_CIRCLE_SIZE * 0.55
    BALL_MAX_R  = Constant.PLAYER_CIRCLE_SIZE * 1.10

    # Palette  (same dark theme as FullGameViewer)
    BG_DARK        = '#0f0f1a'
    BG_WIDGET      = '#1a2744'
    BG_SCORE       = '#0d0d1a'
    BTN_NORMAL     = '#1e3a6e'
    BTN_HOVER      = '#2e5499'
    BTN_PLAY       = '#1b5e20'
    BTN_PLAY_HV    = '#2e7d32'
    BTN_SPD_ACTIVE = '#c8860a'
    SLIDER_CLR     = '#4caf50'
    TEXT_WHITE     = 'white'
    TEXT_DIM       = '#aaaacc'
    SHOT_URGENT    = '#ff4444'

    def __init__(self, frames, player_dict, title='Possession Viewer', filename=''):
        self.frames      = frames
        self.player_dict = player_dict
        self.n_frames    = len(frames)

        self._current_frame   = 0
        self._is_playing      = False
        self._speed           = 1.0
        self._updating_slider = False
        self._timer           = None
        self._ball_trail      = deque(maxlen=self.TRAIL_LEN)

        # Identify the two teams; team2 gets inner-ring (visitor marker)
        self._team1, self._team2 = _get_two_teams(frames)
        self._filename = filename

        # Pre-compute luminance-safe team colours once
        self._team_colors = {
            tid: self._ensure_visible_color(info[0])
            for tid, info in Team.color_dict.items()
        }

        self._build_figure(title)
        self._draw_court()
        self._create_patches()
        self._create_scoreboard()
        self._create_widgets()
        self._create_info_panel()
        self._render(0)
        self._connect_keyboard()

    # =================================================================
    # Figure layout
    # =================================================================

    def _build_figure(self, title):
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(14, 8))
        self.fig.patch.set_facecolor(self.BG_DARK)
        try:
            self.fig.canvas.manager.set_window_title(title)
        except Exception:
            pass

        # Scoreboard strip (top)
        self.score_ax = self.fig.add_axes([0.00, 0.93, 1.00, 0.07])
        self.score_ax.axis('off')
        self.score_ax.set_facecolor(self.BG_SCORE)

        # Court (left 70 %)
        self.court_ax = self.fig.add_axes([0.02, 0.16, 0.68, 0.69])
        self.court_ax.set_facecolor(self.BG_DARK)

        # Info panel (right 26 %)
        self.info_ax = self.fig.add_axes([0.72, 0.16, 0.26, 0.69])
        self.info_ax.axis('off')
        self.info_ax.add_patch(
            Rectangle((0, 0), 1, 1,
                       transform=self.info_ax.transAxes,
                       facecolor='#16213e', zorder=0)
        )

        # Timeline slider (matches court width)
        self.ax_slider = self.fig.add_axes([0.02, 0.07, 0.68, 0.04])
        self.ax_slider.set_facecolor(self.BG_WIDGET)

        # Control bar row (between court top and scoreboard bottom)
        BTN_Y, BTN_H = 0.87, 0.05

        # Play / Pause
        self.ax_play = self.fig.add_axes([0.02, BTN_Y, 0.14, BTN_H])

        # Speed buttons
        self.ax_spd = [
            self.fig.add_axes([0.175 + i * 0.046, BTN_Y, 0.042, BTN_H])
            for i in range(4)
        ]

        # Help (?) button
        self.ax_help = self.fig.add_axes([0.367, BTN_Y, 0.028, BTN_H])

    def _draw_court(self):
        court_path = os.path.join(_here, 'courta.png')
        court = plt.imread(court_path)
        self.court_ax.imshow(
            court, zorder=0,
            extent=[Constant.X_MIN,
                    Constant.X_MAX - Constant.DIFF,
                    Constant.Y_MAX,
                    Constant.Y_MIN]
        )
        self.court_ax.set_xlim(Constant.X_MIN, Constant.X_MAX)
        self.court_ax.set_ylim(Constant.Y_MIN, Constant.Y_MAX)
        self.court_ax.axis('off')

    # =================================================================
    # Patches
    # =================================================================

    def _create_patches(self):
        self.player_shadows = [
            Circle((-100, -100), self.PLAYER_R * 1.35,
                   color='black', alpha=0.25, zorder=2, linewidth=0)
            for _ in range(10)
        ]
        self.player_circles = [
            Circle((-100, -100), self.PLAYER_R,
                   facecolor='gray', zorder=3,
                   edgecolor='white', linewidth=1.8)
            for _ in range(10)
        ]
        # Away (team2) gets an inner white ring to distinguish home vs away
        self.player_inner_ring = [
            Circle((-100, -100), self.PLAYER_R * 0.48,
                   facecolor='none', edgecolor='white',
                   linewidth=1.2, alpha=0, zorder=4)
            for _ in range(10)
        ]
        for shadow, circle, ring in zip(
                self.player_shadows, self.player_circles, self.player_inner_ring):
            self.court_ax.add_patch(shadow)
            self.court_ax.add_patch(circle)
            self.court_ax.add_patch(ring)

        self.annotations = [
            self.court_ax.text(
                -100, -100, '',
                color='white', ha='center', va='center',
                fontweight='bold', fontsize=9, zorder=6,
                path_effects=[
                    pe.withStroke(linewidth=2.5, foreground='black'),
                    pe.Normal()
                ]
            )
            for _ in range(10)
        ]

        # Ball trail
        self.trail_circles = [
            Circle((-100, -100),
                   self.BALL_BASE_R * (0.25 + 0.55 * i / self.TRAIL_LEN),
                   facecolor='#F47F20', alpha=0, zorder=1, linewidth=0)
            for i in range(self.TRAIL_LEN)
        ]
        for tc in self.trail_circles:
            self.court_ax.add_patch(tc)

        # Ball
        self.ball_circle = Circle((-100, -100), self.BALL_BASE_R,
                                  facecolor='#F47F20', zorder=4,
                                  edgecolor='#7B3A00', linewidth=1.5)
        self.ball_shine  = Circle((-100, -100), self.BALL_BASE_R * 0.28,
                                  color='white', alpha=0.55,
                                  zorder=5, linewidth=0)
        self.court_ax.add_patch(self.ball_circle)
        self.court_ax.add_patch(self.ball_shine)

        # Keyboard overlay
        self.help_overlay = self.court_ax.text(
            47, 25,
            '   Keyboard Shortcuts   \n'
            '─────────────────────────\n'
            '  Space      Play / Pause\n'
            '  ← →        Step ± 1 sec\n',
            color='white', ha='center', va='center',
            fontsize=11, fontfamily='monospace',
            zorder=10, visible=False,
            bbox=dict(boxstyle='round,pad=0.9',
                      facecolor='#0a0a1a', alpha=0.95,
                      edgecolor='#4a7fd4', linewidth=1.5)
        )

    # =================================================================
    # Scoreboard strip
    # =================================================================

    def _create_scoreboard(self):
        t1_raw   = Team.color_dict.get(self._team1, ('#4fc3f7', 'T1'))
        t2_raw   = Team.color_dict.get(self._team2, ('#ef9a9a', 'T2'))
        t1_color = self._ensure_visible_color(t1_raw[0])
        t2_color = self._ensure_visible_color(t2_raw[0])
        t1_abbr  = t1_raw[1]
        t2_abbr  = t2_raw[1]

        ax = self.score_ax
        ax.add_patch(Rectangle((0, 0), 0.022, 1,
                               transform=ax.transAxes,
                               facecolor=t1_color, zorder=1))
        ax.add_patch(Rectangle((0.978, 0), 0.022, 1,
                               transform=ax.transAxes,
                               facecolor=t2_color, zorder=1))

        ax.text(0.032, 0.5, t1_abbr, transform=ax.transAxes,
                color=t1_color, ha='left', va='center',
                fontsize=13, fontweight='bold')
        ax.text(0.968, 0.5, t2_abbr, transform=ax.transAxes,
                color=t2_color, ha='right', va='center',
                fontsize=13, fontweight='bold')
        ax.plot([0.5, 0.5], [0.1, 0.9], color='#334466',
                linewidth=0.8, transform=ax.transAxes)

        # Possession filename label (top-right corner)
        ax.text(0.99, 0.92, self._filename,
                transform=ax.transAxes,
                color=self.TEXT_DIM, ha='right', va='top',
                fontsize=7.5, fontfamily='monospace')

        self.scoreboard_time = ax.text(
            0.5, 0.70, 'Q1  12:00',
            transform=ax.transAxes,
            color='white', ha='center', va='center',
            fontsize=13, fontweight='bold'
        )
        self.scoreboard_shot = ax.text(
            0.5, 0.22, 'Shot:  --.-',
            transform=ax.transAxes,
            color=self.TEXT_DIM, ha='center', va='center',
            fontsize=9
        )

    # =================================================================
    # Widgets
    # =================================================================

    def _create_widgets(self):
        total = max(self.n_frames - 1, 1)

        self.slider = mwidgets.Slider(
            self.ax_slider, '', 0, total,
            valinit=0, valstep=1, color=self.SLIDER_CLR
        )
        self.slider.label.set_visible(False)

        self.slider_time_text = self.ax_slider.text(
            0.5, -0.65, '',
            transform=self.ax_slider.transAxes,
            color=self.TEXT_DIM, fontsize=8,
            ha='center', va='top', clip_on=False
        )

        self.play_btn = mwidgets.Button(
            self.ax_play, '▶  Play',
            color=self.BTN_PLAY, hovercolor=self.BTN_PLAY_HV
        )
        self.play_btn.label.set_color(self.TEXT_WHITE)
        self.play_btn.label.set_fontsize(11)
        self.play_btn.on_clicked(self._on_play_pause)

        self.speed_buttons = []
        for i, (label, val) in enumerate(zip(self.SPEED_LABELS, self.SPEED_VALUES)):
            active = abs(val - self._speed) < 0.01
            btn = mwidgets.Button(
                self.ax_spd[i], label,
                color=self.BTN_SPD_ACTIVE if active else self.BTN_NORMAL,
                hovercolor=self.BTN_HOVER
            )
            btn.label.set_color(self.TEXT_WHITE)
            btn.label.set_fontsize(9)
            btn.on_clicked(self._make_speed_callback(val))
            self.speed_buttons.append(btn)

        self.help_btn = mwidgets.Button(
            self.ax_help, '?',
            color=self.BTN_NORMAL, hovercolor=self.BTN_HOVER
        )
        self.help_btn.label.set_color(self.TEXT_WHITE)
        self.help_btn.label.set_fontsize(10)
        self.help_btn.on_clicked(self._toggle_help)

        self.slider.on_changed(self._on_slider_changed)

    # =================================================================
    # Info panel — on/off court roster
    # =================================================================

    def _create_info_panel(self):
        """Build the roster panel: two columns (team1 left, team2 right)."""
        # Collect all unique players from the possession, grouped by team
        seen = {}  # player_id -> (name, jersey, team_id)
        for f in self.frames:
            for p in f['players']:
                pid = p['id']
                if pid not in seen:
                    info = self.player_dict.get(pid, ('Unknown', '?', p['team_id']))
                    seen[pid] = (info[0], info[1], p['team_id'])

        t1_roster = [(name, jersey, pid)
                     for pid, (name, jersey, tid) in seen.items()
                     if tid == self._team1]
        t2_roster = [(name, jersey, pid)
                     for pid, (name, jersey, tid) in seen.items()
                     if tid == self._team2]

        # Sort by jersey number for stable ordering
        t1_roster.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 99)
        t2_roster.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 99)

        self._t1_roster = t1_roster
        self._t2_roster = t2_roster
        self._last_on_court_ids = frozenset()

        t1_color = self._ensure_visible_color(
            Team.color_dict.get(self._team1, ('#4fc3f7', 'T1'))[0])
        t2_color = self._ensure_visible_color(
            Team.color_dict.get(self._team2, ('#ef9a9a', 'T2'))[0])
        t1_abbr  = Team.color_dict.get(self._team1, ('#4fc3f7', 'T1'))[1]
        t2_abbr  = Team.color_dict.get(self._team2, ('#ef9a9a', 'T2'))[1]

        ax = self.info_ax
        n_rows   = max(len(t1_roster), len(t2_roster), 1)
        available = 0.88
        step      = (available - 0.06) / n_rows
        font_size = max(6.5, min(8.0, step * 22))

        # Column headers
        ax.text(0.25, 0.97, t1_abbr, transform=ax.transAxes,
                color=t1_color, ha='center', va='top',
                fontsize=9, fontweight='bold')
        ax.text(0.75, 0.97, t2_abbr, transform=ax.transAxes,
                color=t2_color, ha='center', va='top',
                fontsize=9, fontweight='bold')

        # Centre divider
        ax.plot([0.5, 0.5], [0.03, 0.95], color='#334466',
                linewidth=0.6, transform=ax.transAxes, clip_on=False)

        # Build text objects for dynamic highlighting
        self._t1_roster_texts = []
        self._t2_roster_texts = []

        y = 0.97 - 0.06
        for i in range(n_rows):
            if i < len(t1_roster):
                name, jersey, _ = t1_roster[i]
                t = ax.text(0.02, y, f'  #{jersey:<3} {name}',
                            transform=ax.transAxes,
                            color='#445566', ha='left', va='top',
                            fontsize=font_size)
                self._t1_roster_texts.append(t)

            if i < len(t2_roster):
                name, jersey, _ = t2_roster[i]
                t = ax.text(0.52, y, f'  #{jersey:<3} {name}',
                            transform=ax.transAxes,
                            color='#445566', ha='left', va='top',
                            fontsize=font_size)
                self._t2_roster_texts.append(t)

            y -= step

    def _update_roster_highlight(self, on_court_ids):
        """Highlight on-court players (● white bold); dim others."""
        if on_court_ids == self._last_on_court_ids:
            return
        self._last_on_court_ids = on_court_ids

        for txt, (name, jersey, pid) in zip(self._t1_roster_texts, self._t1_roster):
            on = pid in on_court_ids
            txt.set_color('white' if on else '#445566')
            txt.set_fontweight('bold' if on else 'normal')
            txt.set_text(f'{"●" if on else " "}  #{jersey:<3} {name}')

        for txt, (name, jersey, pid) in zip(self._t2_roster_texts, self._t2_roster):
            on = pid in on_court_ids
            txt.set_color('white' if on else '#445566')
            txt.set_fontweight('bold' if on else 'normal')
            txt.set_text(f'{"●" if on else " "}  #{jersey:<3} {name}')

    # =================================================================
    # Core render
    # =================================================================

    def _render(self, frame_idx):
        if frame_idx >= self.n_frames:
            return
        frame   = self.frames[frame_idx]
        players = frame['players']

        # Players
        for j, circle in enumerate(self.player_circles):
            shadow = self.player_shadows[j]
            ring   = self.player_inner_ring[j]
            if j < len(players):
                p  = players[j]
                px, py = p['x'], p['y']
                color = self._team_colors.get(p['team_id'], 'gray')

                circle.center = (px, py)
                circle.set_facecolor(color)
                shadow.center = (px + 0.18, py - 0.18)

                if p['team_id'] == self._team2:
                    ring.center = (px, py)
                    ring.set_alpha(0.85)
                else:
                    ring.center = (-100, -100)
                    ring.set_alpha(0)

                info   = self.player_dict.get(p['id'], ('?', '?', p['team_id']))
                jersey = info[1]
                self.annotations[j].set_position((px, py))
                self.annotations[j].set_text(jersey)
            else:
                for patch in (circle, shadow, ring):
                    patch.center = (-100, -100)
                ring.set_alpha(0)
                self.annotations[j].set_position((-100, -100))
                self.annotations[j].set_text('')

        # Ball + trail
        bx, by, bz = frame['ball_x'], frame['ball_y'], frame['ball_z']
        display_r = min(
            self.BALL_BASE_R + bz / Constant.NORMALIZATION_COEF,
            self.BALL_MAX_R
        )
        self._ball_trail.append((bx, by))
        trail_list = list(self._ball_trail)
        n = len(trail_list)
        for i, tc in enumerate(self.trail_circles):
            if i < n - 1:
                tc.center = trail_list[i]
                tc.set_alpha((i + 1) / self.TRAIL_LEN * 0.45)
            else:
                tc.center = (-100, -100)
                tc.set_alpha(0)
        self.ball_circle.center = (bx, by)
        self.ball_circle.radius = display_r
        self.ball_shine.center  = (bx - display_r * 0.27, by - display_r * 0.27)
        self.ball_shine.radius  = display_r * 0.28

        # Scoreboard
        q  = frame['quarter']
        gc = frame['quarter_clock']
        if gc is not None:
            mm, ss   = int(gc) // 60, int(gc) % 60
            time_str = f'Q{q}  {mm:02d}:{ss:02d}'
        else:
            time_str = f'Q{q}  --:--'

        sc = frame['shot_clock']
        sc_str     = f'{sc:04.1f}' if sc is not None else ' N/A'
        shot_color = self.SHOT_URGENT if sc is not None and sc <= 5.0 else self.TEXT_DIM

        self.scoreboard_time.set_text(time_str)
        self.scoreboard_shot.set_text(f'Shot:  {sc_str}')
        self.scoreboard_shot.set_color(shot_color)
        self.slider_time_text.set_text(time_str)

        # Roster highlight
        on_court_ids = frozenset(p['id'] for p in players)
        self._update_roster_highlight(on_court_ids)

    # =================================================================
    # Timer
    # =================================================================

    def _start_timer(self):
        interval = max(1, int(self.BASE_INTERVAL_MS / self._speed))
        self._timer = self.fig.canvas.new_timer(interval=interval)
        self._timer.add_callback(self._step)
        self._timer.start()

    def _stop_timer(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _step(self):
        if self._current_frame >= self.n_frames - 1:
            self._stop_timer()
            self._is_playing = False
            self.play_btn.label.set_text('▶  Play')
            self.fig.canvas.draw_idle()
            return
        self._current_frame += 1
        self._render(self._current_frame)
        self._updating_slider = True
        self.slider.set_val(self._current_frame)
        self._updating_slider = False
        self.fig.canvas.draw_idle()

    # =================================================================
    # Callbacks
    # =================================================================

    def _on_slider_changed(self, val):
        if self._updating_slider:
            return
        self._ball_trail.clear()
        self._current_frame = int(val)
        self._render(self._current_frame)
        self.fig.canvas.draw_idle()

    def _on_play_pause(self, event):
        if self._is_playing:
            self._stop_timer()
            self._is_playing = False
            self.play_btn.label.set_text('▶  Play')
        else:
            self._start_timer()
            self._is_playing = True
            self.play_btn.label.set_text('⏸  Pause')
        self.fig.canvas.draw_idle()

    def _make_speed_callback(self, val):
        def callback(event):
            self._speed = val
            for btn, v in zip(self.speed_buttons, self.SPEED_VALUES):
                btn.ax.set_facecolor(
                    self.BTN_SPD_ACTIVE if abs(v - val) < 0.01 else self.BTN_NORMAL
                )
            if self._is_playing:
                self._stop_timer()
                self._start_timer()
            self.fig.canvas.draw_idle()
        return callback

    def _toggle_help(self, event):
        self.help_overlay.set_visible(not self.help_overlay.get_visible())
        self.fig.canvas.draw_idle()

    def _jump_to_frame(self, frame_idx):
        frame_idx = max(0, min(frame_idx, self.n_frames - 1))
        self._ball_trail.clear()
        self._current_frame = frame_idx
        self._render(frame_idx)
        self._updating_slider = True
        self.slider.set_val(frame_idx)
        self._updating_slider = False
        self.fig.canvas.draw_idle()

    # =================================================================
    # Keyboard
    # =================================================================

    def _connect_keyboard(self):
        self.fig.canvas.mpl_connect('key_press_event', self._on_key_press)

    def _on_key_press(self, event):
        if event.key == ' ':
            self._on_play_pause(None)
        elif event.key == 'right':
            self._jump_to_frame(self._current_frame + self.STEP_FRAMES)
        elif event.key == 'left':
            self._jump_to_frame(self._current_frame - self.STEP_FRAMES)

    # =================================================================
    # Utility
    # =================================================================

    @staticmethod
    def _ensure_visible_color(hex_color, threshold=0.20):
        """Brighten team colours that are too dark for the dark background."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if brightness >= threshold:
                return hex_color
            blend = 0.45
            r2 = int(r + blend * (255 - r))
            g2 = int(g + blend * (255 - g))
            b2 = int(b + blend * (255 - b))
            return f'#{r2:02x}{g2:02x}{b2:02x}'
        except (ValueError, IndexError):
            return hex_color

    # =================================================================
    # Entry point
    # =================================================================

    def show(self):
        plt.show()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='NBA Possession Viewer — animate a single possession from CSV.'
    )
    parser.add_argument(
        '--path',
        default=os.path.join(_here, 'data', '0021500001_1_5.csv'),
        help='Path to possession CSV (default: data/0021500001_1_5.csv)'
    )
    parser.add_argument(
        '--players',
        default=os.path.join(_here, 'data', 'player_data.csv'),
        help='Path to player_data.csv (default: data/player_data.csv)'
    )
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f'Error: possession file not found — {args.path}')
        sys.exit(1)
    if not os.path.exists(args.players):
        print(f'Error: player data file not found — {args.players}')
        sys.exit(1)

    frames, player_dict = load_possession(args.path, args.players)
    print(f'Loaded {len(frames)} frames from {os.path.basename(args.path)}')

    basename = os.path.basename(args.path)
    title    = f'Possession — {basename}'
    viewer   = PossessionViewer(frames, player_dict, title=title, filename=basename)
    viewer.show()


if __name__ == '__main__':
    main()
