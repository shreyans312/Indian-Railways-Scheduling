# Data Reference

Complete documentation of all input data files, output format, and key data insights.

---

## 1. Input Data Files

### 1.1 Train Master (`01_TrainMaster`)
- **10,006 rows** | Train-level properties
- Each row = one train proposal: proposal ID, train number, name, type (Rajdhani/Shatabdi/Express/etc.), origin, destination, departure time, max permissible speed (MPS), gauge, traction type, rake type, loco type, number of coaches, days of service, owning railway/division, total distance, total runtime, total stoppages.

### 1.2 Station Master (`03_Station`)
- **9,350 rows** | Every station/halt in the network
- Each row: station code (e.g. `NDLS`, `CSTM`), station name, zone, division, latitude/longitude, junction flag, halt flag, traffic type, traction change point, crew change point, interlocking standard, signal arrangement, state code, start/end buffer times.

### 1.3 Block Section Master (`04_BlockSctn`)
- **23,331 rows** | Track segments between consecutive stations
- Each row: section ID (format `FROM_STATION-TO_STATION`), from/to station codes, distance (km), number of parallel track lines, number of signals, gauge, traction type, max speed, direction (UP/DN), section code.
- A block section is the fundamental unit of track — a train occupies one block section at a time.

### 1.4 Station Lines (`05_StationLine`)
- **30,407 rows** | Track lines within stations
- Each row: line number, line type (MAIN/LOOP/SIDING), category, length, direction, capacity, gauge, traction type, speed, platform attachment flag.

### 1.5 Platforms (`06_Platform`)
- **15,481 rows** | Physical platforms at stations
- Each row: station code, platform number, vertical/horizontal position, length, type, capacity.

### 1.6 Block Section Lines (`07_BlockSctnLine`)
- **28,576 rows** | Individual track lines within block sections
- Each row: line number, length, category, max speed, direction.
- Distinguishes single-line vs double-line vs multi-line sections.

### 1.7 Line Connections (`08_LineConnection`)
- **97,896 rows** | How station lines connect to block section lines
- Each row: station line ↔ block section line mapping, with receive/send direction flag.
- Defines the physical connectivity constraints of the track network.

### 1.8 Station Position (`09_StationPosition`)
- **21,607 rows** | Geographic ordering of stations within corridors
- Each row: station's position on a block section corridor (section code, sequence number).

### 1.9 Curvature Data (`11_Curvature`)
- **58,223 rows** | Track curvature penalties
- Each row: curve on a block section (from/to km marks, curvature degree, time loss for passenger and goods trains).
- Multiple curves per block section — aggregated during preprocessing.

### 1.10 Speed Restrictions (`12_SpeedRestrictions`)
- **6,578 rows** | Temporary/permanent speed limits
- Each row: restriction on a block section (from/to km, restricted speed, distance, reason, status).

### 1.11 Block Corridors (`13_BlockCorridor`)
- **12,031 rows** | Time-based corridor availability windows
- Each row: block section, from/to time, from/to date, days of service, permanent/temporary flag.

### 1.12 Train Schedule (`Train_Schedule.csv`) — Reference
- **374,935 rows, 63 columns** | The target output format
- Contains 2,772 unique trains, each with an ordered sequence of station visits.
- Serves as both the reference for validation AND the source of route data for pre-defined trains.

---

## 2. Output Format

The generated timetable has exactly **63 columns** matching `Train_Schedule.csv`:

### Key Columns

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

## 3. Key Data Insights

### Network Scale
- **9,339 stations** connected by **23,331 directed block sections**
- **12,380 trains** in TrainMaster (origin+destination for 12,379)
- **2,772 trains** with full reference routes; **9,601 routes discovered** via Dijkstra
- Total output: **916,349 schedule rows** across 12,373 trains

### Stopping Pattern
- **83.6%** of station entries are pass-throughs (stoppage = 0)
- Only **16.4%** are actual stops (including origin/destination)
- Average train covers 135 stations but stops at only ~22

### Time Representation
- All times are **cumulative seconds from midnight of Day 1**
- Times never reset at midnight — a train arriving at 25:00:00 (next day 1 AM) has `MANWTTARVL = 90000`
- `MANWTTDAYOFRUN = floor(time / 86400) + 1`

### Block Section Naming
- 100% of block section IDs follow the pattern `FROM_STATION-TO_STATION`
- Direction is encoded in the name: `A-B` is the edge from A to B; `B-A` goes the other way

### Track Capacity
- ~12,000 single-line sections (bidirectional conflict checking needed)
- ~9,000 double-line sections
- ~1,600 sections with 3+ lines

### Line Selection
- **79.2%** of station stops have multiple valid line options
- Line categories: M (Main) = 82% of reference, L (Loop), S (Siding), Y (Yard)
- 6,877 stations have line connection data constraining valid choices
