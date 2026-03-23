"""
FullGameViewer — interactive full-game NBA tracking viewer.

Controls
--------
▶ Play / ⏸ Pause  toggle animation
Q1 / Q2 / Q3 / Q4  jump to quarter start  (active quarter is highlighted)
0.5× 1× 2× 4×      speed buttons          (active speed is highlighted)
?                   toggle keyboard-shortcut overlay
Timeline slider     drag to any frame

Keyboard
--------
Space     play / pause
← →       step ±1 second (25 frames)
1 2 3 4   jump to that quarter
"""

from collections import deque
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.widgets as mwidgets
from matplotlib.patches import Circle, Rectangle
from matplotlib.transforms import blended_transform_factory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Constant import Constant
from Team import Team


class FullGameViewer:

    # ── Playback ──────────────────────────────────────────────────────
    SPEED_LABELS     = ['0.5×', '1×', '2×', '4×']
    SPEED_VALUES     = [0.5, 1.0, 2.0, 4.0]
    BASE_INTERVAL_MS = 40          # ms per frame @ 1× speed  (25 FPS)
    STEP_FRAMES      = 25          # frames per arrow-key press (~1 s)
    TRAIL_LEN        = 8           # ball trail length

    # ── Node / ball sizing ────────────────────────────────────────────
    PLAYER_R    = Constant.PLAYER_CIRCLE_SIZE           # ≈ 1.71 court units
    BALL_BASE_R = Constant.PLAYER_CIRCLE_SIZE * 0.55
    BALL_MAX_R  = Constant.PLAYER_CIRCLE_SIZE * 1.10

    # ── Palette ───────────────────────────────────────────────────────
    BG_DARK        = '#0f0f1a'
    BG_PANEL       = '#16213e'
    BG_WIDGET      = '#1a2744'
    BG_SCORE       = '#0d0d1a'
    BTN_NORMAL     = '#1e3a6e'
    BTN_HOVER      = '#2e5499'
    BTN_PLAY       = '#1b5e20'
    BTN_PLAY_HV    = '#2e7d32'
    BTN_Q_ACTIVE   = '#3d6abf'     # lit-up quarter button
    BTN_SPD_ACTIVE = '#c8860a'     # lit-up speed button
    SLIDER_CLR     = '#4caf50'
    TEXT_WHITE     = 'white'
    TEXT_DIM       = '#aaaacc'
    SHOT_URGENT    = '#ff4444'     # shot-clock colour when ≤ 5 s

    # ── Luminance threshold for dark team colours ─────────────────────
    # Teams whose perceived brightness is below this are brightened.
    COLOR_LUMA_MIN = 0.20

    def __init__(self, timeline):
        self.timeline = timeline

        # Playback state
        self._current_frame     = 0
        self._is_playing        = False
        self._speed             = 1.0
        self._updating_slider   = False
        self._timer             = None

        # Render-optimisation guards
        self._displayed_quarter  = 0
        self._last_on_court_ids  = frozenset()
        self._ball_trail         = deque(maxlen=self.TRAIL_LEN)

        # Team IDs (home = solid circle, away = solid + inner ring)
        home_id, vis_id, _, _ = timeline.get_team_info()
        self._home_teamid = home_id
        self._vis_teamid  = vis_id

        # Pre-compute luminance-adjusted team colours once (not per frame)
        self._team_colors = {
            tid: self._ensure_visible_color(info[0])
            for tid, info in Team.color_dict.items()
        }

        # Sorted quarters cache (used in _update_quarter_highlight)
        self._sorted_quarters = sorted(timeline.quarters)

        # Roster cache (populated in _create_info_panel, used in _update_roster)
        self._home_roster_cache = []
        self._vis_roster_cache  = []

        self._build_figure()
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

    def _build_figure(self):
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(16, 9))
        self.fig.patch.set_facecolor(self.BG_DARK)

        # ── Scoreboard strip (full width, very top) ───────────────────
        self.score_ax = self.fig.add_axes([0.00, 0.93, 1.00, 0.07])
        self.score_ax.axis('off')
        self.score_ax.set_facecolor(self.BG_SCORE)

        # ── Court (left 70 %) ─────────────────────────────────────────
        self.court_ax = self.fig.add_axes([0.02, 0.16, 0.68, 0.69])
        self.court_ax.set_facecolor(self.BG_DARK)

        # ── Info panel (right) ────────────────────────────────────────
        self.info_ax = self.fig.add_axes([0.72, 0.16, 0.26, 0.69])
        self.info_ax.axis('off')
        self.info_ax.add_patch(
            Rectangle((0, 0), 1, 1,
                       transform=self.info_ax.transAxes,
                       facecolor=self.BG_PANEL, zorder=0)
        )

        # ── Timeline slider ───────────────────────────────────────────
        self.ax_slider = self.fig.add_axes([0.02, 0.07, 0.68, 0.04])
        self.ax_slider.set_facecolor(self.BG_WIDGET)

        # ── Control bar ───────────────────────────────────────────────
        BTN_Y, BTN_H = 0.87, 0.05

        # Q1–Q4 jump buttons
        self.ax_q = [
            self.fig.add_axes([0.02 + i * 0.075, BTN_Y, 0.07, BTN_H])
            for i in range(4)
        ]

        # Play / Pause
        self.ax_play = self.fig.add_axes([0.34, BTN_Y, 0.14, BTN_H])

        # Speed buttons (horizontal group — replaces radio widget)
        self.ax_spd = [
            self.fig.add_axes([0.510 + i * 0.044, BTN_Y, 0.040, BTN_H])
            for i in range(4)
        ]

        # Help (?) button
        self.ax_help = self.fig.add_axes([0.692, BTN_Y, 0.028, BTN_H])

    def _draw_court(self):
        court_path = 'courta.png'
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
    # Patches — players, ball, trail, overlay
    # =================================================================

    def _create_patches(self):
        # ── Player shadow discs ───────────────────────────────────────
        self.player_shadows = [
            Circle((-100, -100), self.PLAYER_R * 1.35,
                   color='black', alpha=0.25, zorder=2, linewidth=0)
            for _ in range(10)
        ]

        # ── Player filled circles ─────────────────────────────────────
        self.player_circles = [
            Circle((-100, -100), self.PLAYER_R,
                   facecolor='gray', zorder=3,
                   edgecolor='white', linewidth=1.8)
            for _ in range(10)
        ]

        # ── Away-team inner ring (#8: home/away shape distinction) ────
        # Home = solid fill only.  Away = solid fill + inner white ring.
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

        # ── Jersey numbers ────────────────────────────────────────────
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

        # ── Ball trail (#7) ───────────────────────────────────────────
        # 8 fading circles, oldest = smallest + most transparent.
        self.trail_circles = [
            Circle((-100, -100),
                   self.BALL_BASE_R * (0.25 + 0.55 * i / self.TRAIL_LEN),
                   facecolor='#F47F20', alpha=0, zorder=1, linewidth=0)
            for i in range(self.TRAIL_LEN)
        ]
        for tc in self.trail_circles:
            self.court_ax.add_patch(tc)

        # ── Ball (main + shine) ───────────────────────────────────────
        self.ball_circle = Circle((-100, -100), self.BALL_BASE_R,
                                  facecolor='#F47F20', zorder=4,
                                  edgecolor='#7B3A00', linewidth=1.5)
        self.ball_shine  = Circle((-100, -100), self.BALL_BASE_R * 0.28,
                                  color='white', alpha=0.55,
                                  zorder=5, linewidth=0)
        self.court_ax.add_patch(self.ball_circle)
        self.court_ax.add_patch(self.ball_shine)

        # ── Keyboard help overlay (#10) ───────────────────────────────
        self.help_overlay = self.court_ax.text(
            47, 25,
            '   Keyboard Shortcuts   \n'
            '─────────────────────────\n'
            '  Space      Play / Pause\n'
            '  ← →        Step ± 1 sec\n'
            '  1  2  3  4  Jump to quarter\n',
            color='white', ha='center', va='center',
            fontsize=11, fontfamily='monospace',
            zorder=10, visible=False,
            bbox=dict(boxstyle='round,pad=0.9',
                      facecolor='#0a0a1a', alpha=0.95,
                      edgecolor='#4a7fd4', linewidth=1.5)
        )

    # =================================================================
    # Scoreboard strip (#6)
    # =================================================================

    def _create_scoreboard(self):
        home_id, vis_id, home_name, vis_name = self.timeline.get_team_info()
        home_color = Team.color_dict.get(home_id, ('#4fc3f7', 'HOM'))[0]
        vis_color  = Team.color_dict.get(vis_id,  ('#ef9a9a', 'VIS'))[0]
        home_abbr  = Team.color_dict.get(home_id, ('#4fc3f7', 'HOM'))[1]
        vis_abbr   = Team.color_dict.get(vis_id,  ('#ef9a9a', 'VIS'))[1]

        ax = self.score_ax

        # Accent colour bars on outer edges
        ax.add_patch(Rectangle((0, 0), 0.022, 1,
                               transform=ax.transAxes,
                               facecolor=home_color, zorder=1))
        ax.add_patch(Rectangle((0.978, 0), 0.022, 1,
                               transform=ax.transAxes,
                               facecolor=vis_color, zorder=1))

        # Team names
        ax.text(0.032, 0.5, f'{home_abbr}   {home_name}',
                transform=ax.transAxes,
                color=home_color, ha='left', va='center',
                fontsize=11, fontweight='bold')
        ax.text(0.968, 0.5, f'{vis_name}   {vis_abbr}',
                transform=ax.transAxes,
                color=vis_color, ha='right', va='center',
                fontsize=11, fontweight='bold')

        # Centre divider
        ax.plot([0.5, 0.5], [0.1, 0.9], color='#334466',
                linewidth=0.8, transform=ax.transAxes)

        # Live game clock — updated each frame
        self.scoreboard_time = ax.text(
            0.5, 0.70, 'Q1  12:00',
            transform=ax.transAxes,
            color='white', ha='center', va='center',
            fontsize=13, fontweight='bold'
        )

        # Shot clock — turns red at ≤ 5 s (#3)
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
        total    = max(self.timeline.total_frames - 1, 1)
        quarters = self.timeline.quarters

        # ── Timeline slider ───────────────────────────────────────────
        self.slider = mwidgets.Slider(
            self.ax_slider, '', 0, total,
            valinit=0, valstep=1, color=self.SLIDER_CLR
        )
        self.slider.label.set_visible(False)

        trans = blended_transform_factory(
            self.ax_slider.transData, self.ax_slider.transAxes
        )
        for q in quarters:
            qi = self.timeline.quarter_starts[q]
            self.ax_slider.axvline(x=qi, color='white', alpha=0.35,
                                   linewidth=1.5, zorder=5)
            self.ax_slider.text(
                qi + total * 0.003, 1.12, f'Q{q}',
                transform=trans, color='white',
                fontsize=7.5, ha='left', va='bottom', clip_on=False
            )

        # Time label below slider (#1 — shows "Q2  08:42", not frame numbers)
        self.slider_time_text = self.ax_slider.text(
            0.5, -0.65, '',
            transform=self.ax_slider.transAxes,
            color=self.TEXT_DIM, fontsize=8,
            ha='center', va='top', clip_on=False
        )

        # ── Quarter jump buttons (#2 — active state highlight) ────────
        self.q_buttons = []
        for i, q in enumerate(self._sorted_quarters):
            btn = mwidgets.Button(
                self.ax_q[i], f'Q{q}',
                color=self.BTN_NORMAL, hovercolor=self.BTN_HOVER
            )
            btn.label.set_color(self.TEXT_WHITE)
            btn.label.set_fontweight('bold')
            btn.label.set_fontsize(10)
            btn.on_clicked(self._make_quarter_callback(q))
            self.q_buttons.append(btn)

        # ── Play / Pause ──────────────────────────────────────────────
        self.play_btn = mwidgets.Button(
            self.ax_play, '▶  Play',
            color=self.BTN_PLAY, hovercolor=self.BTN_PLAY_HV
        )
        self.play_btn.label.set_color(self.TEXT_WHITE)
        self.play_btn.label.set_fontsize(11)
        self.play_btn.on_clicked(self._on_play_pause)

        # ── Speed buttons (#4 — horizontal group, replaces radio) ─────
        self.speed_buttons = []
        for i, (label, val) in enumerate(
                zip(self.SPEED_LABELS, self.SPEED_VALUES)):
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

        # ── Help (?) button (#10) ─────────────────────────────────────
        self.help_btn = mwidgets.Button(
            self.ax_help, '?',
            color=self.BTN_NORMAL, hovercolor=self.BTN_HOVER
        )
        self.help_btn.label.set_color(self.TEXT_WHITE)
        self.help_btn.label.set_fontsize(10)
        self.help_btn.on_clicked(self._toggle_help)

        # Connect slider last
        self.slider.on_changed(self._on_slider_changed)

    # =================================================================
    # Info panel — roster only, no clock (#5, #10)
    # =================================================================

    def _create_info_panel(self):
        home_id, vis_id, home_name, vis_name = self.timeline.get_team_info()
        home_roster, vis_roster = self.timeline.get_rosters()

        # Cache for use in _update_roster_highlight
        self._home_roster_cache = home_roster
        self._vis_roster_cache  = vis_roster

        home_color = Team.color_dict.get(home_id, ('#4fc3f7', ''))[0]
        vis_color  = Team.color_dict.get(vis_id,  ('#ef9a9a', ''))[0]

        ax = self.info_ax
        n_rows = max(len(home_roster), len(vis_roster), 1)

        # Dynamic step so all players always fit
        available  = 0.88        # y-zone for players (0.05 → 0.93)
        step       = (available - 0.06) / n_rows   # 0.06 for headers
        font_size  = max(6.5, min(8.0, step * 22))

        # Column headers
        ax.text(0.25, 0.97, home_name,
                transform=ax.transAxes,
                color=home_color, ha='center', va='top',
                fontsize=9, fontweight='bold')
        ax.text(0.75, 0.97, vis_name,
                transform=ax.transAxes,
                color=vis_color, ha='center', va='top',
                fontsize=9, fontweight='bold')

        # Vertical centre divider
        ax.plot([0.5, 0.5], [0.03, 0.95], color='#334466',
                linewidth=0.6, transform=ax.transAxes, clip_on=False)

        # Build text objects and store references for dynamic highlighting
        self.home_roster_texts = []
        self.vis_roster_texts  = []

        y = 0.97 - 0.06
        for i in range(n_rows):
            if i < len(home_roster):
                name, jersey, _ = home_roster[i]
                t = ax.text(0.02, y, f'  #{jersey:<3} {name}',
                            transform=ax.transAxes,
                            color='#445566', ha='left', va='top',
                            fontsize=font_size)
                self.home_roster_texts.append(t)

            if i < len(vis_roster):
                name, jersey, _ = vis_roster[i]
                t = ax.text(0.52, y, f'  #{jersey:<3} {name}',
                            transform=ax.transAxes,
                            color='#445566', ha='left', va='top',
                            fontsize=font_size)
                self.vis_roster_texts.append(t)

            y -= step

    # =================================================================
    # Core render
    # =================================================================

    def _render(self, frame_idx):
        try:
            moment = self.timeline.get_moment(frame_idx)
        except Exception:
            return

        player_dict  = self.timeline.get_player_dict()
        on_court_ids = frozenset(p.id for p in moment.players)

        # ── Players: circles + shadows + away-ring + jersey numbers ───
        for j, circle in enumerate(self.player_circles):
            shadow = self.player_shadows[j]
            ring   = self.player_inner_ring[j]
            try:
                player = moment.players[j]
                px, py = player.x, player.y

                # #9: luminance-floored team colour (pre-computed)
                color = self._team_colors.get(player.team.id, player.color)

                circle.center = (px, py)
                circle.set_facecolor(color)
                shadow.center = (px + 0.18, py - 0.18)

                # #8: away team gets inner white ring; home does not
                if player.team.id == self._vis_teamid:
                    ring.center = (px, py)
                    ring.set_alpha(0.85)
                else:
                    ring.center = (-100, -100)
                    ring.set_alpha(0)

                self.annotations[j].set_position((px, py))
                jersey = player_dict.get(player.id, ('?', '?'))[1]
                self.annotations[j].set_text(jersey)

            except IndexError:
                for patch in (circle, shadow, ring):
                    patch.center = (-100, -100)
                ring.set_alpha(0)
                self.annotations[j].set_position((-100, -100))
                self.annotations[j].set_text('')

        # ── Ball trail (#7) + ball ────────────────────────────────────
        try:
            bx, by = moment.ball.x, moment.ball.y
            z = moment.ball.radius   # z-height in feet
            display_r = min(
                self.BALL_BASE_R + z / Constant.NORMALIZATION_COEF,
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
            shine_r = display_r * 0.28
            self.ball_shine.center = (bx - display_r * 0.27,
                                      by - display_r * 0.27)
            self.ball_shine.radius = shine_r

        except (AttributeError, TypeError):
            self.ball_circle.center = (-100, -100)
            self.ball_shine.center  = (-100, -100)
            for tc in self.trail_circles:
                tc.center = (-100, -100)
                tc.set_alpha(0)

        # ── Scoreboard clock (#6) ─────────────────────────────────────
        q = moment.quarter
        try:
            gc = int(moment.game_clock)
            mm, ss = gc // 60, gc % 60
            time_str = f'Q{q}  {mm:02d}:{ss:02d}'
        except (TypeError, ValueError):
            time_str = f'Q{q}  --:--'

        try:
            sc = moment.shot_clock
            sc_str     = f'{sc:04.1f}' if sc is not None else ' N/A'
            # #3: shot clock turns red at ≤ 5 s
            shot_color = (self.SHOT_URGENT
                          if sc is not None and sc <= 5.0
                          else self.TEXT_DIM)
        except (TypeError, AttributeError):
            sc_str, shot_color = ' N/A', self.TEXT_DIM

        self.scoreboard_time.set_text(time_str)
        self.scoreboard_shot.set_text(f'Shot:  {sc_str}')
        self.scoreboard_shot.set_color(shot_color)

        # #1: slider shows game time, not raw frame numbers
        self.slider_time_text.set_text(time_str)

        # #2: highlight active quarter button
        self._update_quarter_highlight(q)

        # #5: dim bench, highlight on-court 5
        self._update_roster_highlight(on_court_ids)

    # =================================================================
    # Render helpers
    # =================================================================

    def _update_quarter_highlight(self, q):
        """Light up the button for the current quarter; dim the others."""
        if q == self._displayed_quarter:
            return
        self._displayed_quarter = q
        for i, btn in enumerate(self.q_buttons):
            qi = self._sorted_quarters[i]
            btn.ax.set_facecolor(
                self.BTN_Q_ACTIVE if qi == q else self.BTN_NORMAL
            )

    def _update_speed_highlight(self, speed):
        """Light up the active speed button; dim the others."""
        for btn, val in zip(self.speed_buttons, self.SPEED_VALUES):
            btn.ax.set_facecolor(
                self.BTN_SPD_ACTIVE if abs(val - speed) < 0.01
                else self.BTN_NORMAL
            )

    def _update_roster_highlight(self, on_court_ids):
        """Highlight on-court players (●, white, bold); dim bench (#445566)."""
        if on_court_ids == self._last_on_court_ids:
            return   # lineup unchanged — skip expensive text updates
        self._last_on_court_ids = on_court_ids

        for txt, (name, jersey, pid) in zip(
                self.home_roster_texts, self._home_roster_cache):
            on = pid in on_court_ids
            txt.set_color('white' if on else '#445566')
            txt.set_fontweight('bold' if on else 'normal')
            txt.set_text(f'{"●" if on else " "}  #{jersey:<3} {name}')

        for txt, (name, jersey, pid) in zip(
                self.vis_roster_texts, self._vis_roster_cache):
            on = pid in on_court_ids
            txt.set_color('white' if on else '#445566')
            txt.set_fontweight('bold' if on else 'normal')
            txt.set_text(f'{"●" if on else " "}  #{jersey:<3} {name}')

    # =================================================================
    # Timer-based animation
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
        if self._current_frame >= self.timeline.total_frames - 1:
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
        self._ball_trail.clear()   # #7: clear trail on manual scrub
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

    def _make_quarter_callback(self, q):
        def callback(event):
            self._jump_to_frame(self.timeline.quarter_starts[q])
        return callback

    def _make_speed_callback(self, val):
        def callback(event):
            self._speed = val
            self._update_speed_highlight(val)
            if self._is_playing:
                self._stop_timer()
                self._start_timer()
            self.fig.canvas.draw_idle()
        return callback

    def _toggle_help(self, event):
        """Toggle the keyboard shortcut overlay (#10)."""
        self.help_overlay.set_visible(not self.help_overlay.get_visible())
        self.fig.canvas.draw_idle()

    def _jump_to_frame(self, frame_idx):
        frame_idx = max(0, min(frame_idx, self.timeline.total_frames - 1))
        self._ball_trail.clear()   # #7: clear trail on jump
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
        key = event.key
        if key == ' ':
            self._on_play_pause(None)
        elif key == 'right':
            self._jump_to_frame(self._current_frame + self.STEP_FRAMES)
        elif key == 'left':
            self._jump_to_frame(self._current_frame - self.STEP_FRAMES)
        elif key in ('1', '2', '3', '4'):
            q = int(key)
            if q in self.timeline.quarter_starts:
                self._jump_to_frame(self.timeline.quarter_starts[q])

    # =================================================================
    # Utility
    # =================================================================

    @staticmethod
    def _ensure_visible_color(hex_color, threshold=0.20):
        """Brighten team colours too dark to see on a dark background.
        Uses perceived brightness: 0.299R + 0.587G + 0.114B.
        Affected teams: BKN (#061922), WAS/NOP (#002B5C), IND (#00275D),
        CHA (#1D1160), MIA (#98002E), MEM (#0F586C)."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if brightness >= threshold:
                return hex_color
            blend = 0.45   # mix 45 % toward white
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
