"""
Line selection module.
Selects station lines and block section lines for trains based on
connectivity constraints, line preferences, and current occupancy.

Station lines: at each station, a train must be assigned to a line that
connects to both the incoming and outgoing block sections.

Block section lines: on multi-line block sections, a train is assigned
to a specific track.

Selection priority: Main (M) > Loop (L) > Siding (S) > Yard (Y),
with least-occupied line preferred among equal categories.
"""

from collections import defaultdict

# Line category preference: lower = better
LINE_CATEGORY_RANK = {'M': 0, 'L': 1, 'S': 2, 'Y': 3, '': 4}


class LineSelector:
    def __init__(self, station_lines, block_section_lines, line_connections):
        """
        Parameters:
            station_lines: dict station_code -> list of line dicts
            block_section_lines: dict bs_id -> list of line dicts
            line_connections: dict station_code -> list of connection dicts
        """
        self._station_lines = station_lines
        self._bs_lines = block_section_lines

        # Build connection index: (station, bs_id, direction) -> set of station lines
        # direction: 'R' = receive from BS, 'S' = send to BS
        self._conn_index = defaultdict(set)
        for stn, conns in line_connections.items():
            for c in conns:
                bs = c.get('block_section', '')
                flag = c.get('recv_send_flag', '')
                stn_line = c.get('station_line', '')
                if bs and flag and stn_line:
                    self._conn_index[(stn, bs, flag)].add(stn_line)

        # Build line info lookup: (station, line_number) -> line dict
        self._line_info = {}
        for stn, lines in station_lines.items():
            for l in lines:
                self._line_info[(stn, l['line_number'])] = l

        # Occupancy tracking: (station, line_number) -> list of (end_time, start_time)
        self._line_occupancy = defaultdict(list)
        self._bs_line_occupancy = defaultdict(list)

    def get_valid_station_lines(self, station, bs_in, bs_out):
        """
        Get valid station lines that connect to both incoming and outgoing
        block sections.

        Returns sorted list of (line_number, category_rank) tuples.
        """
        # Lines that can receive from incoming BS
        recv_lines = self._conn_index.get((station, bs_in, 'R'), set())
        # Lines that can send to outgoing BS
        send_lines = self._conn_index.get((station, bs_out, 'S'), set())

        if recv_lines and send_lines:
            valid = recv_lines & send_lines
            if not valid:
                # No line connects both - try union as fallback
                valid = recv_lines | send_lines
        elif recv_lines:
            valid = recv_lines
        elif send_lines:
            valid = send_lines
        else:
            # No connection data - use all station lines
            all_lines = self._station_lines.get(station, [])
            valid = set(l['line_number'] for l in all_lines)

        if not valid:
            return []

        # Rank by category preference
        ranked = []
        for ln in valid:
            info = self._line_info.get((station, ln), {})
            cat = info.get('line_category', '')
            rank = LINE_CATEGORY_RANK.get(cat, 4)
            ranked.append((ln, rank))

        ranked.sort(key=lambda x: x[1])
        return ranked

    def select_station_line(self, station, bs_in, bs_out, arrival, departure):
        """
        Select the best available station line.

        Prefers Main lines, then Loop, then Siding.
        Among same-category lines, picks the one with least occupancy overlap.

        Parameters:
            station: station code
            bs_in: incoming block section ID
            bs_out: outgoing block section ID
            arrival: arrival time (seconds)
            departure: departure time (seconds)

        Returns:
            selected line number (str), or '' if no lines available
        """
        candidates = self.get_valid_station_lines(station, bs_in, bs_out)
        if not candidates:
            return ''

        best_line = candidates[0][0]
        best_rank = candidates[0][1]
        best_conflicts = float('inf')

        for line_num, rank in candidates:
            # Count overlapping occupancies
            intervals = self._line_occupancy[(station, line_num)]
            conflicts = 0
            for (iend, istart) in intervals:
                if istart < departure and iend > arrival:
                    conflicts += 1

            # Pick least-conflicting line, preferring higher-ranked category
            if (rank < best_rank) or (rank == best_rank and conflicts < best_conflicts):
                best_line = line_num
                best_rank = rank
                best_conflicts = conflicts

        # Record occupancy
        self._line_occupancy[(station, best_line)].append((departure, arrival))
        return best_line

    def select_bs_line(self, bs_id, entry_time, exit_time):
        """
        Select a block section line for a train.

        Parameters:
            bs_id: block section ID
            entry_time: when the train enters (seconds)
            exit_time: when the train exits (seconds)

        Returns:
            selected line number (str), or '' if no line data
        """
        lines = self._bs_lines.get(bs_id, [])
        if not lines:
            return ''

        best_line = lines[0].get('line_number', '')
        best_conflicts = float('inf')

        for l in lines:
            ln = l.get('line_number', '')
            intervals = self._bs_line_occupancy[(bs_id, ln)]
            conflicts = 0
            for (iend, istart) in intervals:
                if istart < exit_time and iend > entry_time:
                    conflicts += 1

            if conflicts < best_conflicts:
                best_line = ln
                best_conflicts = conflicts

        self._bs_line_occupancy[(bs_id, best_line)].append((exit_time, entry_time))
        return best_line
