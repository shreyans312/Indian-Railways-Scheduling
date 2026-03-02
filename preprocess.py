#!/usr/bin/env python3
"""
Preprocessing script for Indian Railway Primal Timetable Generator.

Reads all raw CSV data files and extracts constant/static data into
efficient JSON lookup structures for use by the schedule generator.

This is a ONE-TIME preprocessing step. The outputs are stored in
the `preprocessed_data/` directory.

Usage:
    python3 preprocess.py
"""

import csv
import json
import os
import sys
import math
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = ROOT_DIR / "preprocessed_data"

# Input file paths
FILES = {
    "train_master":      ROOT_DIR / "Copy of 01_TrainMaster_10_Dec_2024.csv",
    "station":           ROOT_DIR / "Copy of 03_Station_10_Dec_2024.csv",
    "block_section":     ROOT_DIR / "Copy of 04_BlockSctn_10_Dec_2024.csv",
    "station_line":      ROOT_DIR / "Copy of 05_StationLine_10_Dec_2024.csv",
    "platform":          ROOT_DIR / "Copy of 06_Platform_10_Dec_2024.csv",
    "block_sctn_line":   ROOT_DIR / "Copy of 07_BlockSctnLine_10_Dec_2024.csv",
    "line_connection":   ROOT_DIR / "Copy of 08_LineConnection_10_Dec_2024.csv",
    "station_position":  ROOT_DIR / "Copy of 09_StationPosition_10_Dec_2024.csv",
    "curvature":         ROOT_DIR / "Copy of 11_Curvature_10_Dec_2024.csv",
    "speed_restriction": ROOT_DIR / "Copy of 12_SpeedRestrictions_10_Dec_2024.csv",
    "block_corridor":    ROOT_DIR / "Copy of 13_BlockCorridor_10_Dec_2024.csv",
    "train_schedule":    ROOT_DIR / "Train_Schedule.csv",
}


