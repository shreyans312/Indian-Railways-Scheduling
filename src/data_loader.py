import json
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "preprocessed_data"


def _load_json(filename):
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(
            f"{filepath} not found. Run preprocess.py first."
        )
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

# Load all preprocessed data and return as a dict of lookup structures
def load_all():
    data = {}

    data['stations'] = _load_json("stations.json")
    print(f"Stations: {len(data['stations'])}")

    data['block_sections'] = _load_json("block_sections.json")
    print(f"Block sections: {len(data['block_sections'])}")

    data['trains'] = _load_json("train_master.json")
    print(f"Trains: {len(data['trains'])}")

    data['routes'] = _load_json("train_routes.json")
    print(f"Routes: {len(data['routes'])}")

    data['station_lines'] = _load_json("station_lines.json")
    print(f"Station lines: {len(data['station_lines'])}")

    data['platforms'] = _load_json("platforms.json")
    print(f"Platforms: {len(data['platforms'])}")

    data['block_section_lines'] = _load_json("block_section_lines.json")
    print(f"Block section lines: {len(data['block_section_lines'])}")

    data['line_connections'] = _load_json("line_connections.json")
    print(f"Line connections: {len(data['line_connections'])}")

    data['block_corridors'] = _load_json("block_corridors.json")
    print(f"Block corridors: {len(data['block_corridors'])}")

    return data
