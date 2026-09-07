# =============================================================================
# File        : smtp_handler.py
# Description : File responsible for sending mail via SMTP and for a manually-triggerable connectivity/credential test.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - send_mail() - sends a plain-text email via SMTP, honouring SMTP_ENABLE_MAILER/SMTP_FORCE_SSL/SMTP_SKIP_TLS/SMTP_AUTH_TYPE.
#   - test_smtp_configuration() - sends a single fixed test email, intended to be triggered manually, e.g.:
#       docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler
#       docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler someone@example.com
#     Deliberately not run automatically at application startup - see bot_sanctuary/CODE_TODO.md §4.
#
# Notes       :
#   - SMTP_FROM_EMAIL/SMTP_USERNAME/SMTP_PASSWORD are never logged in full - _mask() only ever reports whether a value is set, never any part of its actual content (not even a partial reveal), since no specific masking scheme was mandated and this is the safest reading of "mask" for a credential.
#   - send_mail() is a no-op (logged, returns False) while SMTP_ENABLE_MAILER is unset - see bot_sanctuary/CODE_TODO.md §4.
#
# =============================================================================
# I M P O R T   H E A D E R

import ssl
import smtplib
import logging

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _mask(value: str) -> str:
    """
    Masks a sensitive setting for safe logging - never reveals any part of the actual value, only
    whether it is set at all.

    Args:
        value (str)

    Returns:
        str:
            "<set>" if value is non-empty; otherwise "<unset>".
    """
    return "<set>" if value else "<unset>"

def _build_message(subject: str, body: str, to_addresses: list[str]) -> MIMEMultipart:
    """
    Builds a plain-text MIME message ready to be sent.

    Args:
        subject (str)

        body (str)

        to_addresses (list[str])

    Returns:
        MIMEMultipart

    Notes:
        - The From header renders as "TELEGRAM_BOT_NAME <SMTP_FROM_EMAIL>" (e.g. "Rukia <noreply@example.com>") when TELEGRAM_BOT_NAME is set, via email.utils.formataddr() - which also takes care of quoting the display name if it ever contains characters (commas, angle brackets, etc.) that would otherwise make the header ambiguous.
        - Falls back to the bare address when TELEGRAM_BOT_NAME is unset.
        - Deliberately reuses TELEGRAM_BOT_NAME (config.py's "Bot Identity" section, shared with telegram_gateway) rather than a separate SMTP-only name setting, so mail sent by this application identifies as the same persona the user already talks to on Telegram.
        - This only affects the message header, not the SMTP envelope sender - send_mail() still passes the bare settings.SMTP_FROM_EMAIL as sendmail()'s from_addr, since the envelope sender is required to be a plain address regardless of what the header displays.
    """
    message = MIMEMultipart()
    message["From"] = formataddr((settings.TELEGRAM_BOT_NAME, settings.SMTP_FROM_EMAIL)) if settings.TELEGRAM_BOT_NAME else settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(to_addresses)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))
    return message

def _open_smtp_connection() -> smtplib.SMTP:
    """
    Opens and returns a connected SMTP session, ready for send_mail() to authenticate (unless
    SMTP_AUTH_TYPE is "NONE") and send through.

    Args:
        None

    Returns:
        smtplib.SMTP:
            Ready for .login()/.sendmail() - caller is responsible for calling .quit().

    Raises:
        Exception:
            Whatever smtplib/ssl raises on a connection failure - not caught here, left for the caller (send_mail()) to handle.

    Notes:
        - SMTP_FORCE_SSL=True: connects via smtplib.SMTP_SSL (implicit TLS from the first byte - typically port 465).
          SMTP_SKIP_TLS is not consulted in this branch - implicit TLS cannot be selectively skipped once SMTP_FORCE_SSL is set.
        - SMTP_FORCE_SSL=False, SMTP_SKIP_TLS=False (default): connects via smtplib.SMTP, then upgrades with STARTTLS - typically port 587.
        - SMTP_FORCE_SSL=False, SMTP_SKIP_TLS=True: connects via smtplib.SMTP with no TLS at all - typically port 25, only appropriate for a trusted internal relay.
    """
    if settings.SMTP_FORCE_SSL:
        return smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ssl.create_default_context())
    else:
        connection = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
        if not settings.SMTP_SKIP_TLS:
            connection.starttls(context=ssl.create_default_context())

        return connection

