# =============================================================================
# File        : image_draft_handler.py
# Description : File responsible for warning about and closing a pending draft (media received without an instruction yet).
# Author      : SorinoSSK
# Created On  : 2026-08-31
#
# Features    :
#   - Runs a per-chat_id background loop keeping a pending draft alive through a fixed schedule of repeating "keep-alive" cycles (DRAFT_CLOSE_SECONDS worth, in DRAFT_CYCLE_SECONDS segments).
#     Each cycle shows "typing...", then sends a notice partway through asking the user to press a button if they need more time; the rest of the cycle then waits silently (no further typing indicator) for the cycle to end - closing the draft unless the button was pressed at some point during the cycle, in which case it moves on to the next scheduled cycle instead.
#   - Pressing the button sends an acknowledgement and preserves the current cycle's remaining wait rather than cutting it short - the cycle still only advances (or closes) once its full duration has genuinely elapsed; the final cycle's notice has no button instead, since it's the last one - it always closes at its own end, regardless of response.
#   - close_orphaned_drafts() sweeps Redis on startup for drafts left behind by a keep-alive loop that did not survive the previous run (e.g. an app restart), closing each one out immediately rather than leaving it silently pending.
#
# Notes       :
#   - In-memory only - not persisted. Redis-side draft record has its own TTL as backstop.
#   - _lock guards both _active_drafts membership and each control dict's own "action"/"event" field mutations - _stop_draft_loop()/continue_draft_timer() (called from whichever thread handles an incoming Telegram update) and _consume_continue() (called from the per-chat _draft_loop() background thread) all mutate the same shared control fields, so all three hold _lock across those mutations.
#   - Per cycle (length DRAFT_CYCLE_SECONDS), one "typing..." window, DRAFT_TYPING_LEAD_SECONDS long, immediately precedes the cycle's one message:
#       - the notice, at DRAFT_CYCLE_SECONDS-DRAFT_CYCLE_NOTICE_LEAD_SECONDS into the cycle.
#       - the close message (final cycle only, if it ends with no response) is sent after the cycle's own silent close-point wait - no typing indicator immediately precedes it.
#   - A button press at any point up to the cycle's end sends an acknowledgement, but the cycle's remaining wait still plays out in full before it advances - a press does not shorten it, it only decides whether the draft is allowed to reach its next cycle instead of closing.
#   - Total draft lifetime is capped at DRAFT_CLOSE_SECONDS - reachable only if the button is pressed on every non-final cycle; an unanswered cycle closes the draft immediately rather than reaching the remaining scheduled cycles.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import random
import logging
import threading

from ....config import settings
from ..gateway_outbound import send_message
from .typing_indicator import start_typing, stop_typing
from .button_prompt_handler import register_bot_button, send_message_with_buttons
from ...utils_redis.database import delete_chat_draft, get_chat_draft, get_all_chat_draft_ids

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# chat_id -> {"event": threading.Event, "action": "stop" | "continue" | None}
_active_drafts: dict[int, dict] = {}

_CONTINUE_PURPOSE = "draft_continue"
_CONTINUE_BUTTON_TEXT = "Give me a little while more"

# Sent partway through a regular cycle, with the continue button attached.
_CYCLE_NOTICE_MESSAGES = [
    "{bot_name} is still here... just quietly waiting with her headphones on.",
    "Hey... {bot_name} hasn't heard from you in a while. You still there?",
    "{bot_name} is starting to wonder if you got distracted by something shiny.",
    "Psst... {bot_name} is still waiting. The playlist hasn't ended yet.",
    "{bot_name} is still here, just staring at the sky and waiting for your reply.",
    "Hey, you disappeared. {bot_name} is beginning to think the Wi-Fi ate you.",
    "{bot_name} hasn't gone anywhere. Take your time... I'll wait.",
    "Still there? {bot_name} was just about to put on another song.",
    "{bot_name} is waiting patiently... though she might start debugging something while she waits.",
    "Um... hello? {bot_name} is still here. Don't leave me hanging like this.",
]

