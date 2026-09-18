# =============================================================================
# File        : api_retry.py
# Description : Shared, provider-agnostic retry-with-backoff for the one-shot HTTP LLM providers (DeepSeek and Qwen).
# Author      : SorinoSSK
# Created On  : 2026-09-20
#
# Features    :
#   - run_with_retry() - re-runs one provider attempt while its own result says the failure was transient, backing off between attempts.
#   - RETRYABLE_STATUS_CODES - the shared set of HTTP statuses treated as transient, which each provider's own HTTP call uses to fill in its result and may narrow for itself.
#
# Notes       :
#   - Each provider's own attempt is expected to return a dict carrying "retryable" (bool) alongside its own fields - this module reads only that key and hands the dict back untouched.
#   - The attempt callable is expected to include its own asyncio.wait_for() bound, so every attempt gets a full timeout of its own. A timeout raises out of the attempt and out of run_with_retry() unchanged - it is never retried.
#   - Only fast, unambiguous failures are worth retrying - an HTTP 429/500/502/503/504 (a provider may narrow this for itself - qwen_interface.py drops 429), or a connection-level error. Every other 4xx, a malformed response and a timeout are permanent or ambiguous, and are the provider's own responsibility to mark as not retryable.
#   - Backoff is exponential with jitter, capped at _MAX_DELAY_SECONDS. A provider's Retry-After header is deliberately not read - neither DeepSeek nor DashScope documents sending one, so it was removed 2026-09-20.
#   - Sleeps with asyncio.sleep(), so a backing-off call never holds a worker thread.
#   - A total time budget (settings.API_RETRY_TOTAL_BUDGET_SECONDS) bounds when a new attempt may START - a retry is skipped if the time already spent plus its backoff would reach the budget. It never cancels an attempt already in flight, so the worst case is the budget plus one attempt's own timeout. Added 2026-09-20 because nothing above query_llm() bounds a call's total time - a session's worker thread blocks for the whole call - while Claude's own path is a single timeout.
#   - An optional context string (typically the caller's session_dir) is appended to the provider name in every log message, so a retry line can be tied to a session. Log-only - added 2026-09-20.
#   - See settings.API_RETRY_MAX_ATTEMPTS,settings.API_RETRY_BASE_DELAY_SECONDS and settings.API_RETRY_TOTAL_BUDGET_SECONDS in config.py.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import random
import asyncio
import logging

from collections.abc import Awaitable, Callable

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# HTTP statuses treated as transient. DeepSeek documents 429/500/503 as retry-after-waiting conditions, 502/504 are the usual gateway equivalents.
# A provider may narrow this set for itself - qwen_interface.py drops 429, since DashScope's 429s are mostly per-minute quotas that a few seconds of backoff will not clear.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Upper bound on any single wait between attempts.
_MAX_DELAY_SECONDS = 30

# =============================================================================

def _retry_delay_seconds(attempt: int) -> float:
    """
    Computes how long to wait before the next attempt.

    Args:
        attempt (int):
            The attempt number that just failed, starting at 1.

    Returns:
        float:
            The delay in seconds - exponential from settings.API_RETRY_BASE_DELAY_SECONDS, plus jitter, never more than _MAX_DELAY_SECONDS.
    """
    delay = settings.API_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1)
    delay += random.uniform(0, settings.API_RETRY_BASE_DELAY_SECONDS)
    return min(delay, _MAX_DELAY_SECONDS)

async def run_with_retry(attempt_call: Callable[[], Awaitable[dict]], provider: str, context: str | None = None) -> dict:
    """
    Runs attempt_call, repeating it while its own result marks the failure as transient.

    Args:
        attempt_call (Callable[[], Awaitable[dict]]):
            Builds and returns a fresh awaitable for one attempt each time it is called - typically a lambda wrapping asyncio.wait_for(asyncio.to_thread(...)). Its result dict must carry "retryable".

        provider (str):
            Display name used in log messages only, e.g. "DeepSeek".

        context (str | None):
            Optional extra detail appended to the provider name in log messages only, e.g. "session_dir=/data/sessions/abc/chat/deepseek". Has no effect on retry behaviour.

    Returns:
        dict:
            The last attempt's own result dict, untouched - either a success, a permanent failure, or the final transient failure once attempts ran out.

    Notes:
        - Total attempts are bounded by settings.API_RETRY_MAX_ATTEMPTS, including the first.
        - A retry is also skipped once the time already spent plus its own backoff would reach settings.API_RETRY_TOTAL_BUDGET_SECONDS. That gates only the start of a new attempt - an attempt in flight is never cancelled, so the worst case is the budget plus one attempt's own timeout.
        - An exception raised by an attempt, including asyncio.TimeoutError from its own wait_for(), propagates immediately without a retry.
        - Never raises on its own - the caller's existing timeout handling and None-on-failure behaviour are unchanged.
    """
    label = provider if context is None else f"{provider} ({context})"
    max_attempts = settings.API_RETRY_MAX_ATTEMPTS
    total_budget = settings.API_RETRY_TOTAL_BUDGET_SECONDS
    started_at = time.monotonic()
    attempt = 1
    while True:
        result = await attempt_call()
        if not result["retryable"]:
            return result
        elif attempt >= max_attempts:
            logger.error(f"{label} request still failing after {attempt} attempt(s) - giving up.")
            return result
        else:
            delay = _retry_delay_seconds(attempt)
            elapsed = time.monotonic() - started_at
            if elapsed + delay >= total_budget:
                logger.error(f"{label} request still failing after {attempt} attempt(s) - giving up, since another attempt would pass the {total_budget}s total retry budget ({elapsed:.1f}s spent, {delay:.1f}s backoff).")
                return result
            else:
                logger.warning(f"{label} request failed transiently (attempt {attempt}/{max_attempts}) - retrying in {delay:.1f}s.")
                await asyncio.sleep(delay)
                attempt += 1

# =============================================================================
