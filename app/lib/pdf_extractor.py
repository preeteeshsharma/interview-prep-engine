from __future__ import annotations

import io

import httpx
from pypdf import PdfReader


async def extract_text_from_pdf_url(url: str, auth: tuple[str, str] | None = None) -> str:
    """Download a PDF and return its full text. auth=(account_sid, token) for Twilio media URLs."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=auth, follow_redirects=True)
        resp.raise_for_status()
    reader = PdfReader(io.BytesIO(resp.content))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