# Sent partway through the final cycle - no button, since there's no more time to give.
_FINAL_NOTICE_MESSAGES = [
    "{bot_name} should probably get back to her work soon. Are you still coming?",
    "Hey, I need to get back to something I was working on soon. Anything you want me to do first?",
    "{bot_name} has a little project waiting for her. If you need anything, now's probably a good time.",
    "I've got something I need to take care of soon... so tell me if there's anything you still need.",
    "{bot_name} should get back to her laptop before the evening gets away from her. Anything else?",
    "My playlist is almost done and I still have some work to finish. Anything you need before I go?",
    "{bot_name} has been waiting, but there's something else calling for her attention now.",
    "I probably shouldn't keep putting this off... I've got something I need to finish. Anything for me?",
    "Okay, I need to get back to my little project soon. Say something if you still need me.",
    "{bot_name} has something waiting for her, so she won't be able to stay much longer. Need anything before I go?",
]

# Sent when the continue button is pressed.
_ACCEPT_MESSAGES = [
    "Okay, I'll wait here. Just don't disappear for too long, okay?",
    "No rush. {bot_name} will be right here when you're ready.",
    "Got it. {bot_name} will stay right here and wait for you.",
    "Alright... I'll wait. I have my music to keep me company anyway.",
    "Take your time. {bot_name} isn't in a hurry.",
    "Okay. I'll leave the playlist running while I wait.",
    "Sure. {bot_name} will be here when you get back.",
    "Alright, I'll wait patiently. No need to rush.",
    "Mm, okay. Take your time — I'll be here.",
    "Got it. {bot_name} will wait quietly until you’re ready.",
]

# =============================================================================

def _typing_key(chat_id: int) -> str:
    """
    Builds the typing_indicator.py registry key used for a draft's "typing..." pings, distinct from a task_id's own key.

    Args:
        chat_id (int)

    Returns:
        str:
            The key used to start/stop the typing indicator for this draft.
    """
    return f"draft:{chat_id}"

def _random_message(messages: list[str]) -> str:
    """
    Picks a random message template from messages and fills in the bot's name.

    Args:
        messages (list[str]):
            Templates containing a {bot_name} placeholder.

    Returns:
        str:
            The chosen message, with {bot_name} filled in.
    """
    return random.choice(messages).format(bot_name=settings.TELEGRAM_BOT_NAME)

def _build_continue_button(chat_id: int) -> list[list[dict]]:
    """
    Registers the "give me a little while more" button, ready to slot into a keyboard row.

    Args:
        chat_id (int)

    Returns:
        list[list[dict]]:
            [[{"text": ..., "callback_data": ...}]] if registered successfully; otherwise [].
    """
    button = register_bot_button(_CONTINUE_BUTTON_TEXT, _CONTINUE_PURPOSE, chat_id)
    return [[button]] if button else []

def _stop_draft_loop(chat_id: int) -> None:
    """
    Removes chat_id from the active registry and signals its loop to stop, if present.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - The control dict's own action/event fields are mutated under _lock too, not just
          _active_drafts membership - keeps this in sync with continue_draft_timer()/
          _consume_continue(), which mutate the same shared fields from other threads.
    """
    with _lock:
        control = _active_drafts.pop(chat_id, None)
        if control is not None:
            control["action"] = "stop"
            control["event"].set()

    if control is not None:
        logger.info(f"Stopped draft keep-alive timer for chat_id={chat_id}.")

def continue_draft_timer(chat_id: int) -> bool:
    """
    Signals an active draft's loop that a continue press was received, in response to a button
    press - this is what allows the draft to reach its next scheduled cycle instead of closing at
    the end of the one currently in progress.

    Args:
        chat_id (int)

    Returns:
        bool:
            True if a draft timer was active for chat_id and was signalled; otherwise False.

    Notes:
        - Does not shorten the cycle currently in progress (see _draft_loop()) - its own remaining
          wait still plays out in full; this only decides whether the loop is allowed to advance
          once that wait ends, rather than closing the draft.
        - The control dict's own action/event fields are mutated under _lock too, not just
          _active_drafts membership - keeps this in sync with _stop_draft_loop()/
          _consume_continue(), which mutate the same shared fields from other threads.
    """
    with _lock:
        control = _active_drafts.get(chat_id)
        if control is not None:
            control["action"] = "continue"
            control["event"].set()

    if control is None:
        return False
    else:
        logger.info(f"Draft keep-alive continue signalled for chat_id={chat_id} - draft will reach its next scheduled cycle.")
        return True

