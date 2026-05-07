from pydantic import BaseModel


class TwilioInbound(BaseModel):
    """Form fields from Twilio inbound WhatsApp webhook."""

    From: str
    Body: str
    MessageSid: str


class MailgunInbound(BaseModel):
    """JSON payload from Mailgun inbound route."""

    sender: str
    subject: str
    body_plain: str = ""
