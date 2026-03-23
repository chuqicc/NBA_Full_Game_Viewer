import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Moment import Moment


class GameTimeline:
    """
    Loads a full game JSON, deduplicates all moments across all events,
    and builds a clean sorted timeline for the full game.
    """

    def __init__(self, path_to_json):
        self.path = path_to_json
        self.timeline = []          # sorted list of raw moment lists
        self._player_dict = {}      # {player_id: (full_name, jersey_str)}
        self._quarter_starts = {}   # {quarter_num: frame_idx}
        self._home_teamid = None
        self._visitor_teamid = None
        self._home_name = ''
        self._visitor_name = ''
        # Rosters are (name, jersey, player_id) 3-tuples
        self._home_roster = []
        self._visitor_roster = []

    def load(self):
        print(f"Loading: {self.path}")
        with open(self.path, 'r') as f:
            data = json.load(f)

        events = data['events']
        print(f"Found {len(events)} events. Deduplicating moments...")

        first = events[0]
        self._home_teamid    = first['home']['teamid']
        self._visitor_teamid = first['visitor']['teamid']
        self._home_name    = first['home'].get('name',
                             first['home'].get('abbreviation', 'HOME'))
        self._visitor_name = first['visitor'].get('name',
                             first['visitor'].get('abbreviation', 'VIS'))

        # Rosters include player_id as third element (needed for on-court detection)
        for p in first['home']['players']:
            name = p['firstname'] + ' ' + p['lastname']
            self._home_roster.append((name, str(p['jersey']), p['playerid']))

        for p in first['visitor']['players']:
            name = p['firstname'] + ' ' + p['lastname']
            self._visitor_roster.append((name, str(p['jersey']), p['playerid']))

        # Union player dict from all events
        for event in events:
            for player in event['home']['players'] + event['visitor']['players']:
                pid = player['playerid']
                name = player['firstname'] + ' ' + player['lastname']
                self._player_dict[pid] = (name, str(player['jersey']))

        # Deduplicate by (quarter, timestamp_ms)
        seen = {}
        total_raw = 0
        for event in events:
            for moment in event['moments']:
                total_raw += 1
                key = (moment[0], moment[1])
                if key not in seen:
                    seen[key] = moment

        self.timeline = sorted(seen.values(), key=lambda m: (m[0], m[1]))

        for i, m in enumerate(self.timeline):
            q = m[0]
            if q not in self._quarter_starts:
                self._quarter_starts[q] = i

        print(f"Loaded {len(self.timeline):,} unique frames "
              f"(from {total_raw:,} raw) across {len(self._quarter_starts)} quarters.")
        for q in sorted(self._quarter_starts):
            start = self._quarter_starts[q]
            ends  = [v for k, v in self._quarter_starts.items() if k > q]
            end   = min(ends) - 1 if ends else len(self.timeline) - 1
            print(f"  Q{q}: frames {start:,} – {end:,}  ({end - start + 1:,} frames)")

    @property
    def total_frames(self):
        return len(self.timeline)

    @property
    def quarter_starts(self):
        return self._quarter_starts

    @property
    def quarters(self):
        return sorted(self._quarter_starts.keys())

    def get_moment(self, frame_idx):
        return Moment(self.timeline[frame_idx])

    def get_raw_moment(self, frame_idx):
        return self.timeline[frame_idx]

    def get_player_dict(self):
        return self._player_dict

    def get_team_info(self):
        return (self._home_teamid, self._visitor_teamid,
                self._home_name, self._visitor_name)

    def get_rosters(self):
        """Return (home_roster, visitor_roster).
        Each roster is a list of (name, jersey_str, player_id) 3-tuples."""
        return self._home_roster, self._visitor_roster

    def get_game_clock_at(self, frame_idx):
        raw = self.timeline[frame_idx]
        return raw[0], raw[2]
