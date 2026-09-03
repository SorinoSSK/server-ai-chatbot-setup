# =============================================================================
# File        : image_draft_handler.py
# Description : File responsible for warning about and closing a pending draft (media received without an instruction yet).
# Author      : SorinoSSK
# Created On  : 2026-08-31
#
# Features    :
#   - Runs a per-chat_id background loop keeping a pending draft alive through a fixed schedule of repeating "keep-alive" cycles (DRAFT_CLOSE_SECONDS worth, in DRAFT_CYCLE_SECONDS segments).
#     Each cycle shows "typing...", then sends a notice partway through asking the user to press a button if they need more time; then, if unanswered, shows "typing..." again immediately before the cycle ends - moving on to the next scheduled cycle regardless, unless this was the final one, in which case the draft closes.
#   - Pressing the button sends an acknowledgement and skips ahead to the next cycle immediately, instead of waiting out the rest of the current one; the final cycle's notice has no button instead, since it's the last one - if that goes unanswered too, the draft closes.
#   - close_orphaned_drafts() sweeps Redis on startup for drafts left behind by a keep-alive loop that did not survive the previous run (e.g. an app restart), closing each one out immediately rather than leaving it silently pending.
#
# Notes       :
#   - In-memory only - not persisted. Redis-side draft record has its own TTL as backstop.
#   - Per cycle (length DRAFT_CYCLE_SECONDS), two "typing..." windows, each DRAFT_TYPING_LEAD_SECONDS long, immediately precede the two messages a cycle can send:
#       - the notice, at DRAFT_CYCLE_SECONDS-DRAFT_CYCLE_NOTICE_LEAD_SECONDS into the cycle.
#       - the close message, at DRAFT_CYCLE_SECONDS into the cycle - only sent on the final cycle, if it ends with no response.
#   - A button press at any point up to the cycle's end (including during the second "typing..." window) skips ahead to the next cycle immediately.
#   - Total draft lifetime is capped at DRAFT_CLOSE_SECONDS, since the schedule of cycles is fixed regardless of button presses - the final cycle offers no button, since no further cycle remains to skip ahead to.
#
# =============================================================================
# I M P O R T   H E A D E R

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

def _stop(chat_id: int) -> None:
    """
    Removes chat_id from the active registry and signals its loop to stop, if present.

    Args:
        chat_id (int)

    Returns:
        None
    """
    with _lock:
        control = _active_drafts.pop(chat_id, None)

    if control is not None:
        control["action"] = "stop"
        control["event"].set()
        logger.info(f"Stopped draft keep-alive timer for chat_id={chat_id}.")

