import csv
import math
from pathlib import Path

SECONDS_IN_A_DAY = 86400


def verify_arithmetic(rows):
    errors = []
    trains = {}
    for row in rows:
        pid = row['MAVPROPOSALID']
        if pid not in trains:
            trains[pid] = []
        trains[pid].append(row)

    for pid, train_rows in trains.items():
        train_rows.sort(key=lambda r: int(r['MANSEQNUMBER']))
        for i, row in enumerate(train_rows):
            seq = int(row['MANSEQNUMBER'])
            arr = int(row['MANWTTARVL'])
            dep = int(row['MANWTTDPRT'])
            nxt_arr = int(row['MANWTTNEXTARVL'])
            rt = int(row['MANRUNTIME'])
            halt = int(row['MANSTPGTIME'])

            # Check: Dep = Arr + Halt
            if dep != arr + halt:
                errors.append({
                    'train': pid, 'seq': seq, 'field': 'MANSTPGTIME',
                    'expected': dep - arr, 'actual': halt,
                    'msg': f'Dep({dep}) - Arr({arr}) != Halt({halt})'
                })

            # Check: NextArr = Dep + RT (skip terminal stations)
            if row['MAVBLCKSCTN']:
                if nxt_arr != dep + rt:
                    errors.append({
                        'train': pid, 'seq': seq, 'field': 'MANRUNTIME',
                        'expected': nxt_arr - dep, 'actual': rt,
                        'msg': f'NextArr({nxt_arr}) - Dep({dep}) != RT({rt})'
                    })

            # Check continuity with next row
            if i < len(train_rows) - 1:
                next_row = train_rows[i + 1]
                next_arr = int(next_row['MANWTTARVL'])
                if nxt_arr != next_arr:
                    errors.append({
                        'train': pid, 'seq': seq, 'field': 'continuity',
                        'expected': nxt_arr, 'actual': next_arr,
                        'msg': f'NextArr({nxt_arr}) of seq {seq} != Arr({next_arr}) of seq {seq+1}'
                    })

            # Check day of run
            expected_day = (arr // SECONDS_IN_A_DAY) + 1
            actual_day = int(row['MANWTTDAYOFRUN'])
            if actual_day != expected_day:
                errors.append({
                    'train': pid, 'seq': seq, 'field': 'MANWTTDAYOFRUN',
                    'expected': expected_day, 'actual': actual_day,
                    'msg': f'Day should be {expected_day} for arr={arr}, got {actual_day}'
                })

    return errors


def verify_speed_constraints(rows, block_sections):
    warnings = []
    for row in rows:
        bs_id = row['MAVBLCKSCTN']
        if not bs_id:
            continue

        rt = int(row['MANRUNTIME'])
        dist = float(row['MANINTRDIST']) if row['MANINTRDIST'] else 0
        train_mps = int(row['MANTRAINMPS']) if row['MANTRAINMPS'] else 0

        if dist <= 0 or rt <= 0:
            continue

        bs_data = block_sections.get(bs_id, {})
        bs_speed = bs_data.get('max_speed_kph', 999)

        if train_mps > 0 and bs_speed > 0:
            max_speed = min(train_mps, bs_speed)
            min_runtime = dist / max_speed * 3600
            # Allow 10% tolerance for rounding
            if rt < min_runtime * 0.9:
                warnings.append({
                    'train': row['MAVPROPOSALID'],
                    'seq': int(row['MANSEQNUMBER']),
                    'bs': bs_id,
                    'msg': f'RT({rt}s) < min_RT({min_runtime:.0f}s) for dist={dist}km at {max_speed}kph'
                })

    return warnings


def compare_with_reference(generated_rows, reference_path):
    # Load reference
    ref = {}
    with open(reference_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row['MAVPROPOSALID'], row['MANSEQNUMBER'])
            ref[key] = row

    stats = {
        'total_rows': len(generated_rows),
        'matched_rows': 0,
        'rt_exact_match': 0,
        'rt_within_30s': 0,
        'rt_within_60s': 0,
        'total_rt_diff': 0,
        'missing_in_ref': 0,
        'per_train': {},
    }

    for row in generated_rows:
        key = (str(row['MAVPROPOSALID']), str(row['MANSEQNUMBER']))
        ref_row = ref.get(key)
        if ref_row is None:
            stats['missing_in_ref'] += 1
            continue

        stats['matched_rows'] += 1
        gen_rt = int(row['MANRUNTIME'])
        ref_rt = int(ref_row['MANRUNTIME'])
        diff = abs(gen_rt - ref_rt)

        if diff == 0:
            stats['rt_exact_match'] += 1
        if diff <= 30:
            stats['rt_within_30s'] += 1
        if diff <= 60:
            stats['rt_within_60s'] += 1

        stats['total_rt_diff'] += diff

        pid = str(row['MAVPROPOSALID'])
        if pid not in stats['per_train']:
            stats['per_train'][pid] = {'legs': 0, 'total_diff': 0, 'exact': 0}
        stats['per_train'][pid]['legs'] += 1
        stats['per_train'][pid]['total_diff'] += diff
        if diff == 0:
            stats['per_train'][pid]['exact'] += 1

    return stats


def run_verification(rows, block_sections, reference_path=None):
    """
    Run all verification checks and print a report.

    Parameters:
        rows: list of generated schedule row dicts
        block_sections: dict of block sections
        reference_path: optional path to reference Train_Schedule.csv
    """
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)

    # 1. Arithmetic checks
    print("\n[1] Arithmetic Invariants")
    arith_errors = verify_arithmetic(rows)
    if not arith_errors:
        print(f"PASS: All {len(rows)} rows satisfy arithmetic invariants")
    else:
        print(f"FAIL: {len(arith_errors)} errors found")
        for e in arith_errors[:10]:
            print(f"Train {e['train']} Seq {e['seq']}: {e['msg']}")
        if len(arith_errors) > 10:
            print(f"... and {len(arith_errors) - 10} more")

    # 2. Speed constraints
    print("\n[2] Speed Constraint Checks")
    speed_warnings = verify_speed_constraints(rows, block_sections)
    if not speed_warnings:
        print(f"PASS: No speed limit violations detected")
    else:
        print(f"WARNING: {len(speed_warnings)} potential speed violations")
        for w in speed_warnings[:5]:
            print(f"Train {w['train']} Seq {w['seq']}: {w['msg']}")
        if len(speed_warnings) > 5:
            print(f"... and {len(speed_warnings) - 5} more")

    # 3. Comparison with reference
    if reference_path and Path(reference_path).exists():
        print("\n[3] Comparison with Reference Schedule")
        comp = compare_with_reference(rows, reference_path)
        matched = comp['matched_rows']
        if matched > 0:
            print(f"Matched rows: {matched}/{comp['total_rows']}")
            print(f"Runtime exact match: {comp['rt_exact_match']} ({comp['rt_exact_match']/matched*100:.1f}%)")
            print(f"Runtime within 30s:  {comp['rt_within_30s']} ({comp['rt_within_30s']/matched*100:.1f}%)")
            print(f"Runtime within 60s:  {comp['rt_within_60s']} ({comp['rt_within_60s']/matched*100:.1f}%)")
            avg_diff = comp['total_rt_diff'] / matched
            print(f"Average RT diff:     {avg_diff:.1f}s")
        else:
            print(f"No matching rows found in reference")
    else:
        print("\n[3] Reference comparison: skipped (no reference file)")

    print("\n" + "=" * 60)
    return len(arith_errors) == 0
