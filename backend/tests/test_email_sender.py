from unittest.mock import MagicMock, patch

import pytest

from app.email_sender import EmailNotConfigured, EmailSendFailed, send_email


def test_raises_email_not_configured_without_smtp_host(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(EmailNotConfigured):
        send_email(to="a@example.com", subject="Subject", body_text="Body")


def test_sends_via_smtp_when_configured(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "noreply@example.com")

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch("app.email_sender.smtplib.SMTP", return_value=mock_smtp) as mock_ctor:
        send_email(to="client@example.com", subject="Join Nutri-Matic", body_text="Come join!")

    mock_ctor.assert_called_once_with("smtp.example.com", 587, timeout=10)
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("user@example.com", "secret")
    mock_smtp.sendmail.assert_called_once()
    args = mock_smtp.sendmail.call_args.args
    assert args[0] == "noreply@example.com"
    assert args[1] == ["client@example.com"]
    assert "Come join!" in args[2]


def test_skips_login_without_credentials(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "noreply@example.com")

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch("app.email_sender.smtplib.SMTP", return_value=mock_smtp):
        send_email(to="client@example.com", subject="Subject", body_text="Body")

    mock_smtp.login.assert_not_called()


def test_wraps_smtp_failure(monkeypatch):
    import smtplib

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "noreply@example.com")

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.sendmail.side_effect = smtplib.SMTPRecipientsRefused({"client@example.com": (550, b"rejected")})

    with patch("app.email_sender.smtplib.SMTP", return_value=mock_smtp):
        with pytest.raises(EmailSendFailed):
            send_email(to="client@example.com", subject="Subject", body_text="Body")
