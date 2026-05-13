from pydantic import BaseModel, Field


class TwilioInbound(BaseModel):
    """Form fields from Twilio inbound WhatsApp webhook."""

    From: str = Field(min_length=1)
    Body: str
    MessageSid: str = Field(min_length=1)
    media_items: list[tuple[str, str]] = []  # [(url, content_type), ...]


class MailgunInbound(BaseModel):
    """JSON payload from Mailgun inbound route."""

    sender: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body_plain: str = ""
