"""
Schedule generation engine.
Generates a complete primal schedule for trains by traversing
routes and computing timings, with inter-train conflict resolution
ensuring no two trains occupy the same block section or platform
at the same time, and dynamic line selection at stations.
"""

from runtime_calc import calculate_runtime
from conflict_resolver import ResourceTracker
from line_selector import LineSelector
from route_finder import RouteFinder, determine_stoppages, build_train_stoppage_maps

SECONDS_IN_A_DAY = 86400

# Train type priority: lower number = higher priority (scheduled first)
TRAIN_TYPE_PRIORITY = {
    'RAJ': 1, 'RJDH': 1,            # Rajdhani
    'SHT': 2, 'SHTB': 2,            # Shatabdi
    'DUR': 3, 'DRNT': 3,            # Duronto
    'VB': 4, 'VNDB': 4,             # Vande Bharat
    'SF': 5, 'SFEX': 5,             # Superfast Express
    'EXP': 6, 'MAIL': 6,            # Express / Mail
    'PEXP': 7,                       # Parcel Express
    'PASS': 8, 'PSGR': 8,           # Passenger
    'DMU': 9, 'DEMU': 9, 'MEMU': 9, # DMU/DEMU/MEMU
    'TOD': 10,                       # Tourist
    'GDS': 11, 'GOODS': 11, 'FGHT': 11,  # Goods / Freight
}
DEFAULT_PRIORITY = 6


