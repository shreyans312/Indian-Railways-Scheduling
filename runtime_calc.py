"""
Runtime calculator module.
Computes the runtime for a train traversing a single block section,
accounting for distance, speed limits, curvature, speed restrictions,
and acceleration/deceleration.
"""

import math

# Standard accel/decel time when a train stops (seconds)
DEFAULT_ACC_DEC_TIME = 60

# Rounding granularity for runtimes (seconds)
ROUND_UNIT = 30


def round_to_unit(seconds, unit=ROUND_UNIT):
    """Round seconds to the nearest multiple of `unit`."""
    if seconds <= 0:
        return 0
    return round(seconds / unit) * unit


def compute_effective_speed(train_mps, block_max_speed):
    """
    Compute effective speed as the minimum of train max permissible speed
    and block section max speed. Both in km/h.
    """
    speeds = [s for s in [train_mps, block_max_speed] if s and s > 0]
    if not speeds:
        return 100  # fallback default
    return min(speeds)


def compute_base_runtime(distance_km, effective_speed_kph):
    """
    Compute base runtime in seconds = distance / speed * 3600.
    Returns raw float (not rounded).
    """
    if effective_speed_kph <= 0 or distance_km <= 0:
        return 0.0
    return (distance_km / effective_speed_kph) * 3600


def compute_curvature_adjustment(block_section_data, is_goods=False):
    """
    Get cumulative curvature time loss for this block section (seconds).
    Already aggregated during preprocessing.
    """
    if is_goods:
        return block_section_data.get('curvature_time_loss_goods', 0)
    return block_section_data.get('curvature_time_loss_psgr', 0)


def compute_speed_restriction_adjustment(block_section_data, is_goods=False):
    """
    Get cumulative speed restriction time loss for this block section (seconds).
    Already aggregated during preprocessing.
    """
    if is_goods:
        return block_section_data.get('speed_restriction_time_loss_goods', 0)
    return block_section_data.get('speed_restriction_time_loss_psgr', 0)


def calculate_runtime(train_props, block_section_data, has_prev_stop, has_next_stop,
                      use_reference=False, ref_runtime=None):
    """
    Calculate total runtime for a train traversing a block section.

    Parameters:
        train_props: dict with train properties (must have 'max_speed_kph')
        block_section_data: dict with block section properties
        has_prev_stop: True if the train stopped at the previous station (needs acceleration)
        has_next_stop: True if the train will stop at the next station (needs deceleration)
        use_reference: if True, use ref_runtime as the base and just return it
        ref_runtime: reference runtime from existing schedule (used in reference mode)

    Returns:
        dict with:
            'runtime': total runtime in seconds
            'acc_time': acceleration time component
            'dec_time': deceleration time component
            'base_runtime': base runtime before acc/dec
            'effective_speed': speed used for calculation
    """
    # Reference mode: use known runtime from existing schedule
    if use_reference and ref_runtime is not None and ref_runtime > 0:
        return {
            'runtime': ref_runtime,
            'acc_time': DEFAULT_ACC_DEC_TIME if has_prev_stop else 0,
            'dec_time': DEFAULT_ACC_DEC_TIME if has_next_stop else 0,
            'base_runtime': ref_runtime,
            'effective_speed': 0,
        }

    # Compute mode: calculate from infrastructure data
    distance_km = block_section_data.get('distance_km', 0)
    if distance_km <= 0:
        return {'runtime': 0, 'acc_time': 0, 'dec_time': 0,
                'base_runtime': 0, 'effective_speed': 0}

    train_mps = train_props.get('max_speed_kph', 110)
    block_speed = block_section_data.get('max_speed_kph', 110)

    effective_speed = compute_effective_speed(train_mps, block_speed)

    # Base runtime from distance and effective speed
    base_raw = compute_base_runtime(distance_km, effective_speed)

    # Curvature time loss
    is_goods = train_props.get('train_type', '') in ('GOODS', 'GDS', 'FGHT')
    curv_loss = compute_curvature_adjustment(block_section_data, is_goods)

    # Speed restriction time loss
    sr_loss = compute_speed_restriction_adjustment(block_section_data, is_goods)

    # Total adjusted base time (before acc/dec)
    adjusted_raw = base_raw + curv_loss + sr_loss
    base_runtime = round_to_unit(adjusted_raw)

    # Ensure minimum 30s for any non-zero distance
    if base_runtime <= 0 and distance_km > 0:
        base_runtime = ROUND_UNIT

    # Acceleration / deceleration
    acc_time = DEFAULT_ACC_DEC_TIME if has_prev_stop else 0
    dec_time = DEFAULT_ACC_DEC_TIME if has_next_stop else 0

    total_runtime = base_runtime + acc_time + dec_time

    return {
        'runtime': total_runtime,
        'acc_time': acc_time,
        'dec_time': dec_time,
        'base_runtime': base_runtime,
        'effective_speed': effective_speed,
    }
