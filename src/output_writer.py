
# Writes generated schedule data to CSV in the exact 63-column format as CRIS uses

import csv
from pathlib import Path

# The exact 63 columns in order
OUTPUT_COLUMNS = [
    'MAVPROPOSALID',
    'MANSEQNUMBER',
    'MAVSTTNCODE',
    'MAVBLCKSCTN',
    'MAVCOABLCKSCTN',
    'MANWTTARVL',
    'MANWTTDPRT',
    'MANWTTNEXTARVL',
    'MANWTTDAYOFRUN',
    'MANPTTARVL',
    'MANPTTDPRT',
    'MANPTTDAYOFRUN',
    'MANRUNTIME',
    'MANSTPGTIME',
    'MANCSTPGTIME',
    'MANACCTIME',
    'MANDECTIME',
    'MANTRFCALWC',
    'MANENGGALWC',
    'MANSTARTBUFFER',
    'MANENDBUFFER',
    'MANCONSTRAINTTIME',
    'MAVCONSTRAINTREASON',
    'MANINTRDIST',
    'MANCUMDISTANCE',
    'MANMAXSPEED',
    'MANBSSPEED',
    'MANTRAINMPS',
    'MAVPLATFORMNUMB',
    'MAVZONECODE',
    'MAVDVSNCODE',
    'MAVBLCKSCTNZONE',
    'MAVBLCKSCTNDVSN',
    'MANZONEIC',
    'MANDVSNIC',
    'MAVMDFYBY',
    'MADMDFYTIME',
    'MAVPFREASON',
    'MAVBLCKBUSYDAYS',
    'MAVCROSSINGFLAG',
    'MAVCROSSINGTRAIN',
    'MAVCROSSINGTIME',
    'MACRVSLSTTN',
    'MANRVSLTIME',
    'MACCREWCHNG',
    'MAVCREWCHNGCODE',
    'MACLOCOCHANGE',
    'MAVTRTNCODE',
    'MACGARBG',
    'MACWATER',
    'MAVPLATFORMNUMB_NEW',
    'MAVSTTNLINE',
    'MAVPFDRTN',
    'MAVSTTNLINE_NEW',
    'MAVPFDRTN_NEW',
    'MANNOTIFICATIONFLAG',
    'MACCLASSFLAG',
    'MACREPORTINGFLAG',
    'MAVBLCKSCTNLINE',
    'MANTRAINID',
    'MAVTRAINNUMBER',
    'MAVPLATFORMNUMBER_NEW',
    'MACHSDFUELING',
]


def write_schedule(rows, output_path, columns=None):
    """
    Write schedule rows to a CSV file.

    Parameters:
        rows: list of dicts, each representing one schedule row
        output_path: path to output CSV file
        columns: list of column names (defaults to OUTPUT_COLUMNS)
    """
    if columns is None:
        columns = OUTPUT_COLUMNS

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            # Ensure all columns have a value (empty string for missing)
            clean_row = {}
            for col in columns:
                val = row.get(col, '')
                if val is None:
                    val = ''
                clean_row[col] = val
            writer.writerow(clean_row)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Written {len(rows)} rows to {output_path} ({size_mb:.1f} MB)")
    return output_path
