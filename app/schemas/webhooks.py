from pydantic import BaseModel, Field


class TwilioInbound(BaseModel):
    """Form fields from Twilio inbound WhatsApp webhook."""

    From: str = Field(min_length=1)
    Body: str
    MessageSid: str = Field(min_length=1)


class MailgunInbound(BaseModel):
    """JSON payload from Mailgun inbound route."""

    sender: str
    subject: str
    body_plain: str = ""
