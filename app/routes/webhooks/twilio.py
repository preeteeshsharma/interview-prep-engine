from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import settings
from app.lib.logging import get_logger
from app.schemas.webhooks import TwilioInbound

router = APIRouter()
logger = get_logger(__name__)


def _validate_twilio_signature(request: Request, params: dict) -> None:
    """Raise HTTP 403 if the Twilio signature header is missing or invalid."""
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(url, params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/hooks/twilio")
async def twilio_webhook(request: Request) -> Response:
    form_data = await request.form()
    params = dict(form_data)

    _validate_twilio_signature(request, params)

    payload = TwilioInbound(
        From=params.get("From", ""),
        Body=params.get("Body", ""),
        MessageSid=params.get("MessageSid", ""),
    )

    logger.info(
        "twilio.inbound.received",
        from_=payload.From,
        message_sid=payload.MessageSid,
        body_preview=payload.Body[:80],
    )

    # Intent routing stub — log and ACK.
    logger.info("twilio.inbound.routing_stub", body=payload.Body)

    twiml = "<Response><Message>ACK</Message></Response>"
    return Response(content=twiml, media_type="application/xml")
