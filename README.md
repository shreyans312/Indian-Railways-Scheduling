# Indian Railway Primal Timetable Generator

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Input Data Files](#2-input-data-files)
3. [Output Format](#3-output-format)
4. [System Architecture](#4-system-architecture)
5. [Preprocessing](#5-preprocessing)
6. [Schedule Generation Engine](#6-schedule-generation-engine)
7. [Conflict Resolution](#7-conflict-resolution)
8. [Runtime Calculation](#8-runtime-calculation)
9. [Verification](#9-verification)
10. [How to Run](#10-how-to-run)
11. [Key Data Insights](#11-key-data-insights)
12. [Known Limitations](#12-known-limitations)

---

## 1. Project Overview

This project generates a **primal (initial/base) timetable** for Indian Railways using infrastructure data provided by CRIS (Centre for Railway Information Systems). The system reads 11 static CSV data files describing the railway network - stations, tracks, speed limits, curvature, platforms, etc. - and produces a complete working timetable in a 63-column CSV format.

A "primal timetable" is a feasibility schedule where:
- Every train follows its designated route through the network
- All arithmetic time invariants hold (arrival + halt = departure, departure + runtime = next arrival)
- **No two trains occupy the same block section or platform at the same time**
- Times are cumulative seconds from midnight of Day 1

### Project Structure

```
Time Tabling CRIS/
├── Copy of 01_TrainMaster_10_Dec_2024.csv      # 11 input data files
├── Copy of 03_Station_10_Dec_2024.csv
├── Copy of 04_BlockSctn_10_Dec_2024.csv
├── Copy of 05_StationLine_10_Dec_2024.csv
├── Copy of 06_Platform_10_Dec_2024.csv
├── Copy of 07_BlockSctnLine_10_Dec_2024.csv
├── Copy of 08_LineConnection_10_Dec_2024.csv
├── Copy of 09_StationPosition_10_Dec_2024.csv
├── Copy of 11_Curvature_10_Dec_2024.csv
├── Copy of 12_SpeedRestrictions_10_Dec_2024.csv
├── Copy of 13_BlockCorridor_10_Dec_2024.csv
├── Train_Schedule.csv                           # Reference schedule (target format)
├── README.md                                    # This file
├── preprocess.py                                # Preprocessing script
│
├── preprocessed_data/                           # Output of preprocessing (9 JSON files)
│   ├── stations.json
│   ├── block_sections.json
│   ├── train_master.json
│   ├── train_routes.json
│   ├── station_lines.json
│   ├── platforms.json
│   ├── block_section_lines.json
│   ├── line_connections.json
│   └── block_corridors.json
│
├── src/                                         # Schedule generation code
│   ├── main.py                                  # CLI entry point
│   ├── data_loader.py                           # Loads preprocessed JSON
│   ├── schedule_engine.py                       # Core scheduling logic
│   ├── conflict_resolver.py                     # Block section & platform conflicts
│   ├── runtime_calc.py                          # Travel time calculator
│   ├── output_writer.py                         # 63-column CSV writer
│   ├── verification.py                          # Validation checks
│   └── output/
│       └── full_schedule.csv                    # Generated timetable
```

---

## 2. Input Data Files

### 2.1 Train Master (`01_TrainMaster`)
- **10,006 rows** | Train-level properties
- Each row = one train proposal with: proposal ID, train number, name, type (Rajdhani/Shatabdi/Express/etc.), origin, destination, departure time, max permissible speed (MPS), gauge, traction type, rake type, loco type, number of coaches, days of service, owning railway/division, total distance, total runtime, total stoppages, etc.

### 2.2 Station Master (`03_Station`)
- **9,350 rows** | Every station/halt in the network
- Each row = one station with: station code (e.g. `NDLS`, `CSTM`), station name, zone, division, latitude/longitude, junction flag, halt flag, traffic type, traction change point, crew change point, interlocking standard, signal arrangement, state code, start/end buffer times.

### 2.3 Block Section Master (`04_BlockSctn`)
- **23,331 rows** | Track segments between consecutive stations
- Each row = one block section with: section ID (format `FROM_STATION-TO_STATION`), from/to station codes, distance (km), number of parallel track lines, number of signals, gauge, traction type, max speed, direction (UP/DN), section code.
- A block section is the fundamental unit of track - a train occupies one block section at a time.

### 2.4 Station Lines (`05_StationLine`)
- **30,407 rows** | Track lines within stations
- Each row = one line at a station: line number, line type (MAIN/LOOP/SIDING), category, length, direction, capacity, gauge, traction type, speed, platform attachment flag.
- Describes the internal track layout of each station.

### 2.5 Platforms (`06_Platform`)
- **15,481 rows** | Physical platforms at stations
- Each row = one platform: station code, platform number, vertical/horizontal position, length, type, capacity.
- Used for platform occupancy conflict checks.

### 2.6 Block Section Lines (`07_BlockSctnLine`)
- **28,576 rows** | Individual track lines within block sections
- Each row = one track line in a block section: line number, length, category, max speed, direction.
- Distinguishes single-line vs double-line vs multi-line sections.

### 2.7 Line Connections (`08_LineConnection`)
- **97,896 rows** | How station lines connect to block section lines
- Each row = one connection: station line ↔ block section line mapping, with receive/send direction flag.
- Defines the physical connectivity of the track network.

### 2.8 Station Position (`09_StationPosition`)
- **21,607 rows** | Geographic ordering of stations within corridors
- Each row = one station's position on a block section corridor: section code, sequence number.

### 2.9 Curvature Data (`11_Curvature`)
- **58,223 rows** | Track curvature penalties
- Each row = one curve on a block section: from/to kilometer marks, curvature degree, time loss for passenger trains, time loss for goods trains.
- Multiple curves per block section - aggregated during preprocessing into total time loss per section.

### 2.10 Speed Restrictions (`12_SpeedRestrictions`)
- **6,578 rows** | Temporary/permanent speed limits
- Each row = one restriction on a block section: from/to km, restricted speed for passenger, restricted speed for goods, distance, reason, status.
- Also aggregated into total time loss per section during preprocessing.

### 2.11 Block Corridors (`13_BlockCorridor`)
- **12,031 rows** | Time-based corridor availability windows
- Each row = one availability window: block section, from/to time, from/to date, days of service, permanent/temporary flag.

### 2.12 Train Schedule (`Train_Schedule.csv`) - Reference
- **374,935 rows, 63 columns** | The target output format
- Contains 2,772 unique trains, each with an ordered sequence of station visits.
- This is both the reference for validation AND the source of route data (which stations each train visits, in what order, with what stoppages).

---

## 3. Output Format

The generated timetable has exactly **63 columns** matching `Train_Schedule.csv`. The key columns are:

| Column | Description |
|--------|-------------|
| `MAVPROPOSALID` | Unique train proposal identifier |
| `MANSEQNUMBER` | Sequence number (1, 2, 3, ... for each station in route) |
| `MAVSTTNCODE` | Station code at this stop |
| `MAVBLCKSCTN` | Block section from this station to the next |
| `MANWTTARVL` | Arrival time (cumulative seconds from midnight Day 1) |
| `MANWTTDPRT` | Departure time (cumulative seconds) |
| `MANWTTNEXTARVL` | Arrival time at the next station |
| `MANWTTDAYOFRUN` | Day of run (1, 2, 3... computed from arrival time) |
| `MANRUNTIME` | Runtime to traverse the block section (seconds) |
| `MANSTPGTIME` | Stoppage/halt time at this station (0 = pass-through) |
| `MANACCTIME` | Acceleration time (typically 60s if train stopped) |
| `MANDECTIME` | Deceleration time (typically 60s if train will stop) |
| `MANTRFCALWC` | Traffic allowance (seconds) |
| `MANENGGALWC` | Engineering allowance (seconds) |
| `MANINTRDIST` | Distance of this block section (km) |
| `MANCUMDISTANCE` | Cumulative distance from origin (km) |
| `MANMAXSPEED` | Effective max speed (derived: distance/runtime × 3600) |
| `MANBSSPEED` | Block section speed limit (km/h) |
| `MANTRAINMPS` | Train's max permissible speed (km/h) |

### Arithmetic Invariants (must hold for EVERY row)

```
1. MANWTTDPRT  =  MANWTTARVL + MANSTPGTIME
2. MANWTTNEXTARVL  =  MANWTTDPRT + MANRUNTIME
3. Row[i].MANWTTNEXTARVL  ==  Row[i+1].MANWTTARVL   (cross-row continuity)
4. MANWTTDAYOFRUN  =  floor(MANWTTARVL / 86400) + 1
```

---

## 4. System Architecture

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
                                     ├── runtime_calc.py      (per block section)
                                     └── conflict_resolver.py  (per block section & platform)
                                            │
                                            ▼
                                    output_writer.py ──→ full_schedule.csv
                                            │
                                            ▼
                                    verification.py ──→ PASS/FAIL report
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `preprocess.py` | One-time ETL: CSV → JSON. Aggregates curvature/speed data. Extracts routes. |
| `data_loader.py` | Loads 9 JSON files into Python dicts for fast key-based lookup. |
| `runtime_calc.py` | Calculates travel time for one train on one block section. |
| `schedule_engine.py` | Core loop: iterates through each train's route, builds timetable row by row. |
| `conflict_resolver.py` | Tracks block section and platform occupancy across all trains. |
| `output_writer.py` | Writes list of row dicts to a 63-column CSV. |
| `verification.py` | Validates arithmetic invariants, speed constraints, reference comparison. |
| `main.py` | CLI entry point: parses flags, orchestrates the pipeline. |

---

## 5. Preprocessing

The preprocessing script (`preprocess.py`) is a one-time ETL step that transforms 12 raw CSV files into 9 clean, indexed JSON lookup structures. This section explains each step in detail.

### 5.1 CSV Reading with BOM Handling

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

Some CRIS CSV files include a UTF-8 BOM (Byte Order Mark: `\xef\xbb\xbf`) at the start of the file. When read with plain `utf-8` encoding, this BOM gets prepended to the first column name (e.g., `ï»¿MAVSTTNCODE` instead of `MAVSTTNCODE`), causing key lookups to fail silently.

**Fix**: The `utf-8-sig` encoding automatically strips the BOM. The function tries `utf-8-sig` first, falls back to `utf-8`, then `latin1`.

### 5.2 Station Processing (`preprocess_stations`)

**Input**: `03_Station_10_Dec_2024.csv` (9,350 rows)
**Output**: `stations.json` - dict keyed by station code

Each raw row is transformed into a clean dict:
```
CSV Row: MAVSTTNCODE=NDLS, MAVSTTNNAME=NEW DELHI, MACJUNCTION=Y, MANLATITUDE=28.642...
    ↓
JSON: {"NDLS": {"code":"NDLS", "name":"NEW DELHI", "is_junction":true, "latitude":28.642, ...}}
```

Key transformations:
- String fields are `.strip()`-ed to remove whitespace
- Boolean fields (`MACJUNCTION`, `MACHALTFLAG`, `MACTRTNCHNG`, `MACCREWCHNG`) are converted from `'Y'/'N'` strings to Python `True/False`
- Numeric fields use `safe_float()` / `safe_int()` with fallback defaults to handle missing or malformed data

### 5.3 Block Section Processing (`preprocess_block_sections`)

**Input**: `04_BlockSctn_10_Dec_2024.csv` (23,331 rows)
**Output**: `block_sections.json` - dict keyed by block section ID (e.g., `"NDLS-NZM"`)

Each block section represents a segment of track between two consecutive stations. The ID follows the naming convention `FROM_STATION-TO_STATION` (verified 100% match in data analysis).

Key fields extracted:
- `from_station`, `to_station` - the two endpoints
- `distance_km` - track length in kilometers
- `num_lines` - number of parallel tracks (1 = single-line, 2 = double-line, etc.)
- `max_speed_kph` - speed limit on this section
- `direction` - UP or DN
- `gauge`, `traction_type` - physical track properties

Placeholder fields are initialized for later augmentation:
```python
'curvature_time_loss_psgr': 0,      # filled by step 5.4
'curvature_time_loss_goods': 0,     # filled by step 5.4
'speed_restrictions': [],            # filled by step 5.5
'speed_restriction_time_loss_psgr': 0,   # filled by step 5.5
'speed_restriction_time_loss_goods': 0,  # filled by step 5.5
```

### 5.4 Curvature Augmentation (`preprocess_curvature`)

**Input**: `11_Curvature_10_Dec_2024.csv` (58,223 rows)
**Modifies**: `block_sections` dict (adds time loss values)

A single block section can have many curves. Each curve has separate time loss values for passenger trains and goods trains. The preprocessing **aggregates** (sums) all curvature time losses per block section:

```
Raw:  BIRD-KOPR, curve1, TIMELOSSPSGR=2, TIMELOSSGOODS=3
      BIRD-KOPR, curve2, TIMELOSSPSGR=1, TIMELOSSGOODS=2
      BIRD-KOPR, curve3, TIMELOSSPSGR=3, TIMELOSSGOODS=4
                    ↓
Result: block_sections["BIRD-KOPR"].curvature_time_loss_psgr = 6
        block_sections["BIRD-KOPR"].curvature_time_loss_goods = 9
```

Of 12,947 unique block sections with curvature data, 12,456 (96%) match existing block section IDs and get augmented. The remaining ~4% are for sections not in the block section master (minor data inconsistency).

### 5.5 Speed Restriction Augmentation (`preprocess_speed_restrictions`)

**Input**: `12_SpeedRestrictions_10_Dec_2024.csv` (6,578 rows)
**Modifies**: `block_sections` dict (adds restrictions and time loss)

Similar to curvature, speed restrictions are aggregated per block section. Each restriction stores:
- `from_km`, `to_km` - where on the section the restriction applies
- `psgr_speed`, `goods_speed` - restricted speed for each train category
- `distance` - length of the restricted zone
- `reason`, `status` - why and whether it's active

The individual restrictions are stored in a list, AND the total time losses are summed:
```python
block_sections[bs_id]['speed_restrictions'] = [restriction1, restriction2, ...]
block_sections[bs_id]['speed_restriction_time_loss_psgr'] = sum of all TIMELOSSPSGR
block_sections[bs_id]['speed_restriction_time_loss_goods'] = sum of all TIMELOSSGOODS
```

### 5.6 Station Infrastructure Processing

Four files are processed into lookup structures:

#### Station Lines (`05_StationLine` → `station_lines.json`)
- **30,407 rows** → dict keyed by station code, value = list of lines
- Each line: number, type (MAIN/LOOP/SIDING), length, direction, capacity, gauge, speed, platform flag
- Used to understand station capacity and track layout

#### Platforms (`06_Platform` → `platforms.json`)
- **15,481 rows** → dict keyed by station code, value = list of platforms
- Each platform: number, position, length, type, capacity
- Used by conflict resolver to check platform occupancy

#### Block Section Lines (`07_BlockSctnLine` → `block_section_lines.json`)
- **28,576 rows** → dict keyed by block section ID, value = list of track lines
- Each line: number, length, category, max speed, direction
- Determines single-line vs multi-line capacity for conflict resolution

#### Line Connections (`08_LineConnection` → `line_connections.json`)
- **97,896 rows** → dict keyed by station code, value = list of connections
- Each connection: station line ↔ block section line mapping, receive/send flag
- Maps how trains transition between station tracks and main-line tracks

### 5.7 Block Corridors (`preprocess_block_corridors`)

**Input**: `13_BlockCorridor_10_Dec_2024.csv` (12,031 rows)
**Output**: `block_corridors.json` - list of corridor availability windows

Each entry defines a time window during which a block section is available:
- `block_section`, `from_time`, `to_time` - section and availability window
- `from_date`, `to_date`, `days_of_service` - date range and applicable days
- `perm_temp` - permanent or temporary corridor

### 5.8 Train Master Processing (`preprocess_train_master`)

**Input**: `01_TrainMaster_10_Dec_2024.csv` (10,006 rows)
**Output**: Part of `train_master.json` - dict keyed by proposal ID

Extracts all train-level properties: ID, number, name, type, origin/destination, departure/arrival times, max speed, gauge, traction, coaches, days of service, total distance/runtime/stoppages, owning railway, etc.

### 5.9 Train Route Extraction (`preprocess_train_routes`)

**Input**: `Train_Schedule.csv` (374,935 rows)
**Output**: `train_routes.json` (227.5 MB) - dict keyed by proposal ID, value = ordered list of legs

This is the most important preprocessing step. It reads the entire existing schedule and extracts the **constant route data** for each of the 2,772 trains - the ordered sequence of stations, block sections, stoppages, distances, and other static per-leg information.

For each row in the schedule, it extracts:

**Static route data** (doesn't change between runs):
- `seq` - sequence number (ordering within the route)
- `station` - station code at this point
- `block_section` - track segment to the next station
- `stoppage_time` - halt duration at this station (0 = pass-through)
- `distance_km` - length of the block section
- `cum_distance` - cumulative distance from origin
- `platform` - assigned platform number
- `zone`, `division` - administrative area
- `station_line`, `bs_line` - track line assignments
- `crew_change`, `loco_change` - operational flags

**Reference values** (from the existing schedule, used for validation/reference mode):
- `ref_runtime` - known travel time for this block section
- `ref_acc_time`, `ref_dec_time` - known acceleration/deceleration times
- `ref_traffic_allowance`, `ref_engg_allowance` - known allowances
- `ref_max_speed`, `ref_bs_speed`, `ref_train_mps` - speed values
- `ref_arrival`, `ref_departure` - known arrival/departure times

Routes are sorted by sequence number after extraction to guarantee correct ordering.

### 5.10 Derived Train Properties (`derive_train_props_from_routes`)

**Problem**: Only 397 of 2,772 trains in the schedule exist in TrainMaster (different proposal ID sets from different data snapshots).

**Solution**: For the 2,375 missing trains, synthetic train properties are derived from their schedule rows:
- `origin` = station code from first row
- `destination` = station code from last row
- `departure_time` = `MANWTTDPRT` from first row
- `arrival_time` = `MANWTTARVL` from last row
- `max_speed_kph` = `MANTRAINMPS` from first row
- `train_id`, `train_number` = from row fields
- `total_runtime` = sum of all `MANRUNTIME`
- `total_stoppage` = sum of all `MANSTPGTIME`
- `total_distance` = `MANCUMDISTANCE` from last row

These synthetic entries are merged into the train master, giving a total of 12,380 train entries (10,005 original + 2,375 derived).

### 5.11 Validation

Before saving, the preprocessor runs validation checks:
1. Block section endpoints reference valid stations (**3 missing** - minor data issue)
2. Train origins/destinations reference valid stations (**13 missing**)
3. Route block sections reference valid block section IDs (**69 missing**)
4. Arithmetic check on first 100 trains: `departure - arrival == stoppage` (**0 errors**)

### 5.12 JSON Serialization

All data is saved as compact JSON (no indentation, minimal separators) to reduce file size while maintaining human readability when needed:

```python
json.dump(data, f, ensure_ascii=False, indent=None, separators=(',', ':'))
```

Total preprocessed data: ~270 MB across 9 files. The largest file is `train_routes.json` at 227.5 MB (374,935 legs with 27 fields each).

---

## 6. Schedule Generation Engine

### 6.1 Single Train Generation (`generate_single_train`)

The core function iterates through each station in a train's route and builds one output row per station:

```
For each station i (0 to N-1):

  1. ARRIVAL = current_time
     (For i=0, this is the train's scheduled departure time.
      For i>0, this is the previous leg's next_arrival.)

  2. DEPARTURE = ARRIVAL + STOPPAGE_TIME
     (If stoppage = 0, the train passes through without halting.)

  3. PLATFORM CONFLICT CHECK
     If a platform is assigned and stoppage > 0:
       Ask ResourceTracker: "Is this platform free during [arrival, arrival+stoppage]?"
       If NOT free → find earliest free slot → add extra wait to stoppage
       (Arrival stays unchanged to preserve cross-row continuity)

  4. COMPUTE RUNTIME
     Reference mode: use the known runtime from route data
     Compute mode: calculate from distance, speed limits, curvature, restrictions

  5. BLOCK SECTION CONFLICT CHECK
     Ask ResourceTracker: "Is this block section free during [departure, departure+runtime]?"
     If NOT free → find earliest free departure → add extra wait to stoppage

  6. NEXT_ARRIVAL = DEPARTURE + RUNTIME

  7. Build the 63-column row dict

  8. current_time = NEXT_ARRIVAL  →  feeds into step 1 of next iteration
```

### 6.2 Multi-Train Generation (`generate_all_trains`)

1. All 2,772 trains are sorted by **departure time** (first-come-first-served, equal priority)
2. A shared `ResourceTracker` is created
3. Each train is generated sequentially - the ResourceTracker accumulates occupancy from all previously scheduled trains
4. Earlier-departing trains get their preferred slots; later trains are delayed if conflicts arise

---

## 7. Conflict Resolution

### 7.1 The Problem

The railway network has finite physical capacity:
- A **single-line block section** can hold exactly 1 train at a time (both directions share one track)
- A **multi-line block section** can hold 1 train per track line
- A **platform** can hold 1 train at a time

Without conflict resolution, multiple trains could be scheduled on the same track at the same time - physically impossible.

### 7.2 The Solution: `ResourceTracker`

The `ResourceTracker` maintains two occupancy maps:

```python
_block_occupancy = {physical_key: [(end_time, start_time, train_id), ...]}
_platform_occupancy = {(station, platform): [(end_time, start_time, train_id), ...]}
```

#### Single-Line Section Handling

For single-line sections (11,912 of 23,331 block sections), **both directions** map to the same canonical physical key:

```python
# A→B and B→A share one physical track
canonical = tuple(sorted(["A", "B"]))  # always ("A", "B")
capacity = 1
```

This means if Train X is going A→B at time T, Train Y cannot go B→A during that time.

#### Multi-Line Section Handling

For double/multi-line sections, each direction is tracked independently with capacity = number of lines.

#### Conflict Detection and Resolution

When a train wants to enter a resource:

```python
def earliest_available(intervals, desired_start, duration, capacity):
    candidate = desired_start
    while True:
        overlap = count_overlaps(intervals, candidate, candidate + duration)
        if overlap < capacity:
            return candidate  # slot is free
        # Find when the earliest conflicting interval ends
        candidate = min(end_time for conflicting intervals)
```

If the resource is busy, the function slides forward in time until it finds a free slot. The delay is added to the train's stoppage at the current station (it waits longer before departing).

### 7.3 Key Design Decision: Delay Departure, Not Arrival

When a conflict is detected, the train's **departure** is delayed (stoppage increases), but **arrival stays the same**. This preserves the cross-row invariant:

```
Row[i].MANWTTNEXTARVL == Row[i+1].MANWTTARVL
```

If we changed arrival, we'd break the link with the previous row's NextArrival. Instead, the delay manifests as extra waiting time at the station.

### 7.4 Results

For the full 2,772-train run:
- **7,595 conflicts resolved**
- **4,874,380 seconds** total delay introduced across all trains
- **11,562 block sections** tracked for occupancy
- **5,659 platforms** tracked for occupancy

---

## 8. Runtime Calculation

### 8.1 Reference Mode (100% match)

Simply returns the known runtime from the preprocessed route data. Used for generating a schedule that exactly reproduces the reference timings (with conflict adjustments).

### 8.2 Compute Mode (~64% within 30s, ~81% within 60s)

Calculates runtime from infrastructure data:

```
1. effective_speed = min(train_MPS, block_section_speed)
2. base_runtime = round_to_30(distance / effective_speed × 3600)
3. Add curvature time loss
4. Add speed restriction time loss
5. Add acceleration (60s if train stopped at previous station)
6. Add deceleration (60s if train will stop at next station)
7. total_runtime = base + curvature + restrictions + acc + dec
```

`round_to_30()` rounds to the nearest 30-second multiple (CRIS standard granularity).

The compute mode doesn't achieve 100% match because the actual ICMS system uses additional internal speed tables and computation parameters we don't have access to.

---

## 9. Verification

Three validation checks:

### 9.1 Arithmetic Invariants
- `Departure == Arrival + Stoppage` (every row)
- `NextArrival == Departure + Runtime` (every non-terminal row)
- `Row[i].NextArrival == Row[i+1].Arrival` (cross-row continuity)
- `DayOfRun == floor(Arrival / 86400) + 1`

**Result: PASS** - all 374,935 rows satisfy all invariants.

### 9.2 Speed Constraints
Checks that `runtime ≥ distance / max_speed × 3600` with 10% tolerance.

**Result: 35,235 warnings** - these exist in the reference data itself (the original schedule has runtimes that appear faster than the speed limit would allow, likely due to ICMS internal computation factors).

### 9.3 Reference Comparison
Compares generated runtimes against the original `Train_Schedule.csv`.

**Result (reference mode): 100.0% exact match** on all 374,935 rows.

---

## 10. How to Run

### Prerequisites
- Python 3.7+
- No external dependencies (uses only standard library: `csv`, `json`, `math`, `collections`, `argparse`)

### Step 1: Preprocess Data (run once)
```bash
python3 preprocess.py
```
This reads all 12 CSVs and generates 9 JSON files in `preprocessed_data/`.

### Step 2: Generate Schedule
```bash
cd src

# Full generation with conflict resolution (reference mode):
python3 main.py --mode reference --verify --compare --output full_schedule.csv

# Full generation (compute mode):
python3 main.py --mode compute --verify --output full_schedule_computed.csv

# Single train (no conflicts):
python3 main.py --mode reference --train SECR24251871 --verify --output single.csv

# Without conflict resolution:
python3 main.py --mode reference --no-conflicts --output no_conflicts.csv
```

### CLI Flags
| Flag | Description |
|------|-------------|
| `--mode compute` | Calculate runtimes from infrastructure data |
| `--mode reference` | Use known runtimes from existing schedule |
| `--train PROPOSAL_ID` | Generate for a single train only |
| `--verify` | Run arithmetic and speed verification |
| `--compare` | Compare against reference Train_Schedule.csv |
| `--no-conflicts` | Disable inter-train conflict resolution |
| `--output FILENAME` | Output file name (saved in `output/` subfolder) |

---

## 11. Key Data Insights

### Stopping Pattern
- **83.6%** of station entries are pass-throughs (stoppage = 0)
- Only **16.4%** are actual stops (including origin/destination)
- Average train covers 135 stations but stops at only ~22

### Time Representation
- All times are **cumulative seconds from midnight of Day 1**
- Times never reset at midnight - a train arriving at 25:00:00 (next day 1 AM) has `MANWTTARVL = 90000`
- `MANWTTDAYOFRUN = floor(time / 86400) + 1`

### Block Section Naming
- 100% of block section IDs follow the pattern `FROM_STATION-TO_STATION`
- This was verified across all 23,331 sections

### Track Capacity
- ~12,000 single-line sections (bidirectional conflict checking needed)
- ~9,000 double-line sections
- ~1,600 sections with 3+ lines

---

## 12. Known Limitations

1. **Speed violations in reference data**: ~35,000 rows in the original schedule have runtimes faster than `distance/speed` suggests. These are inherited from the CRIS ICMS system which uses internal speed computation parameters not available to us.

2. **Compute mode accuracy**: Achieves ~64% exact match (within 30s) because we lack the full ICMS speed model (section-wise speed profiles, detailed acceleration curves, etc.).

3. **Train ID mismatch**: Only 397 of 2,772 route trains existed in TrainMaster. The remaining 2,375 have synthetic properties derived from schedule data (missing: train name, type, gauge, traction details).

4. **Minor data gaps**: 69 block sections referenced in routes don't exist in the block section master; 13 trains have origin/destination stations not in the station master.

5. **Numeric formatting**: Some columns have minor formatting differences vs reference (e.g., `7.0` vs `7` for distances, `00635` vs `635` for train numbers). These are cosmetic and don't affect functionality.

6. **No day-of-week filtering**: The conflict resolver doesn't filter by days of service - it assumes all trains run on the same day. A production system would need to check `MAVBLCKBUSYDAYS` to handle Mon/Wed/Fri vs daily trains.
