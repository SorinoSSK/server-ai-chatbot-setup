# =============================================================================
# File        : repository_pull.py
# Description : Detects a git repository reference in a message, and clones/pulls it into WORKSPACE_DIR.
# Author      : SorinoSSK
# Created On  : 2026-09-27
#
# Features    :
#   - extract_repository_reference() - the deterministic (non-LLM) classifier: requires an explicit trigger
#     word ("pull"/"clone"/"fetch") plus a URL token whose own domain is a declared settings.GIT_HOSTS entry,
#     before treating a message as a repository pull request at all - never on URL shape alone.
#   - execute_repository_pull() - clones (first time) or pulls (already present) a reference into WORKSPACE_DIR,
#     over whichever transport its own URL asked for, and publishes the outcome.
#
# Notes       :
#   - Called from session_worker.py::SessionWorker._process_batch(), ahead of the normal Call pipeline dispatch
#     - a recognised repository reference bypasses the LLM entirely; this is plain deterministic application
#     code, gated on the same coding_allowed flag as everything else in §5/§6 (CODE_TODO.md).
#   - A URL whose own domain isn't a declared settings.GIT_HOSTS entry at all is never classified as a
#     repository reference in the first place (see extract_repository_reference()'s own Notes) - it falls
#     through to the normal chat pipeline like any other message, e.g. a link the user wants discussed/analysed
#     rather than pulled. Only a domain that *is* declared but has no usable SSH identity (a genuine
#     configuration problem), when its URL asked for SSH, is rejected explicitly via an "error" tool message.
#   - The transport follows the URL the user sent, exactly as a plain `git clone <url>` would:
#       ssh://git@<domain>[:<port>]/<owner>/<repo>   SSH, on <port> if given - the URL is the only place a
#                                                     non-standard SSH port ever comes from (never GIT_HOSTS or
#                                                     ssh_config), passed on as ssh's own -p by git.
#       git@<domain>:<owner>/<repo>                   SSH, standard port 22 - scp-like syntax cannot carry a
#                                                     port, same as git itself.
#       https://<domain>[:<port>]/<owner>/<repo>     HTTPS - no SSH identity involved at all.
#       http://<domain>[:<port>]/<owner>/<repo>      Recognised, but rejected with an explicit message - plain
#                                                     HTTP is unencrypted, so it is never passed to git.
#   - HTTPS clones carry no credentials - GitHub and Gitea deploy keys only work over SSH. A public
#     repository clones fine; a private one fails fast (GIT_TERMINAL_PROMPT=0, never hangs on a prompt) with a
#     hint to send its SSH URL instead.
#   - A repository already present under WORKSPACE_DIR is not touched at all unless the message said "pull" or
#     "fetch" - a "clone"-only request just gets an "already available" reply (see execute_repository_pull()).
#     When an update is requested, its origin is re-pointed at the URL sent this time
#     (git remote set-url) before every pull, so the URL decides the transport each time, not only on first
#     clone. This matters because the SSH alias baked into origin at clone time is a generated uuid
#     (git_hosts.py) - if that uuid is ever regenerated, a stale origin would no longer resolve.
#   - The destination directory is always WORKSPACE_DIR/<domain>/<repo name>. domain is guaranteed to be one of
#     settings.GIT_HOSTS' own entries by the time it reaches here (never raw user input, see
#     extract_repository_reference()), but the repo name component is parsed from user-supplied text, so it is
#     sanitised (see _sanitize_path_component()) and the final resolved path is re-checked against WORKSPACE_DIR
#     before any filesystem operation - defence in depth against a crafted reference escaping it.
#   - The clone URL handed to git is rebuilt from the parsed parts (see _build_remote_url()), never the raw
#     user-supplied token itself.
#   - GIT_SSH_COMMAND is set explicitly per subprocess call (-F <GIT_SSH_DIR>/ssh_config), rather than relying on
#     any default ~/.ssh lookup - keeps this application's own git filesystem/credential access confined to
#     GIT_SSH_DIR/WORKSPACE_DIR, the same "one directory only" constraint as everywhere else in §6.
#   - Host key verification uses UserKnownHostsFile=<GIT_SSH_DIR>/known_hosts with
#     StrictHostKeyChecking=accept-new - trust-on-first-use, recorded into a file this application itself
#     manages within GIT_SSH_DIR. This is a second, narrow exception to "this application only ever reads
#     GIT_SSH_DIR" (the first being git_hosts.py::sync_git_hosts() itself) - ssh, not this module's own Python
#     code, is what appends to known_hosts.
#   - Requires the `git` and `ssh` binaries in the image - see Dockerfile.dev/Dockerfile.prod's own apt-get line
#     (openssh-client already added for git_hosts.py's own key generation; git added alongside it for this).
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import re
import logging
import subprocess

