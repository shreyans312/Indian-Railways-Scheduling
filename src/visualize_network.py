#!/usr/bin/env python3
"""
Railway Network Visualizer
Renders the Indian Railway network graph using networkx + matplotlib.

Usage:
    python3 src/visualize_network.py                          # Full network
    python3 src/visualize_network.py --train CR24251150       # Highlight route
    python3 src/visualize_network.py --train CR24251150 --compare  # Compare ref vs Dijkstra
    python3 src/visualize_network.py --train X --discover     # Dijkstra route only
"""

import json
import argparse
import os
import sys

import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'preprocessed_data')


def load_data():
    data = {}
    for name in ['stations', 'block_sections', 'train_routes', 'train_master']:
        with open(os.path.join(DATA_DIR, f'{name}.json')) as f:
            data[name] = json.load(f)
    return data['stations'], data['block_sections'], data['train_routes'], data['train_master']


def build_graph(stations, block_sections):
    G = nx.DiGraph()
    pos = {}
    for code, stn in stations.items():
        lat = float(stn.get('latitude', 0) or 0)
        lon = float(stn.get('longitude', 0) or 0)
        if lat != 0 and lon != 0:
            G.add_node(code)
            pos[code] = (lon, lat)

    for bs_id, bs in block_sections.items():
        frm, to = bs.get('from_station'), bs.get('to_station')
        if frm in pos and to in pos:
            G.add_edge(frm, to, bs_id=bs_id,
                       distance=float(bs.get('distance_km', 0) or 0),
                       gauge=bs.get('gauge', 'B'))
    return G, pos


def get_ref_route(train_id, train_routes):
    legs = train_routes.get(train_id, [])
    if not legs:
        return [], []
    sorted_legs = sorted(legs, key=lambda x: int(x.get('seq', 0)))
    stations = [leg['station'] for leg in sorted_legs]
    edges = [(stations[i], stations[i + 1]) for i in range(len(stations) - 1)]
    return edges, stations


def get_dijkstra_route(train_id, train_master):
    sys.path.insert(0, os.path.join(BASE_DIR, 'implementation_claude'))
    from route_finder import RouteFinder
    from data_loader import load_all

    data = load_all()
    finder = RouteFinder(data['block_sections'], data.get('line_connections', {}),
                         data.get('stations', {}))

    tm = train_master.get(train_id)
    if not tm:
        print(f"  Train {train_id} not found in TrainMaster")
        return [], []
    origin, dest, gauge = tm.get('origin', ''), tm.get('destination', ''), tm.get('gauge', 'B')

    # Use waypoint routing with only STOPPING stations from reference
    waypoints = []
    routes = data.get('routes', {})
    if train_id in routes:
        sorted_legs = sorted(routes[train_id], key=lambda x: int(x.get('seq', 0)))
        waypoints = [l['station'] for l in sorted_legs if l.get('stoppage_time', 0) > 0]

    if waypoints:
        route = finder.find_route_via_waypoints(origin, dest, waypoints, gauge)
    else:
        route = finder.find_route(origin, dest, gauge)

    if not route:
        print(f"  No Dijkstra route found: {origin} → {dest}")
        return [], []
    stations = [leg['station'] for leg in route]
    edges = [(stations[i], stations[i + 1]) for i in range(len(stations) - 1)]
    return edges, stations


def _draw_base(G, pos, ax, edge_width=0.3, node_size=1):
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color='#333355',
                           width=edge_width, alpha=0.5, arrows=False, node_size=0)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=node_size,
                           node_color='#555577', alpha=0.4)


