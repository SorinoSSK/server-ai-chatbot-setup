# =============================================================================
# File        : git_hosts.py
# Description : Generates/syncs, then resolves, GIT_SSH_DIR's own ssh_config against settings.GIT_HOSTS.
# Author      : SorinoSSK
# Created On  : 2026-09-24
#
# Features    :
#   - sync_git_hosts() - startup step; generates a deploy keypair and a "<uuid>-pull"/"<uuid>-push" ssh_config
#     Host block pair for any settings.GIT_HOSTS domain not yet known, drops the Host blocks (not the key
#     files) for any previously-known domain no longer declared, and otherwise leaves everything untouched.
#   - resolve_git_hosts() - startup diagnostic; parses the (now up to date) ssh_config, logs each
#     settings.GIT_HOSTS domain's own resolution, and returns an in-memory {domain: GitHost} mapping for later
#     phases (the URL classifier, the pull/push handler) to consume.
#   - declared_domains() - the shared, normalised (lower-cased) set of settings.GIT_HOSTS' own domains - used by
#     repository_pull.py's own classifier, not settings.GIT_HOSTS directly.
#
# Notes       :
#   - settings.GIT_HOSTS is a comma-separated list of plain domains (e.g. "gitea.example.com,github.com") - no
#     scheme, no port, not short labels - see config.py's own GIT_HOSTS Notes.
#   - No port is ever configured here or written into ssh_config. A non-standard SSH port comes from the clone
#     URL a user actually sends (ssh://git@<domain>:<port>/<owner>/<repo>), applied per git call by
#     repository_pull.py - ssh's own -p, which git passes for such a URL, overrides any ssh_config Port anyway.
#   - Both sync/resolve functions here are plain deterministic application code, called once from initialise.py
#     at startup - never reachable from the LLM-facing Call pipeline/agent tool surface (chat_call.py and friends
#     never import this module). That separation, not a "the bot's own process never runs this code" rule, is
#     what keeps the "bots must not have access to credentials" constraint intact (see CODE_TODO.md §6) while
#     still letting generation happen automatically, in-app, without a separate hand-run script.
#   - Key generation shells out to the system `ssh-keygen` binary (openssh-client, installed via Dockerfile.dev/
#     Dockerfile.prod) rather than adding a Python crypto dependency - the same binary an admin would reach for
#     manually to inspect/regenerate a key by hand, and one this application also needs installed for its own
#     git pull/clone subprocess calls (see repository_pull.py).
#   - settings.GIT_SSH_DIR (bot_sanctuary_application/data/git_ssh) is created if missing (see main.py).
#     sync_git_hosts() writes into it (ssh_config, git_hosts_manifest.tsv, and each generated keypair);
#     resolve_git_hosts() only ever reads from it. repository_pull.py's own known_hosts file (via ssh itself,
#     trust-on-first-use, not this module) is the one other thing ever written into this directory - see that
#     module's own header Notes.
#   - git_hosts_manifest.tsv (domain<TAB>uuid, one per line) is this module's own persisted record of which
#     domain a given generated uuid belongs to - the alias itself is opaque, so without this record a restart
#     could not tell "already generated" domains apart from "newly added" ones. Any further columns (an
#     earlier revision briefly wrote a port column) are ignored on read.
#   - Removing a domain from settings.GIT_HOSTS drops its Host blocks and manifest line, but deliberately leaves
#     its key files on disk - deleting key material automatically is not this application's call to make; an
#     admin who wants it gone removes the files themselves.
#   - Hand-written ssh_config parser, not a library - no SSH-config-parsing dependency exists in requirements.txt,
#     and this project's own convention (see deepseek_interface.py/qwen_interface.py) is to prefer stdlib over
#     adding a dependency for a small, self-contained need. Deliberately minimal: only understands "Host
#     <alias...>" blocks and their own directive lines - not a full ssh_config implementation (no Match/Include/
#     wildcard support).
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import subprocess
import uuid as uuid_module

from pathlib import Path
from dataclasses import dataclass

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_SSH_CONFIG_FILENAME = "ssh_config"
_MANIFEST_FILENAME = "git_hosts_manifest.tsv"

# =============================================================================