def _send_close_message(chat_id: int, media_type: str) -> None:
    """
    Sends the standard "draft cleared" message for a chat_id.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file" - used to word the message.

    Returns:
        None

    Notes:
        - Shared by _draft_loop()'s own hard-close and close_orphaned_drafts(), so both close a draft out identically.
    """
    send_message(
        chat_id,
        f"{settings.TELEGRAM_BOT_NAME} will be doing other work for now - feel free to tell "
        f"{settings.TELEGRAM_BOT_NAME} what you'd like help with and resend the {media_type} "
        f"when you're ready."
    )

def _consume_continue(control: dict, is_final_cycle: bool) -> bool:
    """
    Consumes a pending "continue" signal on control, if one is present and valid for this cycle.

    Args:
        control (dict):
            {"event": threading.Event, "action": "stop" | "continue" | None}.

        is_final_cycle (bool):
            The final cycle has no button, so a "continue" signal is never valid there.

    Returns:
        bool:
            True if a valid "continue" signal was consumed (event cleared, action reset); otherwise False, leaving control untouched.

    Notes:
        - Mutates control's action/event fields under _lock, same as _stop_draft_loop()/
          continue_draft_timer() (see module Notes above).
    """
    with _lock:
        if control["action"] == "continue" and not is_final_cycle:
            control["event"].clear()
            control["action"] = None
            return True
        else:
            return False

def _wait_full_duration(chat_id: int, control: dict, timeout: float, is_final_cycle: bool) -> str:
    """
    Waits out the full timeout, resuming for whatever's left after a valid continue press instead of cutting it short - only a stop signal (or an invalid continue, e.g. on the final cycle) ends the wait early.

    Args:
        chat_id (int)

        control (dict):
            {"event": threading.Event, "action": "stop" | "continue" | None}.

        timeout (float):
            Total seconds to wait out, preserved across any continue press received meanwhile.

        is_final_cycle (bool):
            Passed straight through to _consume_continue() - the final cycle has no button, so a "continue" signal is never valid there.

    Returns:
        str:
            "stop" if the wait ended early due to a stop signal (or an invalid continue).
            "extended" if the full timeout elapsed uninterrupted, but at least one valid continue press was consumed along the way.
            "expired" if the full timeout elapsed uninterrupted with no continue press at all.

    Notes:
        - A valid continue press sends its acknowledgement immediately, then re-waits for the remaining portion of timeout - it does not restart or extend timeout itself; whether this cycle is allowed to proceed to the next one is decided by the caller based on this return value.
        - A woken wait is classified by an explicit check against control["action"] - "continue" (if valid for this cycle), then "stop"; any other/unrecognised value is logged as a warning and defensively treated as "stop", rather than being inferred by elimination.
    """
    event = control["event"]
    deadline = time.monotonic() + timeout
    was_extended = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "extended" if was_extended else "expired"
        elif not event.wait(remaining):
            return "extended" if was_extended else "expired"
        elif control["action"] == "continue" and not is_final_cycle:
            _consume_continue(control, is_final_cycle)
            send_message(chat_id, _random_message(_ACCEPT_MESSAGES))
            logger.info(f"Draft keep-alive continue acknowledged for chat_id={chat_id} - current cycle's remaining wait is preserved, not shortened.")
            was_extended = True
        elif control["action"] == "stop":
            return "stop"
        else:
            logger.warning(f"Draft keep-alive for chat_id={chat_id} woke with unrecognised control state (action={control['action']!r}, is_final_cycle={is_final_cycle}). Treating as stop, defensively.")
            return "stop"

