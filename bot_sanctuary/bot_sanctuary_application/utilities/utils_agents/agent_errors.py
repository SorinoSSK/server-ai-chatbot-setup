# =============================================================================
# File        : agent_errors.py
# Description : Builds the standard "error" tool replies an LLM provider interface returns in place of reply text, when a provider-level failure needs to reach the user as a specific error type rather than the generic None-on-failure result.
# Author      : SorinoSSK
# Created On  : 2026-09-20
#
# Features    :
#   - is_billing_failure() - decides whether an HTTP error means a provider's account balance or quota is exhausted.
#   - billing_exhausted_response() - the "error" tool reply for a provider whose account balance or quota is exhausted.
#
# Notes       :
#   - The returned dict is exactly the shape of an LLM's own "error" tool reply (see agent_tools.TOOLS), so it flows through call_dispatch_handler.py::message_dissect() and agent_tools.execute_tool() like any other agent-produced error, with no change to call_dispatch_handler.py. That path also publishes completed after the error, as it does for an LLM's own error reply.
#   - Returned by deepseek_interface.py and qwen_interface.py only today. Every other failure they hit still returns None.
#   - Deliberately a leaf module with no imports from this application, so the interfaces can import it without a circular import.
#   - The fixed message is the only text an end user ever sees from this - a provider's own response body is written to the log only. Until telegram_gateway gives billing_exhausted its own handling, its generic error branch shows this message as-is - see telegram_gateway's CODE_TODO.md.
#   - Replaced an LLMBillingError exception, same day - see CODE_TODO.md.
#
# =============================================================================

_BILLING_EXHAUSTED_MESSAGE = "The chat agent's usage allowance has run out for now. Please try again later."

def billing_exhausted_response() -> dict:
    """
    Builds the "error" tool reply for a provider whose account balance or quota is exhausted.

    Args:
        None

    Returns:
        dict:
            {"type": "error", "error_type": "billing_exhausted", "message": <fixed user-facing text>}.

    Notes:
        - A fresh dict on every call, never a shared one, since downstream code spreads it into a payload.
        - The message never contains the provider's own response text - see this module's own header Notes.
    """
    return {"type": "error", "error_type": "billing_exhausted", "message": _BILLING_EXHAUSTED_MESSAGE}

def is_billing_failure(status_code: int, body_text: str) -> bool:
    """
    Decides whether an HTTP error means the account's balance or quota is exhausted.

    Args:
        status_code (int):
            The HTTP status code the provider returned.

        body_text (str):
            The raw (decoded) error response body.

    Returns:
        bool:
            True for an exhausted balance or quota; False for every other failure.

    Notes:
        - HTTP 402 is DeepSeek's documented "Insufficient Balance" status. HTTP 429 with insufficient_quota in the body is DashScope's exhausted-quota response - a plain 429 without it stays an ordinary rate limit - retried for DeepSeek, not for Qwen (see qwen_interface.py).
        - Both signals come from documentation and search research, not from a real account. DashScope's overdue-account (Arrearage) response is deliberately not matched, since its status and code are unconfirmed - see CODE_TODO.md.
        - A billing failure must never also be marked retryable - the caller is responsible for that, since retrying an exhausted balance only adds delay.
        - Moved here from api_retry.py, same day, so billing logic lives only in this module and the two provider interfaces.
    """
    return status_code == 402 or (status_code == 429 and "insufficient_quota" in body_text.lower())

# =============================================================================