@dataclass
class GitHost:
    """
    One settings.GIT_HOSTS domain's own resolved SSH setup, once cross-referenced against ssh_config.

    Attributes:
        domain (str):
            The declared settings.GIT_HOSTS domain (e.g. "gitea.example.com").

        pull_alias (str | None):
            The generated "<uuid>-pull" SSH Host alias to use for pulling, or None if unusable - in which case
            push_alias is also None.

        push_alias (str | None):
            The generated "<uuid>-push" SSH Host alias to use for pushing, or None if no matching block was
            found (push simply unavailable for this domain - pull-only).
    """
    domain: str
    pull_alias: "str | None"
    push_alias: "str | None"

def declared_domains() -> "set[str]":
    """
    Returns settings.GIT_HOSTS' own declared domains, lower-cased.

    Args:
        None

    Returns:
        set[str]:
            Every domain declared in settings.GIT_HOSTS, lower-cased, with any stray ":<port>" suffix dropped.

    Notes:
        - The single shared source other modules (e.g. repository_pull.py) should use to check whether a
          parsed URL's own domain is a declared git host - never settings.GIT_HOSTS directly, so casing is
          handled in one place.
        - A stray ":<port>" suffix is dropped silently here (this runs on every classified message) - it is
          only warned about once, at startup, by sync_git_hosts().
    """
    domains = {entry.partition(":")[0].strip().lower() for entry in settings.GIT_HOSTS}
    domains.discard("")
    return domains

