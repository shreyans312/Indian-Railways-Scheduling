#!/usr/bin/env python3
"""
Main entry point for the Indian Railway Primal Timetable Generator.

Usage:
    # Generate schedule for all trains (computed runtimes, with conflict resolution):
    python3 main.py --mode compute --output generated_schedule.csv

    # Generate using reference runtimes:
    python3 main.py --mode reference --output generated_schedule.csv

    # Generate for a specific train (no conflict resolution):
    python3 main.py --mode compute --train SECR24251871 --output schedule.csv

    # Generate without conflict resolution:
    python3 main.py --mode compute --no-conflicts --output generated_schedule.csv

    # Generate and verify against reference:
    python3 main.py --mode compute --verify --compare --output generated_schedule.csv
"""

import argparse
import sys
import time
from pathlib import Path

# Add implementation dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_all
from schedule_engine import generate_single_train, generate_all_trains
from output_writer import write_schedule
from verification import run_verification


ROOT_DIR = Path(__file__).parent.parent


def progress(current, total):
    pct = current / total * 100
    print(f"\r  Progress: {current}/{total} ({pct:.1f}%)", end='', flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Indian Railway Primal Timetable Generator"
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
    args = parser.parse_args()

    print("=" * 60)
    print("Indian Railway Primal Timetable Generator")
    print("=" * 60)

    # Load data
    data = load_all()

    use_reference = (args.mode == 'reference')
    resolve_conflicts = not args.no_conflicts
    mode_label = "REFERENCE" if use_reference else "COMPUTED"
    conflict_label = "ON" if resolve_conflicts else "OFF"
    print(f"Mode: {mode_label} | Conflict resolution: {conflict_label}")

    # Determine which trains to generate
    if args.train:
        train_ids = [args.train]
        if args.train not in data['routes']:
            print(f"ERROR: No route found for train {args.train}")
            sys.exit(1)
        if args.train not in data['trains']:
            print(f"ERROR: Train {args.train} not found in train master")
            sys.exit(1)
        print(f"Generating for single train: {args.train}")
        # Single-train mode: no conflict resolution needed
        resolve_conflicts = False
    else:
        train_ids = list(data['routes'].keys())
        print(f"Generating for all {len(train_ids)} trains")

    # Generate schedules
    start_time = time.time()
    print(f"\nGenerating schedules...")

    all_rows, generated, skipped, conflict_stats = generate_all_trains(
        trains=data['trains'],
        routes=data['routes'],
        block_sections=data['block_sections'],
        use_reference=use_reference,
        train_ids=train_ids,
        progress_callback=progress,
        resolve_conflicts=resolve_conflicts,
    )

    elapsed = time.time() - start_time
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
