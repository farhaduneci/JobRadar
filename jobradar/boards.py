"""Job-board fetchers, from RadarKit (radarkit.boards): this module only adapts them to JobRadar's sync code.

Row: {id, title, url, loc, date, desc, remote?, org?, team?}. A new board type is added in RadarKit, not here.
"""
from radarkit.boards import FETCHERS, board_of, fetch_sync, is_dead  # noqa: F401


def fetch(ats, tok, cutoff=None, eager=True):
    """Rows for one board, every description resolved (one request per role where the list lacks it)."""
    return fetch_sync(ats, tok, cutoff, eager)