def compute_day_of_run(time_seconds):
    """Compute day of run from cumulative seconds (Day 1 starts at 0)."""
    if time_seconds < 0:
        return 1
    return (time_seconds // SECONDS_IN_A_DAY) + 1


def get_train_priority(train_props):
    """
    Sort key for train scheduling order.
    Primary: departure time (FCFS). Tiebreaker: train type priority
    (Rajdhani before Passenger when both depart at the same time).
    """
    dep = train_props.get('departure_time', 0)
    ttype = train_props.get('train_type', '')
    prio = TRAIN_TYPE_PRIORITY.get(ttype, DEFAULT_PRIORITY)
    return (dep, prio)


def generate_single_train(train_props, route, block_sections,
                          use_reference=False, resource_tracker=None,
                          start_time_override=None, stoppage_model=None,
                          line_selector=None):
    """
    Generate a complete schedule for a single train.

    When resource_tracker is provided, checks block section and platform
    availability before finalizing times. If a conflict is detected,
    the train is delayed at that point (and the delay cascades forward).

    Parameters:
        train_props: dict with train properties from train_master
        route: list of dicts, each representing one leg (from train_routes.json)
        block_sections: dict of all block sections (keyed by block_section_id)
        use_reference: if True, use reference runtimes from existing schedule
        resource_tracker: optional ResourceTracker for conflict resolution
        start_time_override: optional int, overrides train's departure time (seconds)
        stoppage_model: optional dict mapping station_code -> median stoppage (seconds).
                        When provided in compute mode, uses derived stoppages instead
                        of reference stoppages from route data.

    Returns:
        list of dicts, each representing one row of the output schedule
    """
    if not route:
        return []

    proposal_id = train_props['proposal_id']
    if start_time_override is not None:
        departure_time = start_time_override
    else:
        departure_time = train_props.get('departure_time', 0)

    schedule_rows = []
    current_time = departure_time

    for i, leg in enumerate(route):
        is_last = (i == len(route) - 1)
        station = leg['station']
        block_section_id = leg['block_section']

        # Determine stoppage: use the route's embedded stoppage_time
        # (already set correctly by determine_stoppages with train-specific maps)
        stoppage = leg.get('stoppage_time', 0)

        # Arrival at this station
        arrival_time = current_time

        # Departure = arrival + stoppage
        departure_from_station = arrival_time + stoppage

        # If platform is occupied, delay departure (not arrival) to preserve cross-row invariant
        platform = leg.get('platform', '')
        if resource_tracker and platform and stoppage > 0:
            # Reserve platform from arrival to departure; if occupied, find earliest free slot
            actual_arrival = resource_tracker.check_and_reserve_platform(
                station, platform, arrival_time, stoppage, proposal_id
            )
            if actual_arrival > arrival_time:
                # Can't change arrival (cross-row invariant), so add delay to stoppage
                extra_wait = actual_arrival - arrival_time
                stoppage += extra_wait
                departure_from_station = arrival_time + stoppage

        # Get block section data
        bs_data = block_sections.get(block_section_id, {})

        # Determine stop flags for acc/dec calculation
        has_prev_stop = False
        if i > 0 and route[i].get('stoppage_time', 0) > 0:
            has_prev_stop = True

        has_next_stop = False
        if not is_last and i + 1 < len(route) and route[i + 1].get('stoppage_time', 0) > 0:
            has_next_stop = True

        # Calculate runtime for this block section
        if is_last:
            runtime_result = {
                'runtime': 0, 'acc_time': 0, 'dec_time': 0,
                'base_runtime': 0, 'effective_speed': 0,
            }
        else:
            ref_rt = leg.get('ref_runtime', 0) if use_reference else None
            runtime_result = calculate_runtime(
                train_props, bs_data, has_prev_stop, has_next_stop,
                use_reference=use_reference, ref_runtime=ref_rt,
            )

        runtime = runtime_result['runtime']

        # Block section conflict check
        if resource_tracker and block_section_id and runtime > 0:
            actual_departure = resource_tracker.check_and_reserve_block_section(
                block_section_id, departure_from_station, runtime, proposal_id
            )
            # If delayed, update departure (arrival stays, extra wait at station)
            if actual_departure > departure_from_station:
                extra_wait = actual_departure - departure_from_station
                stoppage += extra_wait
                departure_from_station = actual_departure

        next_arrival = departure_from_station + runtime

        # Line selection
        # In reference mode, use the line from route data.
        # In compute mode with line_selector, dynamically select lines.
        if line_selector and not use_reference:
            bs_in = route[i - 1]['block_section'] if i > 0 else ''
            bs_out = block_section_id
            selected_stn_line = line_selector.select_station_line(
                station, bs_in, bs_out, arrival_time, departure_from_station
            )
            selected_bs_line = ''
            if block_section_id and runtime > 0:
                selected_bs_line = line_selector.select_bs_line(
                    block_section_id, departure_from_station, next_arrival
                )
        else:
            selected_stn_line = leg.get('station_line', '')
            selected_bs_line = leg.get('bs_line', '')

        # Day of run
        day_of_run = compute_day_of_run(arrival_time)

        # Distance data
        distance_km = leg.get('distance_km', 0) or bs_data.get('distance_km', 0)
        cum_distance = leg.get('cum_distance', 0)

        # Speed values
        bs_speed = bs_data.get('max_speed_kph', 0)
        train_mps = train_props.get('max_speed_kph', 0)
        if runtime > 0 and distance_km > 0:
            eff_max_speed = round(distance_km / runtime * 3600)
        else:
            eff_max_speed = 0

        # Allowances
        trf_allowance = bs_data.get('traffic_allowance', 0)
        eng_allowance = bs_data.get('engineering_allowance', 0)
        if use_reference:
            trf_allowance = leg.get('ref_traffic_allowance', 0)
            eng_allowance = leg.get('ref_engg_allowance', 0)

        constraint_time = leg.get('ref_constraint_time', 0) if use_reference else 0

        row = {
            'MAVPROPOSALID': proposal_id,
            'MANSEQNUMBER': leg['seq'],
            'MAVSTTNCODE': station,
            'MAVBLCKSCTN': block_section_id if not is_last else '',
            'MAVCOABLCKSCTN': leg.get('coa_block_section', block_section_id) if not is_last else '',
            'MANWTTARVL': arrival_time,
            'MANWTTDPRT': departure_from_station,
            'MANWTTNEXTARVL': next_arrival if not is_last else arrival_time,
            'MANWTTDAYOFRUN': day_of_run,
            'MANPTTARVL': 0,
            'MANPTTDPRT': 0,
            'MANPTTDAYOFRUN': 0,
            'MANRUNTIME': runtime,
            'MANSTPGTIME': stoppage,
            'MANCSTPGTIME': leg.get('comm_stoppage_time', 0),
            'MANACCTIME': runtime_result['acc_time'],
            'MANDECTIME': runtime_result['dec_time'],
            'MANTRFCALWC': trf_allowance,
            'MANENGGALWC': eng_allowance,
            'MANSTARTBUFFER': 0,
            'MANENDBUFFER': 0,
            'MANCONSTRAINTTIME': constraint_time,
            'MAVCONSTRAINTREASON': '',
            'MANINTRDIST': distance_km,
            'MANCUMDISTANCE': cum_distance,
            'MANMAXSPEED': eff_max_speed,
            'MANBSSPEED': bs_speed if not is_last else 0,
            'MANTRAINMPS': train_mps,
            'MAVPLATFORMNUMB': leg.get('platform', ''),
            'MAVZONECODE': leg.get('zone', ''),
            'MAVDVSNCODE': leg.get('division', ''),
            'MAVBLCKSCTNZONE': leg.get('bs_zone', ''),
            'MAVBLCKSCTNDVSN': leg.get('bs_division', ''),
            'MANZONEIC': 0,
            'MANDVSNIC': 0,
            'MAVMDFYBY': '',
            'MADMDFYTIME': '',
            'MAVPFREASON': '',
            'MAVBLCKBUSYDAYS': leg.get('block_busy_days', ''),
            'MAVCROSSINGFLAG': 'N',
            'MAVCROSSINGTRAIN': '',
            'MAVCROSSINGTIME': '',
            'MACRVSLSTTN': 'N',
            'MANRVSLTIME': 0,
            'MACCREWCHNG': leg.get('crew_change', 'N'),
            'MAVCREWCHNGCODE': '',
            'MACLOCOCHANGE': leg.get('loco_change', 'N'),
            'MAVTRTNCODE': leg.get('traction_code', ''),
            'MACGARBG': 'N',
            'MACWATER': 'N',
            'MAVPLATFORMNUMB_NEW': '',
            'MAVSTTNLINE': selected_stn_line,
            'MAVPFDRTN': '',
            'MAVSTTNLINE_NEW': '',
            'MAVPFDRTN_NEW': '',
            'MANNOTIFICATIONFLAG': 0,
            'MACCLASSFLAG': leg.get('class_flag', ''),
            'MACREPORTINGFLAG': leg.get('reporting_flag', 'Y'),
            'MAVBLCKSCTNLINE': selected_bs_line,
            'MANTRAINID': train_props.get('train_id', 0),
            'MAVTRAINNUMBER': train_props.get('train_number', ''),
            'MAVPLATFORMNUMBER_NEW': '',
            'MACHSDFUELING': 'N',
        }
        schedule_rows.append(row)

        # Advance time for next leg
        current_time = next_arrival

    return schedule_rows


def generate_all_trains(trains, routes, block_sections, use_reference=False,
                        train_ids=None, progress_callback=None,
                        resolve_conflicts=True, start_times=None,
                        stoppage_model=None, station_lines=None,
                        block_section_lines=None, line_connections=None,
                        stations=None, discover_routes=False):
    """
    Generate schedules for multiple trains with conflict resolution.

    Trains are processed in departure-time order (first-come-first-served).

    Parameters:
        trains: dict of train properties keyed by proposal_id
        routes: dict of routes keyed by proposal_id
        block_sections: dict of block sections
        use_reference: if True, use reference runtimes
        train_ids: optional list of proposal_ids to generate (None = all)
        progress_callback: optional function(current, total) for progress reporting
        resolve_conflicts: if True, enforce no two trains on same resource at same time
        start_times: optional dict mapping proposal_id -> start_time (seconds)
        stoppage_model: optional dict mapping station_code -> median stoppage (seconds)
        station_lines: optional dict for dynamic line selection
        block_section_lines: optional dict for dynamic line selection
        line_connections: optional dict for dynamic line selection
        stations: optional dict of station data (for route discovery)
        discover_routes: if True, use RouteFinder for trains without pre-defined routes

    Returns:
        tuple: (all_rows, generated_count, skipped_count, conflict_stats)
    """
    if train_ids is None:
        train_ids = list(routes.keys())

    # Build per-train stoppage maps from reference route data.
    # For each reference train, this maps station -> exact stoppage time.
    # When Dijkstra discovers a new route, stations shared with the reference
    # keep their exact stoppage times, while new stations fall back to the
    # generic per-station median model.
    train_stoppage_maps = build_train_stoppage_maps(routes)

    # Extract mandatory waypoints (stopping stations) from reference routes.
    # Forces Dijkstra to pass through every station where the train must stop,
    # while allowing it to find its own shortest path between stops.
    train_waypoints = {}
    for tid, legs in routes.items():
        sorted_legs = sorted(legs, key=lambda x: int(x.get('seq', 0)))
        wps = [l['station'] for l in sorted_legs if l.get('stoppage_time', 0) > 0]
        if wps:
            train_waypoints[tid] = wps

    # Initialize route finder for trains without pre-defined routes
    route_finder = None
    discovered_routes = {}
    if discover_routes:
        route_finder = RouteFinder(block_sections, line_connections, stations)

    # Filter: train must be in trains dict, and either have a route or be discoverable
    valid_ids = []
    skipped = 0
    for pid in train_ids:
        if pid not in trains:
            skipped += 1
            continue
        if pid in routes:
            valid_ids.append(pid)
        elif route_finder:
            t = trains[pid]
            origin = t.get('origin', '')
            dest = t.get('destination', '')
            if origin and dest:
                # Use waypoint routing if the train has known stopping stations
                waypoints = train_waypoints.get(pid)
                if waypoints:
                    found = route_finder.find_route_via_waypoints(
                        origin, dest, waypoints, t.get('gauge', 'B')
                    )
                else:
                    found = route_finder.find_route(origin, dest, t.get('gauge', 'B'))
                if found:
                    # Apply stoppages: train-specific map first, then generic model
                    determine_stoppages(
                        found, stoppage_model, stations or {},
                        train_stoppage_map=train_stoppage_maps.get(pid)
                    )
                    discovered_routes[pid] = found
                    valid_ids.append(pid)
                else:
                    skipped += 1
            else:
                skipped += 1
        else:
            skipped += 1

    # Sort by departure time (first-come-first-served)
    valid_ids.sort(key=lambda pid: get_train_priority(trains[pid]))

    # Initialize resource tracker for conflict resolution
    tracker = ResourceTracker(block_sections) if resolve_conflicts else None

    # Initialize line selector for dynamic line assignment
    lselector = None
    if station_lines and line_connections and not use_reference:
        lselector = LineSelector(
            station_lines, block_section_lines or {}, line_connections
        )

    all_rows = []
    total = len(valid_ids)
    generated = 0

    for idx, pid in enumerate(valid_ids):
        train_props = trains[pid]
        route = routes.get(pid) or discovered_routes.get(pid, [])
        override = start_times.get(pid) if start_times else None
        rows = generate_single_train(
            train_props, route, block_sections,
            use_reference=use_reference,
            resource_tracker=tracker,
            start_time_override=override,
            stoppage_model=stoppage_model,
            line_selector=lselector,
        )
        all_rows.extend(rows)
        generated += 1

        if progress_callback and (idx + 1) % 100 == 0:
            progress_callback(idx + 1, total)

    conflict_stats = tracker.get_stats() if tracker else {}
    return all_rows, generated, skipped, conflict_stats