def safe_float(val, default=0.0):
    """Convert to float, returning default on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """Convert to int, returning default on failure."""
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def read_csv(filepath, encoding='utf-8-sig'):
    """Read CSV file and return list of dicts. Uses utf-8-sig to strip BOM."""
    for enc in [encoding, 'utf-8', 'latin1']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                return list(reader)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Cannot read {filepath} with any encoding")


def preprocess_stations(rows):
    """Extract station lookup from 03_Station data."""
    stations = {}
    for row in rows:
        code = row.get('MAVSTTNCODE', '').strip()
        if not code:
            continue
        stations[code] = {
            'code': code,
            'name': row.get('MAVSTTNNAME', '').strip(),
            'division': row.get('MAVDVSNCODE', '').strip(),
            'class_flag': row.get('MACCLASSFLAG', '').strip(),
            'is_junction': row.get('MACJUNCTION', 'N').strip() == 'Y',
            'is_halt': row.get('MACHALTFLAG', 'N').strip() == 'Y',
            'latitude': safe_float(row.get('MANLATITUDE')),
            'longitude': safe_float(row.get('MANLONGITUDE')),
            'traffic_type': row.get('MAVTRAFFICTYPE', '').strip(),
            'traction_change': row.get('MACTRTNCHNG', 'N').strip() == 'Y',
            'crew_change': row.get('MACCREWCHNG', 'N').strip() == 'Y',
            'interlock_std': row.get('MAVINTRLOCKSTD', '').strip(),
            'signal_arrangement': row.get('MAVSGNLARRNGMENT', '').strip(),
            'state_code': row.get('MAVSTATECODE', '').strip(),
            'start_buffer': safe_int(row.get('MANSTARTBUFFER')),
            'end_buffer': safe_int(row.get('MANENDBUFFER')),
        }
    return stations


def preprocess_block_sections(rows):
    """Extract block section lookup from 04_BlockSctn data."""
    sections = {}
    for row in rows:
        bs_id = row.get('MAVBLCKSCTN', '').strip()
        if not bs_id:
            continue
        sections[bs_id] = {
            'id': bs_id,
            'from_station': row.get('MAVFROMSTTNCODE', '').strip(),
            'to_station': row.get('MAVTOSTTNCODE', '').strip(),
            'subsection_name': row.get('MAVSUBSCTNNAME', '').strip(),
            'distance_km': safe_float(row.get('MANINTRDIST')),
            'num_lines': safe_int(row.get('MANNUMBLINES')),
            'num_signals': safe_int(row.get('MANNUMBSGNL')),
            'num_level_crossings': safe_int(row.get('MANNUMBLVLCRSG')),
            'signal_type': row.get('MAVSGNLTYPE', '').strip(),
            'gauge': row.get('MAVGAUGE', '').strip(),
            'traction_type': row.get('MAVTRTNTYPE', '').strip(),
            'division': row.get('MAVDVSNCODE', '').strip(),
            'max_speed_kph': safe_int(row.get('MANMAXSPEED')),
            'direction': row.get('MAVDRTN', '').strip(),
            'section_code': row.get('MAVSCTNCODE', '').strip(),
            'traffic_type': row.get('MAVTRAFFICTYPE', '').strip(),
            'rbs_distance': safe_float(row.get('MANRBSDISTANCE')),
            'icms_distance': safe_float(row.get('MANICMSINTRDIST')),
            # Will be augmented with curvature and speed restriction data
            'curvature_time_loss_psgr': 0,
            'curvature_time_loss_goods': 0,
            'speed_restrictions': [],
            'speed_restriction_time_loss_psgr': 0,
            'speed_restriction_time_loss_goods': 0,
        }
    return sections


def preprocess_curvature(rows, block_sections):
    """Aggregate curvature time loss per block section and attach to block_sections."""
    curvature_agg = defaultdict(lambda: {'psgr': 0, 'goods': 0})
    for row in rows:
        bs = row.get('BLCKSCTN', '').strip()
        if not bs:
            continue
        curvature_agg[bs]['psgr'] += safe_int(row.get('TIMELOSSPSGR'))
        curvature_agg[bs]['goods'] += safe_int(row.get('TIMELOSSGOODS'))

    augmented = 0
    for bs_id, losses in curvature_agg.items():
        if bs_id in block_sections:
            block_sections[bs_id]['curvature_time_loss_psgr'] = losses['psgr']
            block_sections[bs_id]['curvature_time_loss_goods'] = losses['goods']
            augmented += 1

    print(f"  Curvature: {len(curvature_agg)} block sections aggregated, {augmented} attached to graph")
    return block_sections


def preprocess_speed_restrictions(rows, block_sections):
    """Attach speed restrictions to block sections."""
    restriction_agg = defaultdict(lambda: {'restrictions': [], 'psgr_loss': 0, 'goods_loss': 0})
    for row in rows:
        bs = row.get('BLCKSCTN', '').strip()
        if not bs:
            continue
        restriction = {
            'from_km': safe_float(row.get('FROMKM')),
            'to_km': safe_float(row.get('TOKM')),
            'psgr_speed': safe_int(row.get('PASSPEED')),
            'goods_speed': safe_int(row.get('GDSSPEED')),
            'distance': safe_float(row.get('DISTANCE')),
            'reason': row.get('REASON', '').strip(),
            'status': row.get('STATUS', '').strip(),
        }
        restriction_agg[bs]['restrictions'].append(restriction)
        restriction_agg[bs]['psgr_loss'] += safe_int(row.get('TIMELOSSPSGR'))
        restriction_agg[bs]['goods_loss'] += safe_int(row.get('TIMELOSSGOODS'))

    augmented = 0
    for bs_id, data in restriction_agg.items():
        if bs_id in block_sections:
            block_sections[bs_id]['speed_restrictions'] = data['restrictions']
            block_sections[bs_id]['speed_restriction_time_loss_psgr'] = data['psgr_loss']
            block_sections[bs_id]['speed_restriction_time_loss_goods'] = data['goods_loss']
            augmented += 1

    print(f"  Speed restrictions: {len(restriction_agg)} block sections, {augmented} attached")
    return block_sections


def preprocess_station_lines(rows):
    """Extract station line data from 05_StationLine."""
    station_lines = defaultdict(list)
    for row in rows:
        code = row.get('MAVSTTNCODE', '').strip()
        if not code:
            continue
        station_lines[code].append({
            'seq': safe_int(row.get('MANSEQNUMB')),
            'line_number': row.get('MAVLINENUMB', '').strip(),
            'line_type': row.get('MAVLINETYPE', '').strip(),
            'line_category': row.get('MACLINECATEGORY', '').strip(),
            'line_length': safe_int(row.get('MANLINELENGTH')),
            'direction': row.get('MAVDRTN', '').strip(),
            'capacity': safe_int(row.get('MANCAPACITY')),
            'gauge': row.get('MACGAUGE', '').strip(),
            'traction_type': row.get('MACTRTNTYPE', '').strip(),
            'line_name': row.get('MAVLINENAME', '').strip(),
            'line_speed': safe_int(row.get('MANLINESPEED')),
            'has_platform': row.get('MACPLATFORM', 'N').strip() == 'Y',
        })
    return dict(station_lines)


def preprocess_platforms(rows):
    """Extract platform data from 06_Platform."""
    platforms = defaultdict(list)
    for row in rows:
        code = row.get('MAVSTTNCODE', '').strip()
        if not code:
            continue
        platforms[code].append({
            'seq': safe_int(row.get('MANSEQNUMB')),
            'platform_number': row.get('MAVPLATFORMNUMB', '').strip(),
            'v_position': row.get('MAVPFVPOSITION', '').strip(),
            'h_position': row.get('MAVPFHPOSITION', '').strip(),
            'length': safe_int(row.get('MANLENGTH')),
            'pf_type': row.get('MAVPFTYPE', '').strip(),
            'capacity': safe_int(row.get('MANCAPACITY')),
        })
    return dict(platforms)


def preprocess_block_sctn_lines(rows):
    """Extract block section line data from 07_BlockSctnLine."""
    bs_lines = defaultdict(list)
    for row in rows:
        bs = row.get('MAVBLCKSCTN', '').strip()
        if not bs:
            continue
        bs_lines[bs].append({
            'seq': safe_int(row.get('MANSEQNUMB')),
            'line_number': row.get('MAVLINENUMB', '').strip(),
            'line_length': safe_float(row.get('MANLINELENGTH')),
            'line_category': row.get('MAVLINECATEGORY', '').strip(),
            'max_speed': safe_int(row.get('MANMAXSPEED')),
            'direction': row.get('MAVDRTN', '').strip(),
        })
    return dict(bs_lines)


def preprocess_line_connections(rows):
    """Extract line connection data from 08_LineConnection."""
    connections = defaultdict(list)
    for row in rows:
        code = row.get('MAVSTTNCODE', '').strip()
        if not code:
            continue
        connections[code].append({
            'station_line': row.get('MANSTTNLINENUMB', '').strip(),
            'block_section': row.get('MAVBLCKSCTN', '').strip(),
            'bs_line': row.get('MANBSLINENUMB', '').strip(),
            'recv_send_flag': row.get('MACRECVSENDFLAG', '').strip(),
        })
    return dict(connections)


def preprocess_block_corridors(rows):
    """Extract block corridor data from 13_BlockCorridor."""
    corridors = []
    for row in rows:
        bs = row.get('BLCKSCTN', '').strip()
        if not bs:
            continue
        corridors.append({
            'block_section': bs,
            'seq': safe_int(row.get('SEQNUMBER')),
            'from_time': safe_int(row.get('FROMTIME')),
            'to_time': safe_int(row.get('TOTIME')),
            'from_date': row.get('MADFROMDATE', '').strip(),
            'to_date': row.get('MADTODATE', '').strip(),
            'days_of_service': row.get('DAYSOFSRVC', '').strip(),
            'status': row.get('STATUS', '').strip(),
            'perm_temp': row.get('PERMTEMPFLAG', '').strip(),
        })
    return corridors


def preprocess_train_master(rows):
    """Clean and extract train master data from 01_TrainMaster."""
    trains = {}
    for row in rows:
        pid = row.get('MAVPROPOSALID', '').strip()
        if not pid:
            continue
        trains[pid] = {
            'proposal_id': pid,
            'train_id': safe_int(row.get('MANTRAINID')),
            'train_number': row.get('MAVTRAINNUMBER', '').strip(),
            'train_name': row.get('MAVTRAINNAME', '').strip(),
            'train_type': row.get('MAVTRAINTYPE', '').strip(),
            'train_subtype': row.get('MAVTRAINSUBTYPE', '').strip(),
            'origin': row.get('MAVORIG', '').strip(),
            'destination': row.get('MAVDSTN', '').strip(),
            'departure_time': safe_int(row.get('MANDPRTTIME')),
            'arrival_time': safe_int(row.get('MANARVLTIME')),
            'max_speed_kph': safe_int(row.get('MANMPS')),
            'gauge': row.get('MACGAUGE', '').strip(),
            'traction_type': row.get('MACTRTNTYPE', '').strip(),
            'train_group': row.get('MACTRAINGROUP', '').strip(),
            'rake_type': row.get('MAVRAKETYPE', '').strip(),
            'loco_type': row.get('MAVLOCOTYPE', '').strip(),
            'num_coaches': safe_int(row.get('MANNOOFCOACH')),
            'days_of_service': row.get('MAVDAYSOFSRVC', '').strip(),
            'frequency': safe_int(row.get('MANFREQUENCY')),
            'total_distance': safe_float(row.get('MANDISTANCE')),
            'total_traffic_allowance': safe_int(row.get('MANTRFCALWC')),
            'total_engg_allowance': safe_int(row.get('MANENGGALWC')),
            'total_stoppage': safe_int(row.get('MANSTOPPAGE')),
            'total_runtime': safe_int(row.get('MANTOTALRUNTIME')),
            'total_constraint_time': safe_int(row.get('MANTOTALCONSTRAINTTIME')),
            'total_acc_time': safe_int(row.get('MANTOTALACCTIME')),
            'total_dec_time': safe_int(row.get('MANTOTALDECTIME')),
            'owning_railway': row.get('MAVTRAINOWNGRLY', '').strip(),
            'owning_division': row.get('MAVTRAINOWNGDVSN', '').strip(),
            'brake_type': row.get('MACBRAKETYPE', '').strip(),
            'up_dn_flag': row.get('MACUPDNFLAG', '').strip(),
            'src_state': row.get('MAVSRCSTATE', '').strip(),
            'dstn_state': row.get('MAVDSTNSTATE', '').strip(),
            'financial_year': row.get('MAVFINANCIALYEAR', '').strip(),
        }
    return trains


def preprocess_train_routes(rows):
    """
    Extract train routes from Train_Schedule.csv.
    This is the most critical constant data — it defines the station-by-station
    path each train takes through the network.
    """
    routes = defaultdict(list)
    for row in rows:
        pid = row.get('MAVPROPOSALID', '').strip()
        if not pid:
            continue
        routes[pid].append({
            'seq': safe_int(row.get('MANSEQNUMBER')),
            'station': row.get('MAVSTTNCODE', '').strip(),
            'block_section': row.get('MAVBLCKSCTN', '').strip(),
            'coa_block_section': row.get('MAVCOABLCKSCTN', '').strip(),
            'stoppage_time': safe_int(row.get('MANSTPGTIME')),
            'comm_stoppage_time': safe_int(row.get('MANCSTPGTIME')),
            'distance_km': safe_float(row.get('MANINTRDIST')),
            'cum_distance': safe_float(row.get('MANCUMDISTANCE')),
            'platform': row.get('MAVPLATFORMNUMB', '').strip(),
            'zone': row.get('MAVZONECODE', '').strip(),
            'division': row.get('MAVDVSNCODE', '').strip(),
            'bs_zone': row.get('MAVBLCKSCTNZONE', '').strip(),
            'bs_division': row.get('MAVBLCKSCTNDVSN', '').strip(),
            'class_flag': row.get('MACCLASSFLAG', '').strip(),
            'reporting_flag': row.get('MACREPORTINGFLAG', '').strip(),
            'station_line': row.get('MAVSTTNLINE', '').strip(),
            'bs_line': row.get('MAVBLCKSCTNLINE', '').strip(),
            'block_busy_days': row.get('MAVBLCKBUSYDAYS', '').strip(),
            'traction_code': row.get('MAVTRTNCODE', '').strip(),
            'crew_change': row.get('MACCREWCHNG', 'N').strip(),
            'loco_change': row.get('MACLOCOCHANGE', 'N').strip(),
            # Reference values from the original schedule
            'ref_runtime': safe_int(row.get('MANRUNTIME')),
            'ref_acc_time': safe_int(row.get('MANACCTIME')),
            'ref_dec_time': safe_int(row.get('MANDECTIME')),
            'ref_traffic_allowance': safe_int(row.get('MANTRFCALWC')),
            'ref_engg_allowance': safe_int(row.get('MANENGGALWC')),
            'ref_max_speed': safe_int(row.get('MANMAXSPEED')),
            'ref_bs_speed': safe_int(row.get('MANBSSPEED')),
            'ref_train_mps': safe_int(row.get('MANTRAINMPS')),
            'ref_constraint_time': safe_int(row.get('MANCONSTRAINTTIME')),
            'ref_arrival': safe_int(row.get('MANWTTARVL')),
            'ref_departure': safe_int(row.get('MANWTTDPRT')),
        })

    # Sort each route by sequence number
    for pid in routes:
        routes[pid].sort(key=lambda x: x['seq'])

    return dict(routes)


def derive_train_props_from_routes(schedule_rows, routes):
    """
    Build synthetic train properties for trains that appear in
    Train_Schedule.csv but not in TrainMaster. Uses the first and last
    rows of each train's schedule to derive origin, destination, times, etc.
    """
    # Group raw schedule rows by proposal ID to extract train-level fields
    train_groups = defaultdict(list)
    for row in schedule_rows:
        pid = row.get('MAVPROPOSALID', '').strip()
        if pid:
            train_groups[pid].append(row)

    derived = {}
    for pid, rows in train_groups.items():
        rows.sort(key=lambda r: safe_int(r.get('MANSEQNUMBER', 0)))
        first = rows[0]
        last = rows[-1]
        derived[pid] = {
            'proposal_id': pid,
            'train_id': safe_int(first.get('MANTRAINID')),
            'train_number': first.get('MAVTRAINNUMBER', '').strip(),
            'train_name': '',
            'train_type': '',
            'train_subtype': '',
            'origin': first.get('MAVSTTNCODE', '').strip(),
            'destination': last.get('MAVSTTNCODE', '').strip(),
            'departure_time': safe_int(first.get('MANWTTDPRT')),
            'arrival_time': safe_int(last.get('MANWTTARVL')),
            'max_speed_kph': safe_int(first.get('MANTRAINMPS')),
            'gauge': '',
            'traction_type': '',
            'train_group': '',
            'rake_type': '',
            'loco_type': '',
            'num_coaches': 0,
            'days_of_service': first.get('MAVBLCKBUSYDAYS', '').strip(),
            'frequency': 0,
            'total_distance': safe_float(last.get('MANCUMDISTANCE')),
            'total_traffic_allowance': 0,
            'total_engg_allowance': 0,
            'total_stoppage': sum(safe_int(r.get('MANSTPGTIME')) for r in rows),
            'total_runtime': sum(safe_int(r.get('MANRUNTIME')) for r in rows),
            'total_constraint_time': 0,
            'total_acc_time': 0,
            'total_dec_time': 0,
            'owning_railway': '',
            'owning_division': '',
            'brake_type': '',
            'up_dn_flag': '',
            'src_state': '',
            'dstn_state': '',
            'financial_year': '',
        }
    return derived


def validate_data(stations, block_sections, trains, routes):
    """Validate cross-references between data structures."""
    print("\n--- Validation ---")
    errors = 0

    # Check block sections reference valid stations
    missing_from = set()
    missing_to = set()
    for bs_id, bs in block_sections.items():
        if bs['from_station'] not in stations:
            missing_from.add(bs['from_station'])
        if bs['to_station'] not in stations:
            missing_to.add(bs['to_station'])
    if missing_from:
        print(f"  WARNING: {len(missing_from)} from-stations in block sections not in station master")
        errors += len(missing_from)
    if missing_to:
        print(f"  WARNING: {len(missing_to)} to-stations in block sections not in station master")
        errors += len(missing_to)

    # Check train origins/destinations exist in stations
    missing_orig = 0
    missing_dest = 0
    for pid, train in trains.items():
        if train['origin'] and train['origin'] not in stations:
            missing_orig += 1
        if train['destination'] and train['destination'] not in stations:
            missing_dest += 1
    if missing_orig:
        print(f"  WARNING: {missing_orig} trains have origin not in station master")
    if missing_dest:
        print(f"  WARNING: {missing_dest} trains have destination not in station master")

    # Check routes reference valid block sections
    missing_bs = set()
    for pid, route in routes.items():
        for leg in route:
            bs = leg['block_section']
            if bs and bs not in block_sections:
                missing_bs.add(bs)
    if missing_bs:
        print(f"  WARNING: {len(missing_bs)} block sections in routes not in block section master")
    else:
        print(f"  OK: All route block sections found in master data")

    # Check route arithmetic (sample)
    arith_errors = 0
    for pid, route in list(routes.items())[:100]:
        for leg in route:
            ref_dep = leg['ref_departure']
            ref_arr = leg['ref_arrival']
            halt = leg['stoppage_time']
            if ref_dep - ref_arr != halt:
                arith_errors += 1
    print(f"  Arithmetic check (100 trains): {arith_errors} errors")

    if errors == 0 and arith_errors == 0:
        print("  All validation checks PASSED")
    return errors


def save_json(data, filepath):
    """Save data as JSON."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=None, separators=(',', ':'))
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"  Saved {filepath.name} ({size_mb:.1f} MB)")


