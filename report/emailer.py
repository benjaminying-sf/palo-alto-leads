"""
Sends the weekly HTML report via Gmail SMTP.

Setup required (one-time):
  1. Go to https://myaccount.google.com/apppasswords
  2. Create an App Password for "Mail" on your Mac
  3. Add EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENT to your .env file
"""
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger(__name__)


def send_report(html: str, new_count: int) -> bool:
    """
    Send the HTML report as a rich email.
    Returns True on success, False on failure.
    """
    if not config.EMAIL_SENDER or not config.EMAIL_APP_PASSWORD:
        logger.error(
            "Email not configured. Add EMAIL_SENDER and EMAIL_APP_PASSWORD to your .env file."
        )
        return False

    subject = (
        f"[Palo Alto Leads] {new_count} New Motivated Seller Leads — "
        f"Week of {datetime.now().strftime('%B %d, %Y')}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"PA Lead System <{config.EMAIL_SENDER}>"
    msg["To"] = config.EMAIL_RECIPIENT

    # Plain-text fallback
    plain_text = (
        f"Palo Alto Motivated Seller Leads — Week of {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"{new_count} new leads found this week.\n\n"
        "Open the HTML version of this email to review the full report with contact details "
        "and call scripts."
    )
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
            smtp.sendmail(
                config.EMAIL_SENDER,
                config.EMAIL_RECIPIENT,
                msg.as_string(),
            )
        logger.info("Report emailed to %s", config.EMAIL_RECIPIENT)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you are using an App Password, "
            "not your regular Gmail password. See https://myaccount.google.com/apppasswords"
        )
        return False
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False