from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...config import settings
from . import git_hosts
from ..utils_agents import agent_tools
from ..utils_redis.database import mark_task_complete

if TYPE_CHECKING:
    from ..utils_queue.queue import RabbitMQPublisher

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# http(s)://<domain>[:<port>]/<owner>/<repo>[.git][/]
_HTTP_URL_PATTERN = re.compile(r"^(?P<scheme>https?)://(?P<domain>[A-Za-z0-9.-]+)(?::(?P<port>\d+))?/(?P<path>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")
# ssh://git@<domain>[:<port>]/<owner>/<repo>[.git][/]
_SSH_URL_PATTERN = re.compile(r"^ssh://git@(?P<domain>[A-Za-z0-9.-]+)(?::(?P<port>\d+))?/(?P<path>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")
# git@<domain>:<owner>/<repo>[.git] - scp-like syntax, which cannot carry a port
_SCP_URL_PATTERN = re.compile(r"^git@(?P<domain>[A-Za-z0-9.-]+):(?P<path>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")

_SAFE_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Pulls the trailing "<owner>/<repo>" out of any of the origin URL shapes this module itself ever writes
# (scp-like alias, ssh://alias:port/..., or http(s)://...) - see _existing_origin_path().
_ORIGIN_OWNER_REPO_PATTERN = re.compile(r"([\w.-]+/[\w.-]+?)(?:\.git)?/?$")

# Requires one of these words to appear anywhere in the message before a URL-shaped token is even looked at -
# see extract_repository_reference()'s own Notes on why matching URL shape alone is not enough.
_PULL_TRIGGER_PATTERN = re.compile(r"\b(?:pull|clone|fetch)\b", re.IGNORECASE)

# The subset of trigger words that explicitly ask for an existing checkout to be updated - a message with only
# "clone" in it, for a repository already cloned, is answered with an "already available" reply instead.
_UPDATE_TRIGGER_PATTERN = re.compile(r"\b(?:pull|fetch)\b", re.IGNORECASE)

_GIT_SUBPROCESS_TIMEOUT_SECONDS = 120

# =============================================================================

@dataclass
class RepositoryReference:
    """
    One git repository reference recognised in a message, classified against settings.GIT_HOSTS.

    Attributes:
        raw_url (str):
            The exact URL token found in the message.

        scheme (str):
            The transport the URL asked for - "ssh", "http", or "https".

        domain (str):
            The parsed domain (lower-cased), e.g. "gitea.example.com" - always one of settings.GIT_HOSTS' own
            declared entries by construction (see extract_repository_reference()), never arbitrary user input.

        port (int | None):
            The port written in the URL itself, if any - an SSH port for scheme "ssh", an HTTP(S) port
            otherwise. None means the transport's own standard port.

        repo_path (str):
            The parsed "<owner>/<repo>" path, with any trailing ".git" already stripped.

        git_host (git_hosts.GitHost | None):
            The matching resolved host (its generated SSH aliases), if domain is a settings.GIT_HOSTS entry;
            only actually needed when scheme is "ssh".

        update_requested (bool):
            Whether the message asked for an update ("pull"/"fetch"), not just a "clone" - only matters when
            the repository is already cloned (see execute_repository_pull()).
    """
    raw_url: str
    scheme: str
    domain: str
    port: "int | None"
    repo_path: str
    git_host: "git_hosts.GitHost | None"
    update_requested: bool

