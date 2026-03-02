"""
Schedule generation engine.
Generates a complete primal schedule for trains by traversing
routes and computing timings, with inter-train conflict resolution
ensuring no two trains occupy the same block section or platform
at the same time.
"""

from runtime_calc import calculate_runtime
from conflict_resolver import ResourceTracker

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
    """Return departure_time for sorting (all trains equal priority, FCFS)."""
    return train_props.get('departure_time', 0)


def generate_single_train(train_props, route, block_sections,
                          use_reference=False, resource_tracker=None):
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

    Returns:
        list of dicts, each representing one row of the output schedule
    """
    if not route:
        return []

    proposal_id = train_props['proposal_id']
    departure_time = train_props.get('departure_time', 0)

    schedule_rows = []
    current_time = departure_time

    for i, leg in enumerate(route):
        is_last = (i == len(route) - 1)
        station = leg['station']
        block_section_id = leg['block_section']
        stoppage = leg.get('stoppage_time', 0)

        # Arrival at this station
        arrival_time = current_time

        # Departure = arrival + stoppage
        departure_from_station = arrival_time + stoppage

        # --- Platform conflict check ---
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

        # --- Block section conflict check ---
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
            'MAVSTTNLINE': leg.get('station_line', ''),
            'MAVPFDRTN': '',
            'MAVSTTNLINE_NEW': '',
            'MAVPFDRTN_NEW': '',
            'MANNOTIFICATIONFLAG': 0,
            'MACCLASSFLAG': leg.get('class_flag', ''),
            'MACREPORTINGFLAG': leg.get('reporting_flag', 'Y'),
            'MAVBLCKSCTNLINE': leg.get('bs_line', ''),
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
                        resolve_conflicts=True):
    """
    Generate schedules for multiple trains with conflict resolution.

    Trains are processed in priority order (Rajdhani first, then Shatabdi,
    then Express, etc.). Higher-priority trains get their preferred slots;
    lower-priority trains are delayed if they conflict.

    Parameters:
        trains: dict of train properties keyed by proposal_id
        routes: dict of routes keyed by proposal_id
        block_sections: dict of block sections
        use_reference: if True, use reference runtimes
        train_ids: optional list of proposal_ids to generate (None = all)
        progress_callback: optional function(current, total) for progress reporting
        resolve_conflicts: if True, enforce no two trains on same resource at same time

    Returns:
        tuple: (all_rows, generated_count, skipped_count, conflict_stats)
    """
    if train_ids is None:
        train_ids = list(routes.keys())

    # Filter to valid trains
    valid_ids = [pid for pid in train_ids if pid in trains and pid in routes]
    skipped = len(train_ids) - len(valid_ids)

    # Sort by priority: higher-priority trains get scheduled first
    valid_ids.sort(key=lambda pid: get_train_priority(trains[pid]))

    # Initialize resource tracker for conflict resolution
    tracker = ResourceTracker(block_sections) if resolve_conflicts else None

    all_rows = []
    total = len(valid_ids)
    generated = 0

    for idx, pid in enumerate(valid_ids):
        train_props = trains[pid]
        route = routes[pid]
        rows = generate_single_train(
            train_props, route, block_sections,
            use_reference=use_reference,
            resource_tracker=tracker,
        )
        all_rows.extend(rows)
        generated += 1

        if progress_callback and (idx + 1) % 100 == 0:
            progress_callback(idx + 1, total)

    conflict_stats = tracker.get_stats() if tracker else {}
    return all_rows, generated, skipped, conflict_stats
