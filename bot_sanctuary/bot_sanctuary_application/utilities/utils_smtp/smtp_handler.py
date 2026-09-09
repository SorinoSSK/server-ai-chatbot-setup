# =============================================================================
# File        : smtp_handler.py
# Description : Sends mail via SMTP and provides a manually-triggerable connectivity/credential test.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - send_mail() - sends a plain-text email via SMTP, supporting implicit TLS, STARTTLS, or no TLS, with optional authentication.
#   - test_smtp_configuration() - sends a single fixed test email to verify configuration end-to-end.
#
# Notes       :
#   - SMTP credentials are never logged in full - only whether a value is set.
#   - Mail sending is inert until SMTP_ENABLE_MAILER is explicitly turned on.
#   - See README.md for how to trigger the connectivity test manually.
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
    Masks a sensitive setting for safe logging - never reveals any part of the actual value, only whether it is set at all.

    Args:
        value (str):
            Setting value to mask.

    Returns:
        str:
            "<set>" if value is non-empty; otherwise "<unset>".
    """
    return "<set>" if value else "<unset>"

def _build_message(subject: str, body: str, to_addresses: list[str]) -> MIMEMultipart:
    """
    Builds a plain-text MIME message ready to be sent.

    Args:
        subject (str):
            Email subject line.

        body (str):
            Plain-text email body.

        to_addresses (list[str]):
            Recipient addresses.

    Returns:
        MIMEMultipart:
            The constructed message.

    Notes:
        - The From header displays TELEGRAM_BOT_NAME alongside SMTP_FROM_EMAIL when a bot name is configured, falling back to the bare address otherwise.
        - This only affects the message header, not the SMTP envelope sender, which always uses the bare address.
    """
    message = MIMEMultipart()
    message["From"] = formataddr((settings.TELEGRAM_BOT_NAME, settings.SMTP_FROM_EMAIL)) if settings.TELEGRAM_BOT_NAME else settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(to_addresses)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))
    return message

def _open_smtp_connection() -> smtplib.SMTP:
    """
    Opens and returns a connected SMTP session, ready for authentication and sending.

    The connection method (implicit TLS, STARTTLS, or no TLS) is determined by SMTP_FORCE_SSL and SMTP_SKIP_TLS.

    Args:
        None

    Returns:
        smtplib.SMTP:
            An open connection - the caller is responsible for calling .quit().

    Raises:
        Exception:
            Whatever smtplib/ssl raises on a connection failure - left for the caller to handle.
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
        subject (str):
            Email subject line.

        body (str):
            Plain-text email body.

        to_addresses (list[str] | str):
            A single recipient address, or a list of addresses.

    Returns:
        bool:
            True if sent successfully; otherwise False.

    Notes:
        - A no-op while SMTP_ENABLE_MAILER is unset - returns False without attempting to connect.
        - Authentication is skipped entirely when SMTP_AUTH_TYPE is "NONE".
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
    Sends a single fixed test email, to confirm SMTP configuration works end-to-end.

    Args:
        to_address (str | None, optional):
            Recipient for the test email. Defaults to SMTP_TO_EMAIL, then SMTP_FROM_EMAIL, if omitted.

    Returns:
        bool:
            True if the test mail was sent successfully; otherwise False.

    Notes:
        - Not run automatically at application startup - see README.md for how to trigger it manually.
        - Fails fast if mailer configuration or a resolvable recipient is missing, rather than attempting a connection that cannot succeed.
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
# Lets an administrator trigger the SMTP test manually, independent of the application's own startup sequence - see README.md for usage.

if __name__ == "__main__":
    import sys

    from ..logging_setup import setup_logging

    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()

    override_recipient = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_smtp_configuration(override_recipient)
    sys.exit(0 if success else 1)

# =============================================================================
