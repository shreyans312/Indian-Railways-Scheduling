# Technical Guide

Detailed technical documentation for each module in the railway timetable generator.

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Preprocessing](#2-preprocessing)
3. [Schedule Generation Engine](#3-schedule-generation-engine)
4. [Route Discovery](#4-route-discovery)
5. [Dynamic Line Selection](#5-dynamic-line-selection)
6. [Conflict Resolution](#6-conflict-resolution)
7. [Runtime Calculation](#7-runtime-calculation)
8. [Verification](#8-verification)
9. [Network Visualization](#9-network-visualization)

---

## 1. System Architecture

### Data Flow

```
Phase 1: PREPROCESSING (run once)

  11 Raw CSVs ──→ preprocess.py ──→ 9 JSON files in preprocessed_data/
  Train_Schedule.csv ─┘                  ├── stations.json (2.8 MB)
                                         ├── block_sections.json (12.4 MB)
                                         ├── train_master.json (8.6 MB)
                                         ├── train_routes.json (227.5 MB)
                                         ├── station_lines.json (5.9 MB)
                                         ├── platforms.json (1.7 MB)
                                         ├── block_section_lines.json (3.0 MB)
                                         ├── line_connections.json (7.8 MB)
                                         └── block_corridors.json (2.0 MB)

Phase 2: SCHEDULE GENERATION

  9 JSON files ──→ data_loader.py ──→ In-memory lookup dicts
                                            │
                                            ▼
                                    schedule_engine.py
                                     ├── route_finder.py      (Dijkstra pathfinding)
                                     ├── runtime_calc.py      (per block section)
                                     ├── line_selector.py     (dynamic line selection)
                                     └── conflict_resolver.py (per block section & platform)
                                            │
                                            ▼
                                    output_writer.py ──→ all_trains_schedule.csv
                                            │
                                            ▼
                                    verification.py ──→ PASS/FAIL report
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `preprocess.py` | One-time ETL: CSV → JSON. Aggregates curvature/speed data. Extracts routes. |
| `data_loader.py` | Loads 9 JSON files into Python dicts for fast key-based lookup. |
| `route_finder.py` | Dijkstra + waypoint routing for route discovery with gauge, line, and corridor constraints. |
| `line_selector.py` | Dynamic line selection using connectivity constraints and occupancy-based ranking. |
| `runtime_calc.py` | Calculates travel time for one train on one block section. |
| `schedule_engine.py` | Core loop: iterates through each train's route, builds timetable row by row. |
| `conflict_resolver.py` | Tracks block section and platform occupancy across all trains. |
| `output_writer.py` | Writes list of row dicts to a 63-column CSV. |
| `verification.py` | Validates arithmetic invariants, speed constraints, reference comparison. |
| `visualize_network.py` | Renders network graph with route highlighting and comparison (networkx + matplotlib). |

---

## 2. Preprocessing

The preprocessing script (`preprocess.py`) is a one-time ETL step that transforms 12 raw CSV files into 9 clean, indexed JSON lookup structures.

### 2.1 CSV Reading with BOM Handling

```python
def read_csv(filepath, encoding='utf-8-sig'):
    for enc in [encoding, 'utf-8', 'latin1']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                return list(reader)
        except UnicodeDecodeError:
            continue
```

Some CRIS CSV files include a UTF-8 BOM (Byte Order Mark: `\xef\xbb\xbf`) at the start. When read with plain `utf-8`, this BOM gets prepended to the first column name (e.g., `ï»¿MAVSTTNCODE`), causing silent key lookup failures. The `utf-8-sig` encoding automatically strips the BOM.

### 2.2 Station Processing

**Input**: `03_Station_10_Dec_2024.csv` (9,350 rows) → **Output**: `stations.json`

```
CSV Row: MAVSTTNCODE=NDLS, MAVSTTNNAME=NEW DELHI, MACJUNCTION=Y, MANLATITUDE=28.642...
    ↓
JSON: {"NDLS": {"code":"NDLS", "name":"NEW DELHI", "is_junction":true, "latitude":28.642, ...}}
```

Key transformations:
- String fields `.strip()`-ed; booleans converted from `'Y'/'N'` to `True/False`
- Numeric fields use `safe_float()` / `safe_int()` with fallback defaults

### 2.3 Block Section Processing

**Input**: `04_BlockSctn_10_Dec_2024.csv` (23,331 rows) → **Output**: `block_sections.json`

Each block section ID follows `FROM_STATION-TO_STATION` convention (verified 100%). Key fields: `from_station`, `to_station`, `distance_km`, `num_lines`, `max_speed_kph`, `direction`, `gauge`.

Placeholder fields are initialized for later augmentation by curvature and speed restriction steps.

### 2.4 Curvature Augmentation

**Input**: `11_Curvature_10_Dec_2024.csv` (58,223 rows) → **Modifies**: `block_sections` dict

Multiple curves per block section are **aggregated** (summed) into total time loss:
```
BIRD-KOPR: curve1(TIMELOSSPSGR=2) + curve2(1) + curve3(3) = total 6 seconds
```
12,456 of 12,947 unique block sections with curvature data match existing IDs (96%).

### 2.5 Speed Restriction Augmentation

**Input**: `12_SpeedRestrictions_10_Dec_2024.csv` (6,578 rows) → **Modifies**: `block_sections` dict

Similar aggregation pattern. Individual restrictions stored in a list AND total time losses summed.

### 2.6 Station Infrastructure Processing

Four files processed into lookup structures:
- **Station Lines** (`05_StationLine` → `station_lines.json`): 30,407 rows of track lines within stations
- **Platforms** (`06_Platform` → `platforms.json`): 15,481 rows for platform occupancy checks
- **Block Section Lines** (`07_BlockSctnLine` → `block_section_lines.json`): 28,576 rows for single/multi-line capacity
- **Line Connections** (`08_LineConnection` → `line_connections.json`): 97,896 rows mapping station lines ↔ block section lines

### 2.7 Train Route Extraction

**Input**: `Train_Schedule.csv` (374,935 rows) → **Output**: `train_routes.json` (227.5 MB)

The most important step. Extracts **constant route data** for 2,772 trains:

**Static route data**: `seq`, `station`, `block_section`, `stoppage_time`, `distance_km`, `cum_distance`, `platform`, `zone`, `division`, `station_line`, `bs_line`, `crew_change`, `loco_change`

**Reference values** (for validation): `ref_runtime`, `ref_acc_time`, `ref_dec_time`, `ref_arrival`, `ref_departure`, speed values

### 2.8 Derived Train Properties

**Problem**: Only 397 of 2,772 schedule trains exist in TrainMaster.

**Solution**: `derive_train_props_from_routes()` creates synthetic properties for the 2,375 missing trains from their schedule rows (origin, destination, speeds, distances). Merged into train master → 12,380 total entries.

### 2.9 Validation

Before saving: block section endpoint validation (3 missing stations), train origin/destination checks (13 missing), route block section validation (69 missing), arithmetic spot-check (0 errors on 100 trains).

---

## 3. Schedule Generation Engine

### 3.1 Single Train Generation (`generate_single_train`)

For each station i (0 to N-1):

```
1. ARRIVAL = current_time (for i=0: free start time input; for i>0: previous next_arrival)
2. DETERMINE STOPPAGE (derived model or route data)
3. DEPARTURE = ARRIVAL + STOPPAGE
4. PLATFORM CONFLICT CHECK → if busy, add wait to stoppage
5. COMPUTE RUNTIME (reference or physics-based)
6. BLOCK SECTION CONFLICT CHECK → if busy, add wait to stoppage
7. SELECT LINES (dynamic: connectivity + least-occupied)
8. NEXT_ARRIVAL = DEPARTURE + RUNTIME
9. Build 63-column row dict
10. current_time = NEXT_ARRIVAL → feeds into step 1 of next iteration
```

### 3.2 Multi-Train Generation (`generate_all_trains`)

1. Build per-train stoppage maps from reference route data (exact station→stoppage for each train)
2. Extract mandatory waypoints (stopping stations) from reference routes
3. Sort all trains by departure time (FCFS, equal priority)
4. Trains without routes → waypoint routing if waypoints known, else direct Dijkstra
5. Shared `ResourceTracker` accumulates occupancy from all scheduled trains
6. Earlier-departing trains get preferred slots; later trains delayed on conflicts

### 3.3 Free Start Times

- **Single train**: `--start-time 08:00:00` (or seconds: `28800`)
- **Batch override**: `--start-times-file times.csv` (CSV with `MAVPROPOSALID,start_time`)
- **Default**: `departure_time` from TrainMaster

### 3.4 Derived Stoppages

**Three-tier stoppage model** (in priority order):

1. **Train-specific map** (`build_train_stoppage_maps`): For each reference train, extracts exact `station → stoppage_time` from its route data. When Dijkstra discovers a new route, shared stations get the exact reference stoppage time.
2. **Per-station median** (`build_stoppage_model`): For stations not in the train-specific map, uses the median of all known stoppage durations at that station across all reference trains.
3. **Junction default**: Junction stations (degree ≥ 3) get 120s; all others pass-through (0s).

Result: **100% coverage** of mandatory stops for reference trains (up from 55.2% with direct Dijkstra). The per-station median fallback handles non-reference stations.

---

## 4. Route Discovery

### 4.1 The Problem

Infrastructure CSVs describe the physical network but NOT train routes. Reference data covers 2,772 trains; TrainMaster has 12,380 — the remaining 9,608 have only origin and destination.

### 4.2 RouteFinder (Dijkstra + Waypoint Routing)

Directed graph: **9,339 nodes** (stations) + **23,331 edges** (block sections, FROM→TO).

Three constraint layers on edge weights:

| Constraint | Effect |
|-----------|--------|
| **Gauge compatibility** | Skip block sections with incompatible gauge (B/M/N) |
| **Line connectivity** | +50km penalty if station lacks valid outgoing connections to a block section |
| **Corridor affinity** | +2km penalty when switching `section_code` (keeps trains on same corridor) |

Memory-efficient implementation: predecessor map (not path copies in heap) + integer tiebreaker for heapq.

### 4.3 Waypoint Routing (`find_route_via_waypoints`)

**Problem**: Direct Dijkstra finds the shortest path, but only 55.2% of mandatory stopping stations appear on that path. Trains miss nearly half their required stops.

**Solution**: For trains with known stopping patterns (from reference routes), extract the mandatory stopping stations as ordered waypoints. Then route through them in sequence:

```
origin → stop₁ → stop₂ → ... → stopₙ → destination
```

Each segment uses Dijkstra shortest path. If a waypoint is unreachable, it's skipped and the next segment is tried.

**Result**: 100% mandatory stop coverage (up from 55.2% with direct Dijkstra).

### 4.4 Stoppage Determination for Discovered Routes

Three-tier priority:

1. **Train-specific stoppage map**: exact stoppage times from reference data for shared stations
2. **Per-station median model**: fallback for stations not in the reference
3. **Junction default**: 120s for junctions; 0s for pass-through

### 4.5 Results

- **100% success** for reachable pairs: 9,601 of 9,607 trains routed
- **100% mandatory stop coverage** for reference trains using waypoint routing
- Average route: 55 stations, 454 km
- Only 7 trains completely unreachable

---

## 5. Dynamic Line Selection

### 5.1 The Problem

79.2% of station stops have 2+ valid line options. Each train must be assigned a specific station line and block section line.

### 5.2 LineSelector

Uses `08_LineConnection` data:

```
Valid station lines at station X (between BS_in and BS_out):
  recv_lines = {lines that can RECEIVE from BS_in}
  send_lines = {lines that can SEND to BS_out}
  valid_lines = recv_lines ∩ send_lines
```

Ranking: **M (Main) > L (Loop) > S (Siding) > Y (Yard)**, then least-occupied wins.

### 5.3 Fallback

If no valid lines found via connectivity data, falls back to the first available line from the station's line list.

---

## 6. Conflict Resolution

### 6.1 ResourceTracker

Maintains two occupancy maps:
```python
_block_occupancy = {physical_key: [(end_time, start_time, train_id), ...]}
_platform_occupancy = {(station, platform): [(end_time, start_time, train_id), ...]}
```

### 6.2 Single-Line Section Handling

Both directions map to the same canonical physical key:
```python
canonical = tuple(sorted(["A", "B"]))  # A→B and B→A share one track
capacity = 1
```

### 6.3 Multi-Line Section Handling

Each direction tracked independently; capacity = number of lines.

### 6.4 Conflict Detection

```python
def earliest_available(intervals, desired_start, duration, capacity):
    candidate = desired_start
    while True:
        overlap = count_overlaps(intervals, candidate, candidate + duration)
        if overlap < capacity:
            return candidate
        candidate = min(end_time for conflicting intervals)
```

### 6.5 Key Design Decision: Delay Departure, Not Arrival

Delays are added to **stoppage** (departure moves later), preserving the cross-row invariant `Row[i].NextArrival == Row[i+1].Arrival`. Changing arrival would break the link with the previous row.

### 6.6 Results (Full Run)

- **41,977 conflicts** resolved across 12,373 trains
- **14,899 block sections** and **5,659 platforms** tracked

---

## 7. Runtime Calculation

### 7.1 Reference Mode (100% match)

Returns the known runtime from preprocessed route data. Used for exact reproduction of reference schedule.

### 7.2 Compute Mode (~64% within 30s, ~81% within 60s)

```
1. effective_speed = min(train_MPS, block_section_speed)
2. base_runtime = round_to_30(distance / effective_speed × 3600)
3. + curvature time loss
4. + speed restriction time loss
5. + acceleration (60s if stopped at previous station)
6. + deceleration (60s if will stop at next station)
```

`round_to_30()` rounds to nearest 30-second multiple (CRIS standard granularity).

---

## 8. Verification

### 8.1 Arithmetic Invariants — ALL PASS

- `Departure == Arrival + Stoppage` (every row)
- `NextArrival == Departure + Runtime` (every non-terminal row)
- `Row[i].NextArrival == Row[i+1].Arrival` (cross-row continuity)
- `DayOfRun == floor(Arrival / 86400) + 1`

Verified on all 916,349 rows.

### 8.2 Speed Constraints

11,237 warnings — primarily from reference routes inheriting ICMS-computed runtimes using internal factors we don't have.

### 8.3 Reference Comparison

Reference mode: **100.0% exact match** on all 374,935 rows.

---

## 9. Network Visualization

The `visualize_network.py` module renders the full Indian railway network as a geographic graph using **networkx** + **matplotlib**, with route comparison support.

### 9.1 Three Visualization Modes

| Mode | Command | Output |
|------|---------|--------|
| **Network only** | `visualize_network.py` | Full India railway map (8,864 stations) |
| **Single route** | `visualize_network.py --train <ID>` | Full map + zoomed route inset (dual-panel) |
| **Route comparison** | `visualize_network.py --train <ID> --compare` | Full overlay + ref zoom + Dijkstra zoom (3-panel) |

### 9.2 How It Works

1. **Graph Construction**: Builds a networkx `DiGraph` from 23,331 block sections. Stations positioned at real lat/lon.
2. **Geographic Layout**: Longitude as X, latitude as Y — 8,864 stations (95% with valid coordinates).
3. **Route Highlighting**: Train route drawn in color over grey network base.
4. **Comparison Mode**: Shows reference route (cyan) vs Dijkstra waypoint route (green), with shared edges in white. Statistics show edge/station overlap percentage.

### 9.3 Visual Features Explained

- **Circular/oval loops** near Chennai, Kolkata, Mumbai are **real geographic curves**. Example: near Chennai (PEW/Perambur), the suburban line curves east→northeast→northwest along the coast, forming a U-shape that renders as an oval.
- **Dense clusters** at junction stations (e.g., DDJ with 8 outgoing edges) appear as star patterns.
- **Triangle patterns** (1,100+ in the network) are junction bypass routes.

### 9.4 Dependencies

`networkx` (graph construction) + `matplotlib` (rendering). Install: `pip install networkx matplotlib`