def main():
    print("=" * 60)
    print("Railway Timetable Data Preprocessing")
    print("=" * 60)

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Check all input files exist
    print("\n[1/11] Checking input files...")
    for name, path in FILES.items():
        if not path.exists():
            print(f"  ERROR: {name} not found at {path}")
            sys.exit(1)
        print(f"  OK: {name}")

    # Load all CSVs
    print("\n[2/11] Loading raw CSV files...")
    raw = {}
    for name, path in FILES.items():
        print(f"  Loading {name}...", end=" ")
        raw[name] = read_csv(path)
        print(f"{len(raw[name])} rows")

    # Process stations
    print("\n[3/11] Processing stations...")
    stations = preprocess_stations(raw['station'])
    print(f"  {len(stations)} stations processed")

    # Process block sections
    print("\n[4/11] Processing block sections...")
    block_sections = preprocess_block_sections(raw['block_section'])
    print(f"  {len(block_sections)} block sections processed")

    # Augment with curvature
    print("\n[5/11] Augmenting with curvature data...")
    block_sections = preprocess_curvature(raw['curvature'], block_sections)

    # Augment with speed restrictions
    print("\n[6/11] Augmenting with speed restrictions...")
    block_sections = preprocess_speed_restrictions(raw['speed_restriction'], block_sections)

    # Process station infrastructure
    print("\n[7/11] Processing station infrastructure...")
    station_lines = preprocess_station_lines(raw['station_line'])
    print(f"  Station lines: {len(station_lines)} stations with line data")
    platforms = preprocess_platforms(raw['platform'])
    print(f"  Platforms: {len(platforms)} stations with platform data")
    bs_lines = preprocess_block_sctn_lines(raw['block_sctn_line'])
    print(f"  Block section lines: {len(bs_lines)} block sections with line data")
    line_connections = preprocess_line_connections(raw['line_connection'])
    print(f"  Line connections: {len(line_connections)} stations with connection data")

    # Process block corridors
    print("\n[8/11] Processing block corridors...")
    block_corridors = preprocess_block_corridors(raw['block_corridor'])
    print(f"  {len(block_corridors)} corridor entries processed")

    # Process train master
    print("\n[9/11] Processing train master...")
    trains = preprocess_train_master(raw['train_master'])
    print(f"  {len(trains)} trains processed")

    # Extract train routes from existing schedule
    print("\n[10/11] Extracting train routes from Train_Schedule.csv...")
    routes = preprocess_train_routes(raw['train_schedule'])
    print(f"  {len(routes)} train routes extracted")
    total_legs = sum(len(r) for r in routes.values())
    print(f"  Total route legs: {total_legs}")
    avg_legs = total_legs / len(routes) if routes else 0
    print(f"  Average legs per route: {avg_legs:.1f}")

    # Derive train properties for trains only in schedule (not in master)
    derived_trains = derive_train_props_from_routes(raw['train_schedule'], routes)
    only_in_schedule = set(routes.keys()) - set(trains.keys())
    for pid in only_in_schedule:
        if pid in derived_trains:
            trains[pid] = derived_trains[pid]
    print(f"  Derived {len(only_in_schedule)} train properties from schedule data")
    print(f"  Total trains after merge: {len(trains)}")

    # Validate
    validate_data(stations, block_sections, trains, routes)

    # Save all preprocessed data
    print("\n[11/11] Saving preprocessed data...")
    save_json(stations, OUTPUT_DIR / "stations.json")
    save_json(block_sections, OUTPUT_DIR / "block_sections.json")
    save_json(trains, OUTPUT_DIR / "train_master.json")
    save_json(routes, OUTPUT_DIR / "train_routes.json")
    save_json(station_lines, OUTPUT_DIR / "station_lines.json")
    save_json(platforms, OUTPUT_DIR / "platforms.json")
    save_json(bs_lines, OUTPUT_DIR / "block_section_lines.json")
    save_json(line_connections, OUTPUT_DIR / "line_connections.json")
    save_json(block_corridors, OUTPUT_DIR / "block_corridors.json")

    # Print summary
    print("\n" + "=" * 60)
    print("PREPROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Stations:          {len(stations):>8,}")
    print(f"  Block sections:    {len(block_sections):>8,}")
    print(f"  Trains:            {len(trains):>8,}")
    print(f"  Train routes:      {len(routes):>8,}")
    print(f"  Total route legs:  {total_legs:>8,}")
    print(f"  Station lines:     {len(station_lines):>8,}")
    print(f"  Platforms:          {len(platforms):>8,}")
    print(f"  BS lines:          {len(bs_lines):>8,}")
    print(f"  Line connections:  {len(line_connections):>8,}")
    print(f"  Block corridors:   {len(block_corridors):>8,}")
    print(f"\nOutput directory: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
