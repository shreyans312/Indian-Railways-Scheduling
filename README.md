# Indian Railway Primal Timetable Generator

A fully autonomous primal timetable generator for Indian Railways, built from CRIS infrastructure data.

> For detailed technical documentation, see [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md)
> For data file descriptions, see [DATA_REFERENCE.md](DATA_REFERENCE.md)

---

## What It Does

Generates a **conflict-free Working Timetable (WTT)** for 12,373 trains from static infrastructure data, producing a 63-column CSV matching the CRIS format.

| Component | Source | Method |
|-----------|--------|--------|
| Route (station sequence) | Block section network graph | Dijkstra shortest path with **waypoint routing** through mandatory stops |
| Runtimes | Distance, speed, curvature, restrictions | Physics-based computation |
| Stoppage durations | Train-specific reference maps + per-station median fallback | 100% coverage of mandatory stops for reference trains |
| Line assignments | Station lines, BS lines, connections | Dynamic: connectivity + least-occupied selection |
| Start times | User input | Free parameter (`--start-time` / `--start-times-file`) |
| Conflict resolution | Block section + platform occupancy | Automatic delay cascade (FCFS) |

---

## Results

| Metric | Value |
|--------|-------|
| Trains scheduled | 12,373 (of 12,380) |
| Routes discovered via Dijkstra | 9,601 |
| Pre-defined routes (from reference) | 2,772 |
| Total output rows | 916,349 |
| Conflicts resolved | 41,977 |
| Arithmetic invariants | ALL PASS |
| Generation time | ~28 seconds |
| Mandatory stop coverage (waypoint routing) | 100% |

---

## Project Structure

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
│                                
├── README.md                                    # This file
├── TECHNICAL_GUIDE.md                           # Module deep-dives
├── DATA_REFERENCE.md                            # Data file descriptions
|── preprocess.py                                # Preprocessing script
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
├── src/                       # Schedule generation code
│   ├── main.py                                  # CLI entry point
│   ├── data_loader.py                           # Loads preprocessed JSON
│   ├── schedule_engine.py                       # Core scheduling logic
│   ├── route_finder.py                          # Dijkstra + waypoint routing
│   ├── line_selector.py                         # Dynamic line selection
│   ├── conflict_resolver.py                     # Block section & platform conflicts
│   ├── runtime_calc.py                          # Travel time calculator
│   ├── output_writer.py                         # 63-column CSV writer
│   ├── verification.py                          # Validation checks
│   └── visualize_network.py                     # Network graph + route comparison
│
└── output/                   # Generated outputs
    ├── generated_schedule.csv                   # Full timetable (916,349 rows)
    ├── network_graph.png                        # India railway network map
    ├── route_single.png                         # Single train route highlighted
    ├── route_comparison.png                     # Reference vs Dijkstra (high overlap)
    └── route_comparison_divergent.png           # Reference vs Dijkstra (divergent)
```

---

## How to Run

### Prerequisites
- Python 3.7+
- Core scheduling: no external dependencies (standard library only)
- Visualization: `networkx`, `matplotlib` (`pip install networkx matplotlib`)

### Step 1: Preprocess Data (run once)
```bash
python3 plan_claude/preprocess.py
```
Reads all 11 CSVs and generates 9 JSON files in `preprocessed_data/`.

### Step 2: Generate Schedule
```bash
# === FULL PRIMAL GENERATION (recommended) ===
python3 src/main.py --mode compute --all-trains --derive-stoppages --verify

# === Reference routes only (2,772 trains) ===
python3 src/main.py --mode compute --derive-stoppages --verify

# === Single train with custom start time ===
python3 src/main.py --mode compute --train ER23241291 --start-time 08:00:00 \
  --derive-stoppages --discover-routes --verify

# === Reference mode (reproduces original timings, for validation) ===
python3 src/main.py --mode reference --verify --compare
```

### Step 3: Visualize Network (optional)
```bash
# Full network map
python3 src/visualize_network.py

# Highlight a train's route
python3 src/visualize_network.py --train CR24251150

# Compare reference vs Dijkstra route (with waypoint routing)
python3 src/visualize_network.py --train ETBC24250104 --compare

# Discover and highlight a route via Dijkstra
python3 src/visualize_network.py --train ACND23240007 --discover
```

### CLI Flags
| Flag | Description |
|------|-------------|
| `--mode compute` | Calculate runtimes from infrastructure data |
| `--mode reference` | Use known runtimes from existing schedule |
| `--all-trains` | Schedule ALL 12,380 trains from TrainMaster (implies `--discover-routes`) |
| `--discover-routes` | Find routes via Dijkstra for trains without reference routes |
| `--derive-stoppages` | Use train-specific + per-station median stoppage model |
| `--start-time HH:MM:SS` | Custom start time for single-train mode |
| `--start-times-file FILE` | CSV with `MAVPROPOSALID,start_time` columns for batch overrides |
| `--train PROPOSAL_ID` | Generate for a single train only |
| `--verify` | Run arithmetic and speed verification |
| `--compare` | Compare against reference Train_Schedule.csv |
| `--no-conflicts` | Disable inter-train conflict resolution |
| `--output FILENAME` | Output file name (saved in `output/` subfolder) |

---

## Known Limitations

1. **Compute mode accuracy**: ~64% exact match (within 30s) — we lack the full ICMS speed model.
2. **Route discovery vs designated corridors**: Waypoint routing ensures mandatory stops are covered (100%), but intermediate segments may differ from operationally designated corridors.
3. **Minor data gaps**: 69 block sections missing from master; 7 trains unreachable.
4. **No day-of-week filtering**: Conflict resolver assumes all trains run on the same day.
5. **Stoppage model**: Train-specific maps give exact times for shared stations; the per-station median fallback covers non-reference stations.
