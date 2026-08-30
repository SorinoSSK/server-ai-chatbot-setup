# =============================================================================
# File        : gatekeeper.py
# Description : File responsible for tracking repeated access attempts from unauthorised chats.
# Author      : SorinoSSK
# Created On  : 2026-08-30
#
# Features    :
#   - Tracks unauthorised chat_id access counts in a fixed-size cache.
#
# Notes       :
#   - In-memory only - not persisted, resets on application restart.
#   - Eviction only considers the oldest window of entries, and within that
#     window prefers the lowest access count - new entries get a genuine
#     grace period instead of being the global minimum on arrival.
#   - Access counts are capped so a single chat_id cannot spam its way into
#     permanent, unevictable protection.
#
# =============================================================================
# I M P O R T   H E A D E R

from collections import OrderedDict

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

_access_counts: OrderedDict[int, int] = OrderedDict()

# =============================================================================

def _evict() -> None:
    """
    Evicts the lowest access count among the oldest window of entries, breaking ties by oldest access.

    Args:
        None

    Returns:
        None

    Notes:
        - _access_counts is ordered oldest -> most recent (move_to_end on every repeat access).
        - Window size is settings.TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT of the cache - only
          the oldest entries in that window are eviction candidates, so a fresh entry is protected
          until it ages into the window, rather than being the global minimum on arrival.
        - min() returns the first match on ties, so ties naturally resolve to the oldest candidate.
    """
    window_size = max(1, len(_access_counts) * settings.TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT // 100)
    candidates = list(_access_counts)[:window_size]

    victim_chat_id = min(candidates, key=lambda cid: _access_counts[cid])
    _access_counts.pop(victim_chat_id)

def track_unauthorised_access(chat_id: int) -> int | None:
    """
    Tracks an unauthorised chat_id's access count, evicting from the cache once full.

    Args:
        - chat_id (int)

    Returns:
        - int | None:
            chat_id if this is its first tracked access; otherwise None.

    Notes:
        - Every call counts as an access and moves chat_id to most-recently-used.
        - Cache size is capped at settings.TELEGRAM_UNAUTHORISED_CACHE_SIZE.
        - Access count is capped at settings.TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP.
        - See _evict() for eviction order.
    """
    is_first_access = chat_id not in _access_counts

    if is_first_access:
        if len(_access_counts) >= settings.TELEGRAM_UNAUTHORISED_CACHE_SIZE:
            _evict()
        _access_counts[chat_id] = 1
    else:
        _access_counts.move_to_end(chat_id)
        if _access_counts[chat_id] < settings.TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP:
            _access_counts[chat_id] += 1

    return chat_id if is_first_access else None

# =============================================================================
