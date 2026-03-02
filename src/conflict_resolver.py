"""
Conflict resolution module.
Tracks resource occupancy (block sections, platforms) and ensures
no two trains occupy the same resource at the same time.

For single-line block sections, both directions share the same physical track
so conflicts are checked bidirectionally.
"""

from collections import defaultdict
import bisect


class ResourceTracker:
    """
    Tracks occupancy of block sections and platforms.
    Detects conflicts and computes the earliest available entry time.
    """

    def __init__(self, block_sections_data):
        """
        Initialize with block section master data to determine capacities
        and single-line section mappings.

        Parameters:
            block_sections_data: dict of block sections keyed by block_section_id
        """
        # Occupancy intervals: key -> sorted list of (end_time, start_time, train_id)
        # Sorted by end_time for efficient conflict search
        self._block_occupancy = defaultdict(list)
        self._platform_occupancy = defaultdict(list)

        # Build physical section mapping for single-line sections
        # canonical_key -> capacity
        self._physical_key = {}   # block_section_id -> canonical physical key
        self._capacity = {}       # canonical physical key -> max concurrent trains

        for bs_id, bs in block_sections_data.items():
            num_lines = bs.get('num_lines', 1)
            if num_lines <= 0:
                num_lines = 1
            from_stn = bs.get('from_station', '')
            to_stn = bs.get('to_station', '')

            if num_lines == 1 and from_stn and to_stn:
                # Single-line: both directions share one physical track
                canonical = tuple(sorted([from_stn, to_stn]))
                self._physical_key[bs_id] = canonical
                self._capacity[canonical] = 1
            else:
                # Multi-line: each direction can hold one train per line
                # Use the block section ID directly as the physical key
                self._physical_key[bs_id] = bs_id
                self._capacity[bs_id] = max(num_lines, 1)

        self._conflicts_resolved = 0
        self._total_delay_seconds = 0

    def _get_physical_key(self, bs_id):
        return self._physical_key.get(bs_id, bs_id)

    def _get_capacity(self, bs_id):
        pk = self._get_physical_key(bs_id)
        return self._capacity.get(pk, 1)

    def count_overlaps(self, intervals, start, end):
        """Count how many existing intervals overlap with [start, end)."""
        count = 0
        for (iend, istart, _) in intervals:
            if istart < end and iend > start:
                count += 1
        return count

    def earliest_available(self, intervals, desired_start, duration, capacity):
        """
        Find the earliest start time >= desired_start such that the resource
        has fewer than `capacity` overlapping occupancies during [start, start+duration).
        """
        candidate = desired_start
        max_iterations = len(intervals) + 1  # prevent infinite loop

        for _ in range(max_iterations):
            candidate_end = candidate + duration
            overlap = self.count_overlaps(intervals, candidate, candidate_end)
            if overlap < capacity:
                return candidate
            # Find the earliest end_time among conflicting intervals to try next
            earliest_free = None
            for (iend, istart, _) in intervals:
                if istart < candidate_end and iend > candidate:
                    if earliest_free is None or iend < earliest_free:
                        earliest_free = iend
            if earliest_free is None:
                return candidate
            candidate = earliest_free

        return candidate

    def check_and_reserve_block_section(self, bs_id, desired_start, duration, train_id):
        """
        Reserve a block section for a train. If the section is occupied,
        returns the delayed start time.

        Parameters:
            bs_id: block section identifier
            desired_start: desired entry time (seconds)
            duration: how long the train occupies the section (seconds)
            train_id: identifier of the train

        Returns:
            actual_start: the actual start time (>= desired_start)
        """
        if not bs_id or duration <= 0:
            return desired_start

        pk = self._get_physical_key(bs_id)
        capacity = self._get_capacity(bs_id)
        intervals = self._block_occupancy[pk]

        actual_start = self.earliest_available(intervals, desired_start, duration, capacity)
        actual_end = actual_start + duration

        # Record the occupancy
        intervals.append((actual_end, actual_start, train_id))

        delay = actual_start - desired_start
        if delay > 0:
            self._conflicts_resolved += 1
            self._total_delay_seconds += delay

        return actual_start

    def check_and_reserve_platform(self, station, platform, desired_start,
                                   duration, train_id):
        """
        Reserve a platform at a station. If occupied, returns delayed start time.

        Parameters:
            station: station code
            platform: platform identifier
            desired_start: desired arrival time
            duration: stoppage duration (how long the train occupies the platform)
            train_id: identifier of the train

        Returns:
            actual_start: the actual arrival time (>= desired_start)
        """
        if not station or not platform or duration <= 0:
            return desired_start

        key = (station, platform)
        intervals = self._platform_occupancy[key]

        # Platform capacity is always 1
        actual_start = self.earliest_available(intervals, desired_start, duration, 1)
        actual_end = actual_start + duration

        intervals.append((actual_end, actual_start, train_id))

        delay = actual_start - desired_start
        if delay > 0:
            self._conflicts_resolved += 1
            self._total_delay_seconds += delay

        return actual_start

    def get_stats(self):
        """Return conflict resolution statistics."""
        return {
            'conflicts_resolved': self._conflicts_resolved,
            'total_delay_seconds': self._total_delay_seconds,
            'block_sections_tracked': len(self._block_occupancy),
            'platforms_tracked': len(self._platform_occupancy),
        }
