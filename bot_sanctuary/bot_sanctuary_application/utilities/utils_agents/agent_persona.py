# =============================================================================
# File        : agent_persona.py
# Description : Reusable persona/library-file loading, shared across every LLM provider's own interface module.
# Author      : SorinoSSK
# Created On  : 2026-09-18
#
# Features    :
#   - parse_agent(llm_type, call_name) - loads and parses a provider/Call's own libraries/<llm_type>/<call_name>.json file into an AgentPersona.
#   - load_persona_text(call_name) - reads a Call's shared, provider-agnostic persona/character text from libraries/persona/<call_name>.md.
#   - call_name_from_session_dir(session_dir) - derives which Call a session_dir belongs to, from its own already-established directory shape.
#
# Notes       :
#   - Deliberately provider-agnostic and call-site-agnostic - this module never decides *when* to resolve a
#     persona, only *how*. Each <provider>_interface.py's own querying function (query_via_api()/
#     query_via_oauth(), or the shared one-shot helper underneath) calls parse_agent() itself, locally, right
#     before it actually queries its LLM - never centralised in agent_interface.py::query_llm().
#   - See config.py for settings.LIBRARIES_DIR/PERSONA_DIR/BOT_NAME_PLACEHOLDER/PERSONA_PLACEHOLDER, and each
#     provider's own settings.LLM_TYPE_CLAUDE/CODEX/DEEPSEEK/QWEN constant.
#   - Moved here 2026-09-18 from claude_session_service.py's own private _parse_agent()/_load_persona_text(),
#     generalised (llm_type/call_name are now parameters, not hardcoded to Claude/"chat") so every provider's
#     own interface module can call the same functions instead of each maintaining its own copy.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import logging

from pathlib import Path

from ...config import AgentPersona, settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def call_name_from_session_dir(session_dir: "Path | None") -> "str | None":
    """
    Derives which Call a session_dir belongs to, from its own already-established directory shape.

    Args:
        session_dir (Path | None):
            A Call/LLM-scoped leaf directory, built as <session root>/<call_name>/<llm_type> by whichever
            <name>_call.py::handle() constructed it (e.g. chat_call.py's own call_session_dir). None if this
            call has no such directory at all.

    Returns:
        str | None:
            The derived call_name (session_dir's own parent directory name), or None if session_dir is None.

    Notes:
        - Purely a path read - never touches the filesystem, never raises.
        - Depends on every caller continuing to build its own session_dir as <root>/<call_name>/<llm_type> -
          not a new coupling, this shape is already how chat_call.py documents its own call_session_dir today.
    """
    return session_dir.parent.name if session_dir is not None else None

def load_persona_text(call_name: str) -> str:
    """
    Reads call_name's own shared, provider-agnostic persona/character text from libraries/persona/<call_name>.md.

    Args:
        call_name (str):
            Which Call's persona text to load - matches that Call's own CALL_NAME (e.g. "chat").

    Returns:
        str:
            The persona file's raw content, stripped. Empty string if the file is missing, unreadable, or blank.

    Notes:
        - Shared across every provider's own libraries/<llm_type>/<call_name>.json - referenced via
          settings.PERSONA_PLACEHOLDER rather than duplicated per provider, so the same character/instruction
          text only needs writing (and updating) once regardless of how many providers a Call is configured
          to run against.
        - Never raises - a missing/unreadable/empty file is treated the same as "no persona text supplied".
    """
    path = settings.PERSONA_DIR / f"{call_name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning(f"Persona file not found at {path} - {settings.PERSONA_PLACEHOLDER} will be substituted with an empty string.")
        return ""
    except OSError:
        logger.exception(f"Persona file at {path} could not be read - {settings.PERSONA_PLACEHOLDER} will be substituted with an empty string.")
        return ""

def parse_agent(llm_type: str, call_name: str) -> AgentPersona:
    """
    Loads and parses a provider/Call's own library file into an AgentPersona.

    Falls back to an empty-but-valid AgentPersona if the file is missing, unreadable, or malformed.

    Args:
        llm_type (str):
            Which provider's own library file to load - one of settings.KNOWN_LLM_TYPES.

        call_name (str):
            Which Call's definition to load - matches that Call's own CALL_NAME (e.g. "chat").

    Returns:
        AgentPersona:
            The parsed agent definition, with the PERSONA_PLACEHOLDER/BOT_NAME_PLACEHOLDER placeholders already substituted.

    Notes:
        - Re-reads the file fresh on every call, so a library file change takes effect on the very next call.
        - settings.PERSONA_PLACEHOLDER is substituted before settings.BOT_NAME_PLACEHOLDER, since
          libraries/persona/<call_name>.md's own content still contains {{BOT_NAME}} markers of its own -
          resolving them in this order lets one final replace() pass catch every occurrence, whichever file
          it came from.
        - Callers decide llm_type/call_name themselves, locally, at the point they actually need a reply -
          this function has no opinion on when it should be called.
        - An empty (0-byte/whitespace-only) library file is treated as "not yet written" rather than
          malformed - several of libraries/<llm_type>/<call_name>.json are deliberately empty placeholders
          today (e.g. every non-Chat Call's own file). Logged at info, not as an exception, since it's an
          expected state, not a failure - only genuinely unreadable/undecodable content logs as an exception.
        - Missing individual JSON fields (persona/tools/model) are tolerated silently, per-field - whatever
          is present is parsed and used; a field simply absent from an otherwise-valid file is not an error.
    """
    path = settings.LIBRARIES_DIR / llm_type / f"{call_name}.json"
    try:
        raw_text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.exception(f"Library file not found at {path} - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})
    except OSError:
        logger.exception(f"Library file at {path} could not be read - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})

    if not raw_text:
        logger.info(f"Library file at {path} is empty - not yet written for this Call/provider. Parsing whatever is available (nothing) - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.exception(f"Library file at {path} is not valid JSON - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})
    else:
        raw_body = data.get("persona", "")
        body = "\n".join(raw_body) if isinstance(raw_body, list) else str(raw_body)
        body = body.strip().replace(settings.PERSONA_PLACEHOLDER, load_persona_text(call_name))
        body = body.strip().replace(settings.BOT_NAME_PLACEHOLDER, settings.TELEGRAM_BOT_NAME)

        tools = data.get("tools") or None
        model = data.get("model") or None
        if not body:
            logger.info(f"Library file at {path} parsed successfully but has no \"persona\" text - using whatever else was available (tools={tools!r}, model={model!r}).")
        return AgentPersona(body=body, tools=tools, model=model, persona=data)

# =============================================================================
