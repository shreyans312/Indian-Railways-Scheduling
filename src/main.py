#!/usr/bin/env python3
"""
This is the main entry point

Usage:
    # Generate primal schedule (computed runtimes, conflict resolution):
    python3 main.py --mode compute --output primal_schedule.csv

    # With custom start time for a single train:
    python3 main.py --mode compute --train SECR24251871 --start-time 28800 --output schedule.csv

    # With start times from a CSV file (columns: MAVPROPOSALID, start_time):
    python3 main.py --mode compute --start-times-file start_times.csv --output schedule.csv

    # With derived stoppage durations (median per station from data):
    python3 main.py --mode compute --derive-stoppages --output schedule.csv

    # Reference mode (reproduce existing schedule with conflict resolution):
    python3 main.py --mode reference --output reference_schedule.csv

    # Generate and verify:
    python3 main.py --mode compute --verify --compare --output schedule.csv
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from collections import defaultdict

# Add implementation dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_all
from schedule_engine import generate_single_train, generate_all_trains
from output_writer import write_schedule
from verification import run_verification


ROOT_DIR = Path(__file__).parent.parent


def progress(current, total):
    pct = current / total * 100
    print(f"\rProgress: {current}/{total} ({pct:.1f}%)", end='', flush=True)


def build_stoppage_model(routes, stations):
    """
    Build a stoppage duration model from route data.
    Returns dict: station_code -> median stoppage (seconds).
    Only includes stations where trains actually stop.
    """
    stn_stoppages = defaultdict(list)
    for pid, route in routes.items():
        for i, leg in enumerate(route):
            stp = leg.get('stoppage_time', 0)
            if stp > 0 and i > 0 and i < len(route) - 1:
                stn_stoppages[leg['station']].append(stp)

    model = {}
    for stn, vals in stn_stoppages.items():
        sorted_vals = sorted(vals)
        model[stn] = sorted_vals[len(sorted_vals) // 2]  # median
    return model


def load_start_times_file(filepath):
    # Load start times from a CSV file with columns: MAVPROPOSALID, start_time
    start_times = {}
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get('MAVPROPOSALID', '').strip()
            st = row.get('start_time', '').strip()
            if pid and st:
                try:
                    start_times[pid] = int(st)
                except ValueError:
                    pass
    return start_times


def parse_time_string(time_str):
    # Parse time as seconds (int) or HH:MM:SS format
    time_str = time_str.strip()
    if ':' in time_str:
        parts = time_str.split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        return h * 3600 + m * 60 + s
    return int(time_str)


def main():
    parser = argparse.ArgumentParser(
        description="Indian Railway Timetable Generator"
    )
    parser.add_argument(
        '--mode', choices=['compute', 'reference'], default='compute',
        help='compute: calculate runtimes from infrastructure; '
             'reference: use runtimes from existing schedule'
    )
    parser.add_argument(
        '--train', type=str, default=None,
        help='Generate for a specific train (MAVPROPOSALID). Omit for all trains.'
    )
    parser.add_argument(
        '--start-time', type=str, default=None, dest='start_time',
        help='Start time for the train (seconds or HH:MM:SS). '
             'Only used with --train for single-train mode.'
    )
    parser.add_argument(
        '--start-times-file', type=str, default=None, dest='start_times_file',
        help='CSV file with columns MAVPROPOSALID,start_time for batch start time overrides.'
    )
    parser.add_argument(
        '--derive-stoppages', action='store_true', dest='derive_stoppages',
        help='Use derived stoppage durations (per-station median from data) '
             'instead of exact reference stoppages. Only applies in compute mode.'
    )
    parser.add_argument(
        '--output', type=str, default='generated_schedule.csv',
        help='Output CSV filename (saved in implementation_claude/output/)'
    )
    parser.add_argument(
        '--verify', action='store_true',
        help='Run verification checks after generation'
    )
    parser.add_argument(
        '--compare', action='store_true',
        help='Compare against reference Train_Schedule.csv'
    )
    parser.add_argument(
        '--no-conflicts', action='store_true', dest='no_conflicts',
        help='Disable inter-train conflict resolution'
    )
    parser.add_argument(
        '--discover-routes', action='store_true', dest='discover_routes',
        help='Use route finder for trains without pre-defined routes. '
             'Finds shortest path from origin to destination in block section network.'
    )
    parser.add_argument(
        '--all-trains', action='store_true', dest='all_trains',
        help='Schedule ALL trains from TrainMaster (not just those with reference routes). '
             'Implies --discover-routes.'
    )
    args = parser.parse_args()

    if args.all_trains:
        args.discover_routes = True

    print("=" * 60)
    print("Indian Railway Primal Timetable Generator")
    print("=" * 60)

    # Load data
    data = load_all()

    use_reference = (args.mode == 'reference')
    resolve_conflicts = not args.no_conflicts
    mode_label = "REFERENCE" if use_reference else "COMPUTED"
    conflict_label = "ON" if resolve_conflicts else "OFF"

    # Build start time overrides
    start_times = {}
    if args.start_times_file:
        fpath = Path(args.start_times_file)
        if not fpath.is_absolute():
            fpath = ROOT_DIR / fpath
        start_times = load_start_times_file(fpath)
        print(f"Loaded {len(start_times)} start time overrides from {fpath.name}")

    # Build stoppage model if requested
    stoppage_model = None
    if args.derive_stoppages and not use_reference:
        stoppage_model = build_stoppage_model(data['routes'], data['stations'])
        print(f"Built stoppage model: {len(stoppage_model)} station rules (median-based)")

    print(f"Mode: {mode_label} | Conflict resolution: {conflict_label}"
          f"{' | Derived stoppages' if stoppage_model else ''}"
          f"{' | Dynamic lines' if not use_reference else ''}"
          f"{' | Route discovery' if args.discover_routes else ''}")

    # Determine which trains to generate
    if args.train:
        train_ids = [args.train]
        has_route = args.train in data['routes']
        has_train = args.train in data['trains']
        if not has_train:
            print(f"ERROR: Train {args.train} not found in train master")
            sys.exit(1)
        if not has_route and not args.discover_routes:
            print(f"ERROR: No route found for train {args.train}. Use --discover-routes.")
            sys.exit(1)
        print(f"Generating for single train: {args.train}"
              f"{' (route will be discovered)' if not has_route else ''}")
        # Single-train start time override
        if args.start_time:
            start_times[args.train] = parse_time_string(args.start_time)
            print(f"  Start time override: {start_times[args.train]}s"
                  f" ({start_times[args.train]//3600:02d}:"
                  f"{(start_times[args.train]%3600)//60:02d}:"
                  f"{start_times[args.train]%60:02d})")
        # Single-train mode: no conflict resolution needed
        resolve_conflicts = False
    elif args.all_trains:
        train_ids = list(data['trains'].keys())
        print(f"Generating for ALL {len(train_ids)} trains from TrainMaster"
              f" ({len(data['routes'])} with reference routes,"
              f" {len(train_ids) - len(data['routes'])} to discover)")
    else:
        train_ids = list(data['routes'].keys())
        print(f"Generating for {len(train_ids)} trains with reference routes")

    # Generate schedules
    gen_start = time.time()
    print(f"\nGenerating schedules...")

    all_rows, generated, skipped, conflict_stats = generate_all_trains(
        trains=data['trains'],
        routes=data['routes'],
        block_sections=data['block_sections'],
        use_reference=use_reference,
        train_ids=train_ids,
        progress_callback=progress,
        resolve_conflicts=resolve_conflicts,
        start_times=start_times if start_times else None,
        stoppage_model=stoppage_model,
        station_lines=data.get('station_lines'),
        block_section_lines=data.get('block_section_lines'),
        line_connections=data.get('line_connections'),
        stations=data.get('stations'),
        discover_routes=args.discover_routes,
    )

    elapsed = time.time() - gen_start
    print(f"\n  Generated: {generated} trains, {len(all_rows)} rows in {elapsed:.1f}s")
    if skipped:
        print(f"  Skipped: {skipped} trains (missing master or route data)")

    # Print conflict resolution stats
    if conflict_stats:
        print(f"\n  Conflict Resolution Stats:")
        print(f"    Conflicts resolved:      {conflict_stats.get('conflicts_resolved', 0):,}")
        print(f"    Total delay introduced:  {conflict_stats.get('total_delay_seconds', 0):,}s")
        print(f"    Block sections tracked:  {conflict_stats.get('block_sections_tracked', 0):,}")
        print(f"    Platforms tracked:        {conflict_stats.get('platforms_tracked', 0):,}")

    # Write output
    output_dir = Path(__file__).parent / "output"
    output_path = output_dir / args.output
    print(f"\nWriting output...")
    write_schedule(all_rows, output_path)

    # Verification
    if args.verify or args.compare:
        print()
        ref_path = ROOT_DIR / "Train_Schedule.csv" if args.compare else None
        run_verification(all_rows, data['block_sections'], reference_path=ref_path)

    print(f"\nDone! Output: {output_path}")


if __name__ == '__main__':
    main()
