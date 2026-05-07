import asyncio

from twilio.rest import Client

from app.config import settings

client = Client(settings.twilio_account_sid, settings.twilio_auth_token)


async def send_whatsapp(to: str, body: str) -> str:
    """Send a free-form WhatsApp message. Returns the message SID."""

    def _send() -> str:
        message = client.messages.create(
            from_=settings.twilio_from_whatsapp,
            to=to,
            body=body,
        )
        return message.sid

    return await asyncio.to_thread(_send)


async def send_template(to: str, template_sid: str, variables: dict) -> str:
    """Send a WhatsApp template message. Returns the message SID."""

    def _send() -> str:
        message = client.messages.create(
            from_=settings.twilio_from_whatsapp,
            to=to,
            content_sid=template_sid,
            content_variables=variables,
        )
        return message.sid

    return await asyncio.to_thread(_send)
