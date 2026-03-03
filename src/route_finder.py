"""
Route Finder Module:

Finds valid routes from origin to destination through the block section
network using Dijkstra's shortest-path algorithm, constrained by:
  - Gauge compatibility (train gauge must match block section gauge)
  - Line connectivity (only use block sections reachable via valid station lines)
  - Section/corridor affinity (prefer staying on the same corridor)

For trains that already have reference routes (from Train_Schedule.csv),
the existing route is used. This module is for the ~9,600 TrainMaster
trains without pre-defined routes.
"""

import heapq
from collections import defaultdict


class RouteFinder:
    # Builds a directed station graph from block section and line connection data, then finds shortest-distance routes respecting gauge and line constraints.

    # Small penalty (km) for switching corridor/section code
    CORRIDOR_SWITCH_PENALTY = 2.0

    def __init__(self, block_sections, line_connections=None, stations=None):
        """
        Args:
            block_sections: dict keyed by bs_id -> {from_station, to_station, distance_km, gauge, section_code, ...}
            line_connections: dict keyed by station_code -> [{station_line, block_section, bs_line, recv_send_flag}]
            stations: dict keyed by station_code -> {code, name, ...}
        """
        self.block_sections = block_sections
        self.line_connections = line_connections or {}
        self.stations = stations or {}

        # Pre-compute outgoing BS per station from line connections
        self._stn_outgoing_bs = defaultdict(set)
        for stn, conns in self.line_connections.items():
            for c in conns:
                if c['recv_send_flag'] == 'S':
                    self._stn_outgoing_bs[stn].add(c['block_section'])

        # Build the directed graph
        self._graph = self._build_graph()

        # All station codes reachable in the graph
        self._all_stations = set(self._graph.keys())
        for edges in self._graph.values():
            for e in edges:
                self._all_stations.add(e['to'])

    def _build_graph(self):
        # Build directed adjacency list: station -> [edge_dict, ...]
        graph = defaultdict(list)
        for bs_id, data in self.block_sections.items():
            fr = data['from_station']
            to = data['to_station']
            dist = data.get('distance_km', 0) or 0.1
            gauge = data.get('gauge', 'B')
            section = data.get('section_code', '')

            # Check line connectivity: if station has connection data,
            # only allow BS that appear in its outgoing set
            has_lc = fr in self.line_connections
            line_ok = not has_lc or bs_id in self._stn_outgoing_bs.get(fr, set())

            graph[fr].append({
                'to': to,
                'bs_id': bs_id,
                'dist': dist,
                'gauge': gauge,
                'section': section,
                'line_ok': line_ok,
            })
        return graph

    def find_route(self, origin, destination, train_gauge='B'):
        """
        Find shortest-distance route from origin to destination.

        Args:
            origin: station code (e.g. 'NDLS')
            destination: station code (e.g. 'BCT')
            train_gauge: gauge filter ('B' broad, 'M' metre, 'N' narrow)

        Returns:
            list of dicts matching the leg format used by schedule_engine:
                [{'station': ..., 'block_section': ..., 'distance_km': ..., ...}, ...]
            or None if no path exists.
        """
        if origin not in self._all_stations:
            return None
        if destination not in self._all_stations:
            return None
        if origin == destination:
            return self._enrich_route([self._make_leg(origin, '', 0)])

        # Dijkstra with predecessor tracking (memory-efficient)
        best = {}         # station -> finalized cost
        tentative = {origin: 0.0}  # station -> best tentative cost
        prev = {}         # station -> (prev_station, bs_id, distance, section_code)
        counter = 0
        pq = [(0.0, counter, origin, '')]

        while pq:
            cost, _, node, prev_section = heapq.heappop(pq)

            if node in best:
                continue
            best[node] = cost

            if node == destination:
                # Reconstruct path from predecessor map
                path = []
                curr = destination
                while curr in prev:
                    p_stn, p_bs, p_dist, _ = prev[curr]
                    path.append(self._make_leg(p_stn, p_bs, p_dist))
                    curr = p_stn
                path.reverse()
                # Add final destination leg (no outgoing BS)
                path.append(self._make_leg(destination, '', 0))
                return self._enrich_route(path)

            for edge in self._graph.get(node, []):
                nbr = edge['to']
                if nbr in best:
                    continue

                # Gauge filter: train must be compatible with block section
                if train_gauge and edge['gauge'] not in (train_gauge, f'{train_gauge},M',
                                                          f'{train_gauge},N', f'B,{train_gauge}'):
                    if train_gauge != edge['gauge']:
                        continue

                # Prefer line-valid edges; allow line-invalid with heavy penalty
                line_penalty = 0 if edge['line_ok'] else 50.0

                # Corridor affinity: small penalty for switching section codes
                section = edge['section']
                corridor_penalty = 0
                if prev_section and section and section != prev_section:
                    corridor_penalty = self.CORRIDOR_SWITCH_PENALTY

                new_cost = cost + edge['dist'] + line_penalty + corridor_penalty

                if new_cost < tentative.get(nbr, float('inf')):
                    tentative[nbr] = new_cost
                    prev[nbr] = (node, edge['bs_id'], edge['dist'], section)
                    counter += 1
                    heapq.heappush(pq, (new_cost, counter, nbr, section))

        return None  # No path found

    def find_route_via_waypoints(self, origin, destination, waypoints, train_gauge='B'):
        """
        Find a route from origin to destination that passes through mandatory
        waypoints (stopping stations) in order.

        Routes through each consecutive pair: origin->wp1->wp2->...->destination.
        Each segment uses Dijkstra shortest path. If any segment fails,
        that waypoint is skipped and the next is tried.

        Args:
            origin: starting station code
            destination: ending station code
            waypoints: list of station codes that must be visited (in order)
            train_gauge: gauge filter

        Returns:
            list of leg dicts, or None if no path found
        """
        # Filter waypoints to only those reachable in our graph
        valid_wps = [wp for wp in waypoints
                     if wp in self._all_stations and wp != origin and wp != destination]

        if not valid_wps:
            return self.find_route(origin, destination, train_gauge)

        # Build segment chain: origin -> wp1 -> wp2 -> ... -> destination
        checkpoints = [origin] + valid_wps + [destination]
        full_legs = []

        for i in range(len(checkpoints) - 1):
            seg_origin = checkpoints[i]
            seg_dest = checkpoints[i + 1]

            if seg_origin == seg_dest:
                continue

            segment = self.find_route(seg_origin, seg_dest, train_gauge)

            if segment is None:
                # Waypoint unreachable - skip it and try direct to next
                continue

            # Append segment legs, avoiding duplicate station at junction points
            if full_legs and segment:
                # The last leg of previous segment and first leg of this segment
                # share the same station - skip the duplicate
                segment = segment[1:]

            full_legs.extend(segment)

        if not full_legs:
            # Fallback: direct route ignoring waypoints
            return self.find_route(origin, destination, train_gauge)

        # Verify origin and destination
        if full_legs[0]['station'] != origin or full_legs[-1]['station'] != destination:
            return self.find_route(origin, destination, train_gauge)

        return self._enrich_route(full_legs)

    def _make_leg(self, station, block_section, distance_km):
        """Create a minimal leg dict compatible with schedule_engine."""
        stn_data = self.stations.get(station, {})
        bs_data = self.block_sections.get(block_section, {})
        return {
            'station': station,
            'block_section': block_section,
            'coa_block_section': block_section,
            'distance_km': distance_km,
            'stoppage_time': 0,
            'comm_stoppage_time': 0,
            'platform': '',
            'zone': stn_data.get('division', ''),
            'division': stn_data.get('division', ''),
            'bs_zone': bs_data.get('division', ''),
            'bs_division': bs_data.get('division', ''),
            'class_flag': stn_data.get('class_flag', ''),
            'reporting_flag': 'Y',
            'station_line': '',
            'bs_line': '',
            'block_busy_days': '',
            'traction_code': '',
            'crew_change': 'N',
            'loco_change': 'N',
            'ref_runtime': 0,
            'ref_acc_time': 0,
            'ref_dec_time': 0,
            'ref_traffic_allowance': 0,
            'ref_engg_allowance': 0,
            'ref_max_speed': 0,
            'ref_bs_speed': bs_data.get('max_speed_kph', 0),
            'ref_train_mps': 0,
            'ref_constraint_time': 0,
            'ref_arrival': 0,
            'ref_departure': 0,
        }

    def _enrich_route(self, legs):
        # Add cumulative distance and sequence numbers
        cum_dist = 0
        for i, leg in enumerate(legs):
            leg['seq'] = i + 1
            leg['cum_distance'] = cum_dist
            cum_dist += leg.get('distance_km', 0)
        return legs

    def can_reach(self, origin, destination):
        # Quick reachability check using BFS (no cost computation)
        if origin not in self._all_stations or destination not in self._all_stations:
            return False
        if origin == destination:
            return True
        visited = {origin}
        queue = [origin]
        while queue:
            next_queue = []
            for node in queue:
                for edge in self._graph.get(node, []):
                    nbr = edge['to']
                    if nbr == destination:
                        return True
                    if nbr not in visited:
                        visited.add(nbr)
                        next_queue.append(nbr)
            queue = next_queue
        return False