def _draw_route(G, pos, ax, edges, stations, edge_color, node_color,
                edge_width=2.5, node_size=15, label_endpoints=True, fontsize=9):
    valid_edges = [(u, v) for u, v in edges if G.has_node(u) and G.has_node(v)]
    valid_stns = [s for s in stations if s in pos]
    if not valid_edges:
        return
    nx.draw_networkx_edges(G, pos, edgelist=valid_edges, ax=ax,
                           edge_color=edge_color, width=edge_width,
                           alpha=0.85, arrows=True, arrowsize=8, node_size=0)
    nx.draw_networkx_nodes(G, pos, nodelist=valid_stns, ax=ax,
                           node_size=node_size, node_color=node_color,
                           edgecolors=edge_color, linewidths=0.5, alpha=0.85)
    if label_endpoints and valid_stns:
        for stn, lbl, clr in [(valid_stns[0], f"ORIGIN: {valid_stns[0]}", '#00ff88'),
                               (valid_stns[-1], f"DEST: {valid_stns[-1]}", '#ff6666')]:
            if stn in pos:
                ax.annotate(lbl, pos[stn], fontsize=fontsize, fontweight='bold', color=clr,
                            ha='left', va='bottom', xytext=(8, 8), textcoords='offset points',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e',
                                      edgecolor=clr, alpha=0.9))