def _draft_loop(chat_id: int, media_type: str, control: dict) -> None:
    """
    Background loop keeping a pending draft alive through repeating keep-alive cycles, until stopped, expired, or the hard cap is reached.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file" - used to word the final close message.

        control (dict):
            {"event": threading.Event, "action": "stop" | "continue" | None} - shared with continue_draft_timer()/_stop_draft_loop().

    Returns:
        None

    Notes:
        - Each cycle: a silent wait, "typing...", then the notice (with a continue button, except on the final cycle) - then a further silent wait (no typing indicator) until the cycle ends.
        - A continue press during a non-final cycle is what allows the draft to reach its next scheduled cycle - an unanswered (never extended) non-final cycle closes the draft, same as an unanswered final cycle does.
        - A continue button press at any point up to the cycle's end sends an acknowledgement immediately, but does not shorten the cycle it was pressed in - that cycle's own remaining wait still plays out in full (see _wait_full_duration()) before the loop advances.
        - Uses control["event"].wait() throughout so an early stop cancels immediately.
    """
    event = control["event"]
    total_cycles = max(1, settings.DRAFT_CLOSE_SECONDS // settings.DRAFT_CYCLE_SECONDS)

    for cycle_index in range(total_cycles):
        is_final_cycle = cycle_index == total_cycles - 1

        # Silent wait before this cycle's typing indicator starts
        wait_before_notice_typing = max(0, settings.DRAFT_CYCLE_SECONDS - settings.DRAFT_CYCLE_NOTICE_LEAD_SECONDS - settings.DRAFT_TYPING_LEAD_SECONDS)
        if event.wait(wait_before_notice_typing):
            return

        # Start typing and hold it for DRAFT_TYPING_LEAD_SECONDS, immediately before the notice
        start_typing(_typing_key(chat_id), chat_id)
        if event.wait(settings.DRAFT_TYPING_LEAD_SECONDS):
            stop_typing(_typing_key(chat_id))
            return

        stop_typing(_typing_key(chat_id))

        # Send prompt for extension to user
        if is_final_cycle:
            send_message(chat_id, _random_message(_FINAL_NOTICE_MESSAGES))
        else:
            rows = _build_continue_button(chat_id)
            if rows:
                send_message_with_buttons(chat_id, _random_message(_CYCLE_NOTICE_MESSAGES), rows)
            else:
                send_message(chat_id, _random_message(_CYCLE_NOTICE_MESSAGES))
        logger.info(f"Sent draft keep-alive notice for chat_id={chat_id} (cycle {cycle_index + 1}/{total_cycles}, final={is_final_cycle}).")

        wait_result = _wait_full_duration(chat_id, control, settings.DRAFT_CYCLE_NOTICE_LEAD_SECONDS, is_final_cycle)

        if wait_result == "stop":
            return
        elif is_final_cycle:
            break
        elif wait_result == "extended":
            logger.info(f"Draft keep-alive extended for chat_id={chat_id} - moving on to cycle {cycle_index + 2}/{total_cycles}.")
        else:
            logger.info(f"Draft keep-alive for chat_id={chat_id} unanswered - closing without reaching cycle {cycle_index + 2}/{total_cycles}.")
            break

    logger.info(f"Draft for chat_id={chat_id} reached its hard close. Clearing.")
    _stop_draft_loop(chat_id)
    _send_close_message(chat_id, media_type)
    delete_chat_draft(chat_id)

def start_draft_timer(chat_id: int, media_type: str) -> None:
    """
    Starts the draft keep-alive timer for a chat, if one is not already running.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file" - used to word the final close message.

    Returns:
        None

    Notes:
        - No-op if already active for this chat_id (defensive guard, not the primary check).
    """
    with _lock:
        if chat_id in _active_drafts:
            return
        else:
            control = {"event": threading.Event(), "action": None}
            _active_drafts[chat_id] = control

    threading.Thread(
        target=_draft_loop,
        args=(chat_id, media_type, control),
        daemon=True
    ).start()
    logger.info(f"Started draft keep-alive timer for chat_id={chat_id} (media_type={media_type}).")

def stop_draft_timer(chat_id: int) -> None:
    """
    Stops the draft keep-alive timer for a chat, if active - also stops its typing indicator.

    Args:
        chat_id (int)

    Returns:
        None
    """
    stop_typing(_typing_key(chat_id))
    _stop_draft_loop(chat_id)

def close_orphaned_drafts() -> None:
    """
    Closes out any draft left in Redis with no matching in-memory keep-alive timer.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called once on startup, before polling begins.
          A draft's keep-alive loop is in-memory only (see module Notes above), so it does not survive an application restart - without this sweep, such a draft would sit silently until its Redis TTL lapses, with no notice or close message ever sent.
        - Since the loop's progress (cycle index, extensions used) isn't persisted, an orphaned draft is closed out immediately rather than resumed part-way through a cycle.
    """
    chat_ids = get_all_chat_draft_ids()
    if not chat_ids:
        return
    else:
        for chat_id in chat_ids:
            draft = get_chat_draft(chat_id)
            if draft is None:
                continue
            else:
                delete_chat_draft(chat_id)
                _send_close_message(chat_id, draft["media_type"])
                logger.info(f"Closed orphaned {draft['media_type']} draft for chat_id={chat_id} left behind by a previous run.")

# =============================================================================