def continue_draft_timer(chat_id: int) -> bool:
    """
    Signals an active draft's loop to grant one more keep-alive cycle, in response to a button press.

    Args:
        chat_id (int)

    Returns:
        bool:
            True if a draft timer was active for chat_id and was signalled; otherwise False.
    """
    with _lock:
        control = _active_drafts.get(chat_id)

    if control is None:
        return False

    control["action"] = "continue"
    control["event"].set()
    logger.info(f"Extended draft keep-alive timer for chat_id={chat_id} by one more cycle.")
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
        - Shared by _draft_loop()'s own hard-close and close_orphaned_drafts(), so both
          close a draft out identically.
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
            True if a valid "continue" signal was consumed (event cleared, action reset);
            otherwise False, leaving control untouched.
    """
    if control["action"] == "continue" and not is_final_cycle:
        control["event"].clear()
        control["action"] = None
        return True

    return False

def _draft_loop(chat_id: int, media_type: str, control: dict) -> None:
    """
    Background loop keeping a pending draft alive through repeating keep-alive cycles, until stopped, expired, or the hard cap is reached.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file" - used to word the final close message.

        control (dict):
            {"event": threading.Event, "action": "stop" | "continue" | None} - shared with continue_draft_timer()/_stop().

    Returns:
        None

    Notes:
        - Each cycle has two "typing... -> message" beats: a silent wait, "typing...", then the notice (with a continue button, except on the final cycle); then another silent wait, "typing..." again, then - if still unanswered - the cycle ends.
        - An unanswered non-final cycle does not close the draft - it simply moves on to the next scheduled cycle, which sends its own notice in turn.
          Only an unanswered final cycle actually closes the draft.
        - A continue button press at any point up to the cycle's end sends an acknowledgement and immediately moves on to the next cycle, skipping the rest of the current cycle's wait - it does not carry over unused time.
        - Uses control["event"].wait() throughout so an early stop cancels immediately.
    """
    event = control["event"]
    total_cycles = max(1, settings.DRAFT_CLOSE_SECONDS // settings.DRAFT_CYCLE_SECONDS)

    for cycle_index in range(total_cycles):
        is_final_cycle = cycle_index == total_cycles - 1

        # Beat 1: silent wait, "typing...", then the notice.
        wait_before_notice_typing = max(0, settings.DRAFT_CYCLE_SECONDS - settings.DRAFT_CYCLE_NOTICE_LEAD_SECONDS - settings.DRAFT_TYPING_LEAD_SECONDS)
        if event.wait(wait_before_notice_typing):
            return

        start_typing(_typing_key(chat_id), chat_id)
        if event.wait(settings.DRAFT_TYPING_LEAD_SECONDS):
            stop_typing(_typing_key(chat_id))
            return

        stop_typing(_typing_key(chat_id))

        if is_final_cycle:
            send_message(chat_id, _random_message(_FINAL_NOTICE_MESSAGES))
        else:
            rows = _build_continue_button(chat_id)
            if rows:
                send_message_with_buttons(chat_id, _random_message(_CYCLE_NOTICE_MESSAGES), rows)
            else:
                send_message(chat_id, _random_message(_CYCLE_NOTICE_MESSAGES))
        logger.info(f"Sent draft keep-alive notice for chat_id={chat_id} (cycle {cycle_index + 1}/{total_cycles}, final={is_final_cycle}).")

        # Beat 2: silent wait, "typing...", then the cycle's close point.
        wait_before_close_typing = max(0, settings.DRAFT_CYCLE_NOTICE_LEAD_SECONDS - settings.DRAFT_TYPING_LEAD_SECONDS)
        if event.wait(wait_before_close_typing):
            if _consume_continue(control, is_final_cycle):
                send_message(chat_id, _random_message(_ACCEPT_MESSAGES))
                logger.info(f"Draft keep-alive for chat_id={chat_id} extended into cycle {cycle_index + 2}/{total_cycles}.")
                continue
            else:
                return

        start_typing(_typing_key(chat_id), chat_id)
        woken = event.wait(settings.DRAFT_TYPING_LEAD_SECONDS)
        stop_typing(_typing_key(chat_id))
        if woken:
            if _consume_continue(control, is_final_cycle):
                send_message(chat_id, _random_message(_ACCEPT_MESSAGES))
                logger.info(f"Draft keep-alive for chat_id={chat_id} extended into cycle {cycle_index + 2}/{total_cycles}.")
                continue
            else:
                return

        # No response before this cycle's end - the draft only actually expires if this
        # was the final cycle; otherwise, fall through to the next scheduled cycle,
        # which will send its own notice at its own 2 min mark.
        if is_final_cycle:
            break

        logger.info(f"Draft keep-alive for chat_id={chat_id} unanswered - moving on to cycle {cycle_index + 2}/{total_cycles}.")

    logger.info(f"Draft for chat_id={chat_id} reached its hard close. Clearing.")
    _stop(chat_id)
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
    _stop(chat_id)

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

    for chat_id in chat_ids:
        draft = get_chat_draft(chat_id)
        if draft is None:
            continue

        delete_chat_draft(chat_id)
        _send_close_message(chat_id, draft["media_type"])
        logger.info(f"Closed orphaned {draft['media_type']} draft for chat_id={chat_id} left behind by a previous run.")

# =============================================================================