def extract_repository_reference(text: str) -> "RepositoryReference | None":
    """
    Finds the first git-repository-shaped URL token in text, and resolves its domain against settings.GIT_HOSTS.

    Args:
        text (str):
            A turn's own combined message text.

    Returns:
        RepositoryReference | None:
            The first recognised reference; None if this message isn't a repository pull request at all - in
            which case the normal Call pipeline should handle it instead (e.g. an ordinary chat message that
            happens to contain a URL, for the LLM to discuss/analyse rather than pull).

    Notes:
        - Deterministic - plain regex/keyword matching against text and its own whitespace-split tokens, no LLM
          involved.
        - Two separate gates must both pass before this is treated as a pull request at all, not URL shape
          alone - a URL that merely looks like a repository link (e.g. any ordinary https://<domain>/<a>/<b>
          page, git hosting or not) must never silently hijack a normal chat turn:
            1. text must contain one of _PULL_TRIGGER_PATTERN's own trigger words ("pull"/"clone"/"fetch")
               somewhere - checked first, cheaply, before any URL parsing is attempted at all.
            2. the URL's own domain (case-insensitively) must already be one of settings.GIT_HOSTS' own
               declared domains, per git_hosts.declared_domains() - checked before git_hosts.resolve_git_hosts()
               is ever called, so a URL for an entirely unrelated/unconfigured domain is left alone (falls
               through to chat) rather than being treated as a failed pull attempt.
        - Only the first matching token whose domain is a declared GIT_HOSTS entry is used - a message with
          several URLs skips any that don't match one, rather than only ever checking the first token overall.
        - The URL's own scheme and port are kept on the returned reference (see this module's own header Notes
          on how they decide the transport) - never discarded and re-derived from config.
        - git_hosts.declared_domains() and git_hosts.resolve_git_hosts() both derive their own domain casing
          from the same lower-casing, so the two stay consistent with each other regardless of whatever casing
          settings.GIT_HOSTS itself was written in.
    """
    if not _PULL_TRIGGER_PATTERN.search(text):
        return None

    declared_domain_set = git_hosts.declared_domains()

    for token in text.split():
        match = _HTTP_URL_PATTERN.match(token) or _SSH_URL_PATTERN.match(token) or _SCP_URL_PATTERN.match(token)
        if match is None:
            continue
        else:
            groups = match.groupdict()
            domain = groups["domain"].lower()
            if domain not in declared_domain_set:
                continue
            else:
                port_text = groups.get("port")
                resolved_hosts = git_hosts.resolve_git_hosts()
                return RepositoryReference(
                    raw_url=token,
                    scheme=groups.get("scheme") or "ssh",
                    domain=domain,
                    port=int(port_text) if port_text else None,
                    repo_path=groups["path"],
                    git_host=resolved_hosts.get(domain),
                    update_requested=bool(_UPDATE_TRIGGER_PATTERN.search(text))
                )

    return None

def _sanitize_path_component(value: str) -> "str | None":
    """
    Restricts value to a safe single filesystem path component - no separators, no "..".

    Args:
        value (str)

    Returns:
        str | None:
            value, unchanged, if it is a single safe component; otherwise None.
    """
    if value in ("", ".", "..") or not _SAFE_PATH_COMPONENT_PATTERN.match(value):
        return None
    else:
        return value

def _resolve_destination(reference: RepositoryReference) -> "Path | None":
    """
    Builds and confines this reference's own destination directory under WORKSPACE_DIR.

    Args:
        reference (RepositoryReference)

    Returns:
        Path | None:
            WORKSPACE_DIR/<domain>/<repo name>, resolved and confirmed to be a genuine descendant of
            WORKSPACE_DIR; None if the repo name isn't a safe single path component, or the resolved path
            unexpectedly escapes WORKSPACE_DIR.

    Notes:
        - domain is never user-controlled by the time this runs - it is always one of settings.GIT_HOSTS' own
          entries (see extract_repository_reference()). Only the repo name (parsed from reference.repo_path,
          itself derived from user-supplied text) needs sanitising.
    """
    repo_name = _sanitize_path_component(reference.repo_path.rsplit("/", 1)[-1])
    if repo_name is None:
        logger.warning(f"Rejected repository reference with an unsafe repo name (raw_url={reference.raw_url!r}).")
        return None
    else:
        workspace_root = settings.WORKSPACE_DIR.resolve()
        destination = (workspace_root / reference.domain / repo_name).resolve()
        if not destination.is_relative_to(workspace_root):
            logger.error(f"Resolved destination {destination} for raw_url={reference.raw_url!r} escapes WORKSPACE_DIR - refusing to touch it.")
            return None
        else:
            return destination