def _read_manifest(path: Path) -> "dict[str, str]":
    """
    Reads git_hosts_manifest.tsv into a domain -> uuid mapping.

    Args:
        path (Path):
            Path to the manifest file.

    Returns:
        dict[str, str]:
            Each known domain mapped to its own previously-generated uuid. Empty if the file doesn't exist yet
            or is empty.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception(f"Failed to read {path} - treating it as if no git hosts were previously synced.")
        return {}

    domain_to_uuid: "dict[str, str]" = {}
    for line in raw_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        else:
            domain, entry_uuid = parts[0].strip(), parts[1].strip()
            if domain and entry_uuid:
                domain_to_uuid[domain] = entry_uuid

    return domain_to_uuid

def _write_manifest(path: Path, domain_to_uuid: "dict[str, str]") -> None:
    """
    Writes a domain -> uuid mapping out to git_hosts_manifest.tsv.

    Args:
        path (Path):
            Path to the manifest file.

        domain_to_uuid (dict[str, str]):
            Each domain to persist, mapped to its own uuid.

    Returns:
        None
    """
    lines = [f"{domain}\t{entry_uuid}" for domain, entry_uuid in domain_to_uuid.items()]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

def _write_ssh_config(path: Path, domain_to_uuid: "dict[str, str]") -> None:
    """
    Regenerates ssh_config from scratch, writing a <uuid>-pull/<uuid>-push Host block pair per domain.

    Args:
        path (Path):
            Path to the ssh_config file to (re)write.

        domain_to_uuid (dict[str, str]):
            Every domain that should have a Host block pair, mapped to its own uuid.

    Returns:
        None

    Notes:
        - No Port directive is written - see this module's own header Notes on where a port comes from instead.
    """
    blocks = []
    for domain, entry_uuid in domain_to_uuid.items():
        key_path = settings.GIT_SSH_DIR / f"{entry_uuid}_deploy_key"
        for suffix in ("pull", "push"):
            blocks.append(
                f"Host {entry_uuid}-{suffix}\n"
                f"    HostName {domain}\n"
                f"    User git\n"
                f"    IdentityFile {key_path}\n"
                f"    IdentitiesOnly yes\n"
            )
    path.write_text("\n".join(blocks), encoding="utf-8")

def _generate_deploy_keypair(domain: str, entry_uuid: str) -> bool:
    """
    Generates one passphrase-less ed25519 deploy keypair for a newly-added domain, via the system ssh-keygen.

    Args:
        domain (str):
            The domain this keypair is being generated for - used only for the key's own comment field.

        entry_uuid (str):
            This domain's generated uuid - the keypair is written as "<uuid>_deploy_key"/"<uuid>_deploy_key.pub".

    Returns:
        bool:
            True if key generation succeeded; False otherwise (logged, never raised).
    """
    key_path = settings.GIT_SSH_DIR / f"{entry_uuid}_deploy_key"
    try:
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", f"bot_sanctuary:{domain}", "-q"],
            check=True,
            timeout=30
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        logger.exception(f"Failed to generate a deploy keypair for git host domain {domain!r} - it will be left unresolvable until this is retried on the next startup.")
        return False

def sync_git_hosts() -> None:
    """
    Generates/removes ssh_config Host blocks and their keypairs so GIT_SSH_DIR matches settings.GIT_HOSTS.

    Args:
        None

    Returns:
        None

    Notes:
        - A no-op, without rewriting either file, when settings.GIT_HOSTS hasn't gained or lost a domain since
          the last run.
        - Safe to call with an empty settings.GIT_HOSTS - nothing is generated, any previously-generated Host
          blocks are dropped from ssh_config (their key files are left on disk regardless).
        - Logs each newly-generated domain's own public key, with an instruction to add it as a deploy key on
          that domain's own repository/organisation settings page - this is the one piece of output an admin is
          still expected to act on by hand.
        - Warns once, here, about any GIT_HOSTS entry carrying a ":<port>" suffix - only its domain part is used.
        - A domain whose key generation fails is left out of the result and named in a single summary warning;
          it is retried on the next startup, since it is still absent from the manifest.
        - Only writes when the outcome actually differs from what was read - if every attempted change failed
          (e.g. ssh-keygen missing from the image), both files are left exactly as they were rather than being
          rewritten with an unchanged or empty result. A partial success still writes the domains that worked,
          and a genuine removal down to an empty set still writes an empty ssh_config, since that is the outcome.
    """
    for entry in settings.GIT_HOSTS:
        if ":" in entry:
            logger.warning(f"GIT_HOSTS entry {entry!r} carries a ':' - only the domain part is used. An SSH port is read from the clone URL itself at pull time, never from GIT_HOSTS.")

    manifest_path = settings.GIT_SSH_DIR / _MANIFEST_FILENAME
    ssh_config_path = settings.GIT_SSH_DIR / _SSH_CONFIG_FILENAME

    existing_domain_to_uuid = _read_manifest(manifest_path)
    desired_domains = declared_domains()
    existing_domains = set(existing_domain_to_uuid)

    added_domains = desired_domains - existing_domains
    removed_domains = existing_domains - desired_domains

    if not added_domains and not removed_domains:
        logger.info("GIT_HOSTS is unchanged since the last sync - ssh_config left untouched.")
        return
    else:
        updated_domain_to_uuid = dict(existing_domain_to_uuid)

        for domain in removed_domains:
            logger.info(f"git host domain {domain!r} is no longer in GIT_HOSTS - removing its Host block from ssh_config (its key files under {settings.GIT_SSH_DIR} are left in place - remove manually if no longer needed).")
            del updated_domain_to_uuid[domain]

        for domain in added_domains:
            entry_uuid = str(uuid_module.uuid4())
            logger.info(f"New git host domain detected: {domain!r} - generating a deploy keypair (uuid={entry_uuid})...")
            if not _generate_deploy_keypair(domain, entry_uuid):
                continue
            else:
                updated_domain_to_uuid[domain] = entry_uuid
                public_key_path = settings.GIT_SSH_DIR / f"{entry_uuid}_deploy_key.pub"
                try:
                    public_key = public_key_path.read_text(encoding="utf-8").strip()
                    logger.info(f"Add the following deploy key (read+write) to {domain!r}'s repository/organisation settings:\n{public_key}")
                except OSError:
                    logger.exception(f"Generated a deploy keypair for {domain!r} but could not read its public half back from {public_key_path} - check it manually.")

        failed_domains = sorted(domain for domain in added_domains if domain not in updated_domain_to_uuid)
        if failed_domains:
            logger.warning(f"Key generation failed for {len(failed_domains)} of {len(added_domains)} new git host domain(s) ({', '.join(failed_domains)}) - see the errors above. They are unresolvable until the next startup retries them.")

        if updated_domain_to_uuid == existing_domain_to_uuid:
            logger.warning("No git host change could be applied - ssh_config and git_hosts_manifest.tsv were left untouched, not rewritten with an unchanged or empty result.")
            return
        else:
            _write_manifest(manifest_path, updated_domain_to_uuid)
            _write_ssh_config(ssh_config_path, updated_domain_to_uuid)
            logger.info(f"ssh_config regenerated ({len(updated_domain_to_uuid)} host domain(s)).")

def _parse_ssh_config(path: Path) -> "dict[str, dict[str, str]]":
    """
    Parses an OpenSSH client config file into a mapping of each Host alias to its own directives.

    Args:
        path (Path):
            Path to the ssh_config file to parse.

    Returns:
        dict[str, dict[str, str]]:
            Each Host alias (e.g. a generated "<uuid>-pull") mapped to its own directives (lower-cased keyword
            -> raw value, e.g. {"hostname": "git.example.com", "identityfile": "..."}). Empty if the file
            doesn't exist or declares no Host blocks.

    Notes:
        - A "Host a b" line sharing multiple aliases is supported - each alias gets its own dict, but all point
          at the directives that follow, matching real ssh_config block semantics.
        - Directive keywords are matched case-insensitively and stored lower-cased; values are left as-is.
        - Comment lines (leading "#") and blank lines are skipped; a malformed directive line (no value) is
          skipped rather than raising.
    """
    aliases: "dict[str, dict[str, str]]" = {}
    current_directives_list: "list[dict[str, str]]" = []

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception(f"Failed to read {path} - treating it as if it declared no git hosts.")
        return {}

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        else:
            parts = stripped.split(None, 1)
            if len(parts) != 2:
                continue
            else:
                keyword, value = parts[0].lower(), parts[1].strip()
                if keyword == "host":
                    current_directives_list = []
                    for alias in value.split():
                        directives: "dict[str, str]" = {}
                        aliases[alias] = directives
                        current_directives_list.append(directives)
                else:
                    for directives in current_directives_list:
                        directives[keyword] = value

    return aliases

def resolve_git_hosts() -> "dict[str, GitHost]":
    """
    Resolves settings.GIT_HOSTS against GIT_SSH_DIR's own ssh_config file, as a one-off startup diagnostic.

    Args:
        None

    Returns:
        dict[str, GitHost]:
            Each settings.GIT_HOSTS domain mapped to its own resolved GitHost - present for every declared
            domain regardless of whether it actually resolved (pull_alias/push_alias are None when it didn't).

    Notes:
        - Intended to be called after sync_git_hosts() so ssh_config already reflects the current GIT_HOSTS -
          same "log clearly, never raise, an admin reads the log to fix it" convention as
          agent_interface.py::test_llm_tokens().
        - Safe to call with an empty settings.GIT_HOSTS - logs that git host access is unconfigured and returns
          an empty mapping.
        - A domain is resolved by scanning every parsed alias for one ending "-pull"/"-push" whose own HostName
          matches it, not by constructing the alias name from the domain - the alias itself is an opaque
          generated uuid (see sync_git_hosts()).
    """
    if not settings.GIT_HOSTS:
        logger.info("GIT_HOSTS is not configured - skipping git host resolution (repository access is disabled).")
        return {}
    else:
        ssh_config_path = settings.GIT_SSH_DIR / _SSH_CONFIG_FILENAME
        aliases = _parse_ssh_config(ssh_config_path)

        pull_alias_by_domain: "dict[str, str]" = {}
        push_alias_by_domain: "dict[str, str]" = {}
        for alias_name, directives in aliases.items():
            domain = directives.get("hostname")
            if not domain:
                continue
            elif alias_name.endswith("-pull"):
                pull_alias_by_domain[domain] = alias_name
            elif alias_name.endswith("-push"):
                push_alias_by_domain[domain] = alias_name

        resolved: "dict[str, GitHost]" = {}

        for domain in declared_domains():
            pull_alias = pull_alias_by_domain.get(domain)
            if pull_alias is None:
                logger.warning(f"git host domain {domain!r} has no usable *-pull Host block in {ssh_config_path} - it should have been generated by sync_git_hosts() on this same startup; check the log above for a generation failure.")
                resolved[domain] = GitHost(domain=domain, pull_alias=None, push_alias=None)
                continue
            else:
                push_alias = push_alias_by_domain.get(domain)
                if push_alias is None:
                    logger.info(f"git host domain {domain!r} has no usable *-push Host block - push is unavailable for it (pull-only).")

                resolved[domain] = GitHost(domain=domain, pull_alias=pull_alias, push_alias=push_alias)
                logger.info(f"Resolved git host domain {domain!r}: pull_alias={pull_alias!r}, push_alias={push_alias!r}.")

        return resolved

# =============================================================================
