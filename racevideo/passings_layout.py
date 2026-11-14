"""Align CrossMgr positions while retaining unranked visual evidence between them."""
from bisect import bisect_right


def ranked(cell):
    return cell.get('origin') == 'CrossMgr' and cell.get('rider_lap', 0) is not None and not cell.get('grouped_under')


def layout(cells, columns):
    """Return shared rows; only CrossMgr lap passings consume a position number.

    Each gap gets enough unnumbered rows for all candidates in its busiest lap.
    Other lap columns leave those rows blank, so the numbered rows stay aligned.
    """
    assigned = {}
    extras = {}
    maximum = 0
    for column in columns:
        members = [c for c in cells if c['column'] == column]
        ordered = sorted((c for c in members if ranked(c)), key=lambda c: (c['at_ns'], c['cell_key']))
        assigned[column] = ordered
        maximum = max(maximum, len(ordered))
        times = [c['at_ns'] for c in ordered]
        for cell in sorted((c for c in members if not ranked(c)), key=lambda c: (c.get('sort_ns', c['at_ns']), c['cell_key'])):
            gap = bisect_right(times, cell.get('sort_ns', cell['at_ns']))
            extras.setdefault((column, gap), []).append(cell)
    rows = []
    for gap in range(maximum + 1):
        count = max((len(extras.get((col, gap), [])) for col in columns), default=0)
        for index in range(count):
            rows.append(dict(position=None, cells={col: extras[col, gap][index] for col in columns if len(extras.get((col, gap), [])) > index}))
        if gap < maximum:
            rows.append(dict(position=gap + 1, cells={col: assigned[col][gap] for col in columns if len(assigned[col]) > gap}))
    return rows