def _git_env() -> dict:
    """
    Builds the subprocess environment for a git pull/clone, pinning ssh to GIT_SSH_DIR's own config/known_hosts.

    Args:
        None

    Returns:
        dict:
            A copy of this process' own environment, with GIT_SSH_COMMAND overridden and terminal prompts
            disabled.

    Notes:
        - See this module's own header Notes on why UserKnownHostsFile/StrictHostKeyChecking=accept-new is the
          accepted trust-on-first-use approach here.
        - GIT_TERMINAL_PROMPT=0 makes an HTTP(S) clone that needs credentials fail immediately, instead of
          waiting on a username/password prompt nothing can answer.
        - GIT_SSH_COMMAND is inert for an HTTP(S) clone, so it is set unconditionally.
    """
    ssh_config_path = settings.GIT_SSH_DIR / "ssh_config"
    known_hosts_path = settings.GIT_SSH_DIR / "known_hosts"
    ssh_command = f"ssh -F {ssh_config_path} -o UserKnownHostsFile={known_hosts_path} -o StrictHostKeyChecking=accept-new"
    return {**os.environ, "GIT_SSH_COMMAND": ssh_command, "GIT_TERMINAL_PROMPT": "0"}

def _existing_origin_path(destination: Path) -> "str | None":
    """
    Reads which "<owner>/<repo>" an existing checkout's own origin actually points at.

    Args:
        destination (Path):
            An existing checkout under WORKSPACE_DIR (already confirmed to contain a .git directory).

    Returns:
        str | None:
            The lower-cased trailing "<owner>/<repo>" of its origin URL; None if git can't report one (no
            origin remote, an unparsable URL, or the git call itself failing).

    Notes:
        - Backs the name-collision guard in execute_repository_pull() - the destination is keyed only by
          domain and repo name, so two owners' identically named repositories on one host would otherwise
          silently share (and be pulled into) the same directory.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(destination), "config", "--get", "remote.origin.url"],
            env=_git_env(), capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if completed.returncode != 0:
        return None
    else:
        match = _ORIGIN_OWNER_REPO_PATTERN.search(completed.stdout.strip())
        return match.group(1).lower() if match else None

def _build_remote_url(reference: RepositoryReference) -> str:
    """
    Rebuilds the clone URL handed to git, from reference's own parsed parts.

    Args:
        reference (RepositoryReference):
            For scheme "ssh", already confirmed to have a resolved reference.git_host.pull_alias.

    Returns:
        str:
            For SSH, the domain's generated pull alias stands in for the host, so ssh_config supplies its
            identity - "ssh://<alias>:<port>/<path>.git" if the URL carried a port, otherwise the scp-like
            "<alias>:<path>.git". For HTTP(S), "<scheme>://<domain>[:<port>]/<path>.git".

    Notes:
        - Never the raw user-supplied token - see this module's own header Notes.
    """
    if reference.scheme == "ssh":
        alias = reference.git_host.pull_alias
        if reference.port is not None:
            return f"ssh://{alias}:{reference.port}/{reference.repo_path}.git"
        else:
            return f"{alias}:{reference.repo_path}.git"
    else:
        port_suffix = f":{reference.port}" if reference.port is not None else ""
        return f"{reference.scheme}://{reference.domain}{port_suffix}/{reference.repo_path}.git"

def _run_git_pull_or_clone(reference: RepositoryReference, destination: Path) -> "tuple[bool, str]":
    """
    Clones reference into destination if it doesn't exist yet, otherwise pulls it (fast-forward only).

    Args:
        reference (RepositoryReference):
            For scheme "ssh", already confirmed to have a resolved reference.git_host.pull_alias.

        destination (Path):
            Already confirmed confined to WORKSPACE_DIR (see _resolve_destination()).

    Returns:
        tuple[bool, str]:
            (True, action) on success, where action is "cloned" or "pulled"; (False, error text) otherwise.
    """
    env = _git_env()
    remote_url = _build_remote_url(reference)

    if (destination / ".git").is_dir():
        action = "pulled"
        commands = [
            ["git", "-C", str(destination), "remote", "set-url", "origin", remote_url],
            ["git", "-C", str(destination), "pull", "--ff-only"]
        ]
    else:
        action = "cloned"
        commands = [["git", "clone", remote_url, str(destination)]]
        destination.parent.mkdir(parents=True, exist_ok=True)

    for command in commands:
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=_GIT_SUBPROCESS_TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"git {action} failed to run: {exc}"

        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"git exited with status {completed.returncode}."
            if reference.scheme != "ssh":
                detail += "\n(HTTP(S) clones send no credentials - a private repository needs its SSH URL instead.)"
            return False, detail

    return True, action

def execute_repository_pull(publisher: "RabbitMQPublisher", session_id: str, task_id: str, reference: RepositoryReference) -> None:
    """
    Clones/pulls reference into WORKSPACE_DIR, then publishes the outcome and closes task_id.

    Bypasses the LLM Call pipeline entirely - this is plain deterministic application code end to end.

    Args:
        publisher (RabbitMQPublisher):
            The calling SessionWorker's own publisher - never shared across threads.

        session_id (str)

        task_id (str):
            The still-open task_id this turn's reply/error/completed must be published against.

        reference (RepositoryReference):
            The classified reference to act on (see extract_repository_reference()).

    Returns:
        None

    Notes:
        - A plain http:// reference is rejected first of all, before any destination is even resolved or any git
          call made, with a "repository_insecure_scheme" error - it was still classified as a pull request (see
          extract_repository_reference()) precisely so it gets this explicit message rather than silently
          falling through to chat. Only https:// and the two SSH forms ever reach git.
        - Name-collision guard, checked first once a destination exists: the destination is keyed only by
          domain and repo name, so if an existing checkout's own origin points at a different "<owner>/<repo>"
          (e.g. alice/api already there, bob/api requested), the request is refused with an explicit error
          rather than pulling into, or reporting as available, the wrong repository. Deliberately not solved
          by adding owner to the directory layout - coding access is single-user (§6), so this is expected to
          be rare, and a guard is enough.
        - A repository already cloned under WORKSPACE_DIR is answered with a plain "already available" reply,
          with no git/network call at all, unless the message explicitly asked for an update ("pull"/"fetch",
          see RepositoryReference.update_requested). Checked before the SSH identity check below, since
          nothing needs an identity just to report an existing checkout.
        - An SSH reference with no resolved git_host pull alias (a domain whose deploy key generation failed),
          or any reference with an unsafe/escaping destination, is rejected with an explicit "error" tool
          message - never silently ignored. An HTTP(S) reference needs no SSH identity, so is not held back by
          a missing alias.
        - Mirrors call_dispatch_handler.py::execute_dispatch_call()'s own close-out shape/logging conventions.
    """
    insecure = reference.scheme == "http"
    destination = None if insecure else _resolve_destination(reference)
    already_cloned = destination is not None and (destination / ".git").is_dir()
    existing_path = _existing_origin_path(destination) if already_cloned else None

    if insecure:
        message = {
            "type": "error",
            "error_type": "repository_insecure_scheme",
            "message": "Plain http:// URLs are not supported - resend it as an https:// URL, or send its SSH URL instead."
        }
    elif destination is None:
        message = {
            "type": "error",
            "error_type": "repository_reference_invalid",
            "message": "That repository reference could not be resolved to a safe destination."
        }
    elif existing_path is not None and existing_path != reference.repo_path.lower():
        message = {
            "type": "error",
            "error_type": "repository_name_conflict",
            "message": f"`{reference.domain}/{existing_path}` already occupies that workspace name, so `{reference.domain}/{reference.repo_path}` was not cloned or pulled. Remove or rename the existing checkout first."
        }
    elif already_cloned and not reference.update_requested:
        message = {
            "type": "text",
            "text": f"`{reference.domain}/{reference.repo_path}` is already cloned and available in the workspace. Say \"pull\" if you want it updated."
        }
    elif reference.scheme == "ssh" and (reference.git_host is None or reference.git_host.pull_alias is None):
        message = {
            "type": "error",
            "error_type": "repository_host_unresolved",
            "message": f"{reference.domain!r} has no SSH deploy key set up yet, so its SSH URL cannot be pulled."
        }
    else:
        success, detail = _run_git_pull_or_clone(reference, destination)
        if success:
            message = {"type": "text", "text": f"{detail.capitalize()} `{reference.domain}/{reference.repo_path}`."}
        else:
            logger.error(f"session_id={session_id}: git pull/clone failed for raw_url={reference.raw_url!r} - {detail}")
            message = {
                "type": "error",
                "error_type": "repository_pull_failed",
                "message": f"Failed to pull that repository: {detail}"
            }

    tool_error = agent_tools.execute_tool(publisher, task_id, session_id, message)
    if tool_error is not None:
        logger.error(f"session_id={session_id}: failed to publish repository pull outcome for task_id={task_id} - {tool_error}")
    else:
        completed_error = agent_tools.execute_completed(publisher, task_id, session_id)
        if completed_error is not None:
            logger.error(f"session_id={session_id}: repository pull outcome published for task_id={task_id}, but failed to close it out with completed - {completed_error}. task_id remains open until a future session reset.")
        else:
            mark_task_complete(task_id)
            logger.info(f"session_id={session_id}: closed task_id={task_id} after a repository pull attempt (raw_url={reference.raw_url!r}).")

# =============================================================================