def build_train_stoppage_maps(routes):
    """
    Build per-train stoppage maps from reference route data.

    Returns dict: train_id -> {station_code: stoppage_time_seconds}
    Only includes stations where the train actually stops (stoppage > 0).
    """
    train_maps = {}
    for tid, legs in routes.items():
        stn_map = {}
        for i, leg in enumerate(legs):
            stp = leg.get('stoppage_time', 0)
            if stp > 0 and i > 0 and i < len(legs) - 1:
                stn_map[leg['station']] = stp
        if stn_map:
            train_maps[tid] = stn_map
    return train_maps


def determine_stoppages(route, stoppage_model, stations_data,
                        is_junction_fn=None, train_stoppage_map=None):
    """
    Determine which stations in a route should have stoppages (and for how long).

    Rules (in priority order):
    1. Origin (first station): stoppage = 0 (departs immediately)
    2. Destination (last station): stoppage = 0 (terminates)
    3. Train-specific stoppage map (exact per-station times from reference): highest priority
    4. Stations with a stoppage entry in stoppage_model (generic median): fallback
    5. Junction stations (degree >= 3 in network, or is_junction flag): 120s default
    6. All others: 0 (pass-through)

    Args:
        route: list of leg dicts (as returned by RouteFinder.find_route)
        stoppage_model: dict station_code -> median stoppage seconds
        stations_data: dict station_code -> station info
        is_junction_fn: optional callable(station_code) -> bool
        train_stoppage_map: optional dict station_code -> stoppage seconds
                           (train-specific, from reference route data)

    Returns:
        route with stoppage_time updated in-place
    """
    if not route:
        return route

    for i, leg in enumerate(route):
        stn = leg['station']
        is_first = (i == 0)
        is_last = (i == len(route) - 1)

        if is_first or is_last:
            leg['stoppage_time'] = 0
            continue

        # Priority 1: Train-specific stoppage from reference data
        if train_stoppage_map and stn in train_stoppage_map:
            leg['stoppage_time'] = train_stoppage_map[stn]
            continue

        # Priority 2: Generic station stoppage model (per-station median)
        if stoppage_model and stn in stoppage_model:
            model_val = stoppage_model[stn]
            if model_val > 0:
                leg['stoppage_time'] = model_val
                continue

        # Priority 3: Junction stations get a default 120s stop
        is_junc = False
        if is_junction_fn:
            is_junc = is_junction_fn(stn)
        elif stations_data:
            stn_info = stations_data.get(stn, {})
            is_junc = stn_info.get('is_junction', False)

        if is_junc:
            leg['stoppage_time'] = 120
        else:
            leg['stoppage_time'] = 0

    return route