def send_mail(subject: str, body: str, to_addresses: list[str] | str) -> bool:
    """
    Sends a plain-text email via SMTP.

    Args:
        subject (str)

        body (str)

        to_addresses (list[str] | str):
            A single recipient address, or a list of addresses.

    Returns:
        bool:
            True if sent successfully; otherwise False.

    Notes:
        - No-op (logged, returns False) while SMTP_ENABLE_MAILER is unset - see bot_sanctuary/CODE_TODO.md §4.
        - SMTP_AUTH_TYPE="NONE" (case-insensitive) skips .login() entirely, for a relay that doesn't require authentication.
          Any other value authenticates via SMTP_USERNAME/SMTP_PASSWORD - see _open_smtp_connection()'s Notes for why no further distinction between mechanism names is made.
        - settings.SMTP_FROM_EMAIL/SMTP_USERNAME/SMTP_PASSWORD are never logged in full - see _mask().
    """
    if not settings.SMTP_ENABLE_MAILER:
        logger.warning("SMTP_ENABLE_MAILER is unset - mail not sent (no-op).")
        return False
    else:
        addresses = [to_addresses] if isinstance(to_addresses, str) else to_addresses
        if not addresses:
            logger.error("send_mail() called with no recipient. Mail not sent.")
            return False
        else:
            message = _build_message(subject, body, addresses)

            logger.info(
                f"Sending mail via {settings.SMTP_HOST}:{settings.SMTP_PORT} "
                f"(from={_mask(settings.SMTP_FROM_EMAIL)}, from_name={settings.TELEGRAM_BOT_NAME!r}, "
                f"username={_mask(settings.SMTP_USERNAME)}, to={addresses}, subject={subject!r})."
            )

            connection = None
            try:
                connection = _open_smtp_connection()
                if settings.SMTP_AUTH_TYPE.strip().upper() != "NONE":
                    connection.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

                connection.sendmail(settings.SMTP_FROM_EMAIL, addresses, message.as_string())
                logger.info(f"Mail sent successfully to {addresses}.")
                return True
            except Exception:
                logger.exception(f"Failed to send mail to {addresses}.")
                return False
            finally:
                if connection is not None:
                    try:
                        connection.quit()
                    except Exception:
                        pass

def test_smtp_configuration(to_address: str | None = None) -> bool:
    """
    Sends a single fixed test email, to confirm SMTP_* configuration actually works end-to-end.

    Args:
        to_address (str | None, optional):
            Recipient for the test email - an explicit override, mainly for ad-hoc testing.
            Defaults to SMTP_TO_EMAIL (the configured alert recipient) if omitted, then to SMTP_FROM_EMAIL (send to self) if that's unset too.

    Returns:
        bool:
            True if the test mail was sent successfully; otherwise False.

    Notes:
        - Not run automatically at application startup - intended to be triggered manually, e.g.:
          docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler
          docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler someone@example.com  (override)
        - Fails fast (logged, returns False) if SMTP_ENABLE_MAILER/SMTP_HOST/a resolvable recipient are missing, rather than attempting a connection that can't succeed.
    """
    if not settings.SMTP_ENABLE_MAILER:
        logger.error(
            "SMTP_ENABLE_MAILER is unset - cannot run the SMTP test. "
            "Set SMTP_ENABLE_MAILER=true and the other SMTP_* connection settings first."
        )
        return False
    else:
        recipient = to_address or settings.SMTP_TO_EMAIL or settings.SMTP_FROM_EMAIL
        if not recipient:
            logger.error(
                "No recipient available for the SMTP test - pass one explicitly, or set SMTP_TO_EMAIL "
                "(preferred) or SMTP_FROM_EMAIL so it can be used as the default."
            )
            return False
        elif not settings.SMTP_HOST:
            logger.error("SMTP_HOST is unset - cannot run the SMTP test.")
            return False
        else:
            logger.info(f"Running SMTP test - sending to {recipient} via {settings.SMTP_HOST}:{settings.SMTP_PORT}...")
            sent = send_mail(
                subject="Bot Sanctuary - SMTP test",
                body="This is a test email confirming Bot Sanctuary's SMTP configuration is working.",
                to_addresses=recipient
            )
            if sent:
                logger.info("SMTP test PASSED - mail sent successfully.")
            else:
                logger.error("SMTP test FAILED - see the error logged above for details.")

            return sent

# =============================================================================
# C O M M A N D   L I N E   E N T R Y   P O I N T
#
# Lets an administrator trigger the SMTP test manually, independent of the application's own startup sequence, e.g.:
#   docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler
#   docker exec <container_name> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler someone@example.com

if __name__ == "__main__":
    import sys

    from ..logging_setup import setup_logging

    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()

    override_recipient = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_smtp_configuration(override_recipient)
    sys.exit(0 if success else 1)

# =============================================================================
