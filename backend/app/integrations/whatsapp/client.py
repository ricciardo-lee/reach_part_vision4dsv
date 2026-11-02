"""HTTP client for Meta WhatsApp Cloud API."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4096


class WhatsAppCloudClient:
    def __init__(
        self,
        *,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout: float = 30.0,
        proxy: Optional[str] = None,
        retries: Optional[int] = None,
    ) -> None:
        self.access_token = access_token if access_token is not None else settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = (
            phone_number_id if phone_number_id is not None else settings.WHATSAPP_PHONE_NUMBER_ID
        )
        self.api_version = api_version or settings.WHATSAPP_GRAPH_API_VERSION
        self.timeout = timeout
        configured_proxy = (proxy if proxy is not None else settings.WHATSAPP_HTTP_PROXY) or ""
        self.proxy = configured_proxy.strip() or None
        self.retries = max(
            1,
            int(retries if retries is not None else (settings.WHATSAPP_HTTP_RETRIES or 3)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    def _url(self, path: str) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.Client:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return httpx.Client(**kwargs)

    def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with self._client() as client:
                    response = client.request(method, url, **kwargs)
                return response
            except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt >= self.retries:
                    break
                delay = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "WhatsApp HTTP retry | method=%s | attempt=%s/%s | wait=%ss | error=%s",
                    method,
                    attempt,
                    self.retries,
                    delay,
                    exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("WhatsApp Cloud API is not configured")
        url = self._url(path)
        response = self._request_with_retry(
            "POST",
            url,
            headers=self._headers(),
            json=payload,
        )
        if response.status_code >= 400:
            logger.error(
                "WhatsApp API error | status=%s | body=%s",
                response.status_code,
                response.text[:500],
            )
            response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def send_text(self, to: str, text: str, *, preview_url: bool = False) -> list[str]:
        """Send one or more text messages (auto-split at 4096). Returns message ids."""
        body = (text or "").strip()
        if not body:
            return []
        chunks = _chunk_text(body, MAX_TEXT_LENGTH)
        message_ids: list[str] = []
        for chunk in chunks:
            data = self._post(
                f"{self.phone_number_id}/messages",
                {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": preview_url, "body": chunk},
                },
            )
            mid = _extract_message_id(data)
            if mid:
                message_ids.append(mid)
            logger.info("WhatsApp send_text | to=%s | message_id=%s | chars=%s", to, mid, len(chunk))
        return message_ids

    def send_interactive_buttons(
        self,
        to: str,
        body: str,
        buttons: list[tuple[str, str]],
        *,
        footer: Optional[str] = None,
    ) -> list[str]:
        """Send an interactive reply-button message (max 3 buttons, title <= 20 chars)."""
        text = (body or "").strip()
        if not text:
            return []
        prepared: list[dict[str, Any]] = []
        for raw_id, raw_title in buttons[:3]:
            bid = str(raw_id or "").strip()
            title = str(raw_title or "").strip()[:20]
            if not bid or not title:
                continue
            prepared.append({"type": "reply", "reply": {"id": bid, "title": title}})
        if not prepared:
            return []
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": text[:MAX_TEXT_LENGTH]},
            "action": {"buttons": prepared},
        }
        footer_text = (footer or "").strip()
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}
        data = self._post(
            f"{self.phone_number_id}/messages",
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            },
        )
        mid = _extract_message_id(data)
        message_ids = [mid] if mid else []
        logger.info(
            "WhatsApp send_interactive_buttons | to=%s | message_id=%s | buttons=%s",
            to,
            mid,
            len(prepared),
        )
        return message_ids

    def mark_read(self, message_id: str, *, typing: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        return self._post(f"{self.phone_number_id}/messages", payload)

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media bytes and content-type from Meta CDN."""
        if not self.configured:
            raise RuntimeError("WhatsApp Cloud API is not configured")
        meta_url = self._url(media_id)
        meta_resp = self._request_with_retry("GET", meta_url, headers=self._headers())
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        download_url = str(meta.get("url") or "")
        if not download_url:
            raise RuntimeError("WhatsApp media URL missing")
        media_resp = self._request_with_retry("GET", download_url, headers=self._headers())
        media_resp.raise_for_status()
        content_type = media_resp.headers.get("content-type", "application/octet-stream")
        return media_resp.content, content_type


def _chunk_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [c for c in chunks if c]


def _extract_message_id(data: dict[str, Any]) -> Optional[str]:
    messages = data.get("messages") or []
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            mid = first.get("id")
            return str(mid) if mid else None
    return None