def _label_stations(ax, pos, stations, color, step_div=10):
    valid = [s for s in stations if s in pos]
    step = max(1, len(valid) // step_div)
    for i in range(0, len(valid), step):
        ax.annotate(valid[i], pos[valid[i]], fontsize=5, color=color,
                    ha='left', va='bottom', xytext=(3, 3), textcoords='offset points')


def _zoom_bounds(pos, stations_list):
    # Compute zoom bounds from one or more station lists
    all_stns = set()
    for sl in stations_list:
        all_stns.update(sl)
    valid = [s for s in all_stns if s in pos]
    if not valid:
        return None, None
    lons = [pos[s][0] for s in valid]
    lats = [pos[s][1] for s in valid]
    px = max((max(lons) - min(lons)) * 0.15, 0.5)
    py = max((max(lats) - min(lats)) * 0.15, 0.5)
    return (min(lons) - px, max(lons) + px), (min(lats) - py, max(lats) + py)


# Single-route visualization

def visualize_single(G, pos, edges, stations, train_id, output):
    fig = plt.figure(figsize=(28, 18), dpi=100)
    fig.patch.set_facecolor('#1a1a2e')
    ax_full = fig.add_axes([0.01, 0.03, 0.54, 0.90])
    ax_zoom = fig.add_axes([0.56, 0.03, 0.43, 0.90])
    for a in [ax_full, ax_zoom]:
        a.set_facecolor('#1a1a2e')

    _draw_base(G, pos, ax_full)
    _draw_route(G, pos, ax_full, edges, stations, '#ff4444', '#ffcc00')
    ax_full.set_axis_off()

    xlim, ylim = _zoom_bounds(pos, [stations])
    _draw_base(G, pos, ax_zoom, edge_width=0.5, node_size=3)
    _draw_route(G, pos, ax_zoom, edges, stations, '#ff4444', '#ffcc00',
                edge_width=3.5, node_size=30, fontsize=10)
    _label_stations(ax_zoom, pos, stations, '#ccccee', 12)
    if xlim:
        ax_zoom.set_xlim(*xlim); ax_zoom.set_ylim(*ylim)
        rect = plt.Rectangle((xlim[0], ylim[0]), xlim[1]-xlim[0], ylim[1]-ylim[0],
                              lw=1.5, edgecolor='#ffcc00', facecolor='none', ls='--', alpha=0.7)
        ax_full.add_patch(rect)
    ax_zoom.set_title("Route Detail (Zoomed)", fontsize=13, fontweight='bold', color='#aaaacc', pad=10)
    ax_zoom.set_axis_off()

    fig.suptitle(f"Indian Railway Network  —  Train {train_id}",
                 fontsize=16, fontweight='bold', color='white', y=0.97)
    fig.text(0.5, 0.945, f"{G.number_of_nodes():,} stations  •  Route: {len(edges)} edges",
             fontsize=10, color='#aaaacc', ha='center')
    legend = [mpatches.Patch(color='#333355', label='Network'),
              mpatches.Patch(color='#ff4444', label='Route'),
              mpatches.Patch(color='#ffcc00', label='Stations')]
    ax_full.legend(handles=legend, loc='lower left', fontsize=9,
                   facecolor='#1a1a2e', edgecolor='#555577', labelcolor='white')
    plt.savefig(output, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    print(f"Saved to {output}")


# Comparison visualization

def visualize_compare(G, pos, ref_edges, ref_stns, dij_edges, dij_stns, train_id, output):
    fig = plt.figure(figsize=(30, 18), dpi=100)
    fig.patch.set_facecolor('#1a1a2e')

    ax_full = fig.add_axes([0.01, 0.03, 0.44, 0.90])
    ax_ref  = fig.add_axes([0.47, 0.50, 0.52, 0.44])
    ax_dij  = fig.add_axes([0.47, 0.03, 0.52, 0.44])
    for a in [ax_full, ax_ref, ax_dij]:
        a.set_facecolor('#1a1a2e')

    ref_set = set(ref_edges)
    dij_set = set(dij_edges)
    shared = ref_set & dij_set
    ref_only = ref_set - dij_set
    dij_only = dij_set - ref_set
    ref_stn_set = set(ref_stns)
    dij_stn_set = set(dij_stns)
    shared_stns = ref_stn_set & dij_stn_set
    union_edges = ref_set | dij_set
    union_stns = ref_stn_set | dij_stn_set

    xlim, ylim = _zoom_bounds(pos, [ref_stns, dij_stns])

    # Full map: both overlaid
    _draw_base(G, pos, ax_full)
    _draw_route(G, pos, ax_full, ref_edges, ref_stns, '#4fc3f7', '#4fc3f7',
                edge_width=2.0, node_size=8, label_endpoints=True)
    _draw_route(G, pos, ax_full, dij_edges, dij_stns, '#66bb6a', '#66bb6a',
                edge_width=2.0, node_size=8, label_endpoints=False)
    ax_full.set_axis_off()

    # Reference zoomed (top-right)
    _draw_base(G, pos, ax_ref, edge_width=0.5, node_size=3)
    if shared:
        _draw_route(G, pos, ax_ref, list(shared), list(shared_stns),
                    '#ffffff', '#ffffff', edge_width=2.5, node_size=18, label_endpoints=False)
    _draw_route(G, pos, ax_ref, list(ref_only) if ref_only else ref_edges,
                ref_stns, '#4fc3f7', '#4fc3f7',
                edge_width=3.5, node_size=25, label_endpoints=True)
    _label_stations(ax_ref, pos, ref_stns, '#90caf9')
    if xlim:
        ax_ref.set_xlim(*xlim); ax_ref.set_ylim(*ylim)
    ax_ref.set_title(f"Reference Route (Train_Schedule.csv)  •  {len(ref_edges)} edges, {len(ref_stns)} stations",
                     fontsize=11, fontweight='bold', color='#4fc3f7', pad=8)
    ax_ref.set_axis_off()

    # Dijkstra zoomed (bottom-right)
    _draw_base(G, pos, ax_dij, edge_width=0.5, node_size=3)
    if shared:
        _draw_route(G, pos, ax_dij, list(shared), list(shared_stns),
                    '#ffffff', '#ffffff', edge_width=2.5, node_size=18, label_endpoints=False)
    _draw_route(G, pos, ax_dij, list(dij_only) if dij_only else dij_edges,
                dij_stns, '#66bb6a', '#66bb6a',
                edge_width=3.5, node_size=25, label_endpoints=True)
    _label_stations(ax_dij, pos, dij_stns, '#a5d6a7')
    if xlim:
        ax_dij.set_xlim(*xlim); ax_dij.set_ylim(*ylim)
    ax_dij.set_title(f"Dijkstra Route (Discovered)  •  {len(dij_edges)} edges, {len(dij_stns)} stations",
                     fontsize=11, fontweight='bold', color='#66bb6a', pad=8)
    ax_dij.set_axis_off()

    # Title + stats
    pct_edge = len(shared) / max(len(union_edges), 1) * 100
    pct_stn = len(shared_stns) / max(len(union_stns), 1) * 100
    fig.suptitle(f"Route Comparison  —  Train {train_id}",
                 fontsize=16, fontweight='bold', color='white', y=0.97)
    fig.text(0.5, 0.945,
             f"Edge overlap: {len(shared)}/{len(union_edges)} ({pct_edge:.1f}%)  •  "
             f"Station overlap: {len(shared_stns)}/{len(union_stns)} ({pct_stn:.1f}%)  •  "
             f"White = shared",
             fontsize=10, color='#aaaacc', ha='center')

    legend = [
        mpatches.Patch(color='#4fc3f7', label=f'Reference ({len(ref_edges)} edges)'),
        mpatches.Patch(color='#66bb6a', label=f'Dijkstra ({len(dij_edges)} edges)'),
        mpatches.Patch(color='#ffffff', label=f'Shared ({len(shared)} edges)'),
    ]
    ax_full.legend(handles=legend, loc='lower left', fontsize=9,
                   facecolor='#1a1a2e', edgecolor='#555577', labelcolor='white')

    plt.savefig(output, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    print(f"Saved to {output}")


# Full network only

def visualize_network_only(G, pos, output):
    fig, ax = plt.subplots(1, 1, figsize=(24, 18), dpi=100)
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    _draw_base(G, pos, ax)
    ax.set_axis_off()
    fig.suptitle("Indian Railway Network Graph", fontsize=16, fontweight='bold', color='white', y=0.97)
    fig.text(0.5, 0.945, f"{G.number_of_nodes():,} stations  •  {G.number_of_edges():,} directed edges",
             fontsize=10, color='#aaaacc', ha='center')
    ax.legend(handles=[mpatches.Patch(color='#333355', label='Railway network')],
              loc='lower left', fontsize=9,
              facecolor='#1a1a2e', edgecolor='#555577', labelcolor='white')
    plt.savefig(output, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    print(f"Saved to {output}")


def main():
    parser = argparse.ArgumentParser(description='Railway Network Visualizer')
    parser.add_argument('--train', help='Train ID to highlight')
    parser.add_argument('--discover', action='store_true', help='Use Dijkstra route only')
    parser.add_argument('--compare', action='store_true', help='Compare reference vs Dijkstra routes')
    parser.add_argument('--output', '-o', default=None, help='Output image path')
    args = parser.parse_args()

    print("Loading data...")
    stations, block_sections, train_routes, train_master = load_data()

    print("Building graph...")
    G, pos = build_graph(stations, block_sections)
    print(f"  Nodes: {G.number_of_nodes():,}  Edges: {G.number_of_edges():,}")

    out_dir = os.path.join(BASE_DIR, 'implementation_claude', 'output')
    os.makedirs(out_dir, exist_ok=True)

    if args.train and args.compare:
        # Compare mode: reference vs Dijkstra
        output = args.output or os.path.join(out_dir, 'route_comparison.png')
        print(f"Getting reference route for {args.train}...")
        ref_edges, ref_stns = get_ref_route(args.train, train_routes)
        if not ref_edges:
            print(f"No reference route found for {args.train}")
            return
        print(f"Reference: {len(ref_edges)} edges, {ref_stns[0]} → {ref_stns[-1]}")

        print(f"Getting Dijkstra route for {args.train}...")
        dij_edges, dij_stns = get_dijkstra_route(args.train, train_master)
        if not dij_edges:
            print(f"No Dijkstra route found for {args.train}")
            return
        print(f"Dijkstra:  {len(dij_edges)} edges, {dij_stns[0]} → {dij_stns[-1]}")

        # Stats
        shared = set(ref_edges) & set(dij_edges)
        print(f"Shared edges: {len(shared)}/{len(set(ref_edges) | set(dij_edges))}")

        print("Rendering comparison...")
        visualize_compare(G, pos, ref_edges, ref_stns, dij_edges, dij_stns, args.train, output)

    elif args.train:
        output = args.output or os.path.join(out_dir, 'network_train_route.png')
        print(f"Finding route for {args.train}...")
        if args.discover:
            edges, stns = get_dijkstra_route(args.train, train_master)
        else:
            edges, stns = get_ref_route(args.train, train_routes)
        if not edges:
            return
        print(f"  Route: {len(edges)} edges, {stns[0]} → {stns[-1]}")
        print("Rendering...")
        visualize_single(G, pos, edges, stns, args.train, output)

    else:
        output = args.output or os.path.join(out_dir, 'network_graph.png')
        print("Rendering full network...")
        visualize_network_only(G, pos, output)

    print("Done.")


if __name__ == '__main__':
    main()
