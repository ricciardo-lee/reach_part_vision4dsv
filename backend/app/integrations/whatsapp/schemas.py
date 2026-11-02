"""Pydantic models for Meta WhatsApp Cloud API webhook payloads."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class WaTextBody(BaseModel):
    body: str = ""


class WaMedia(BaseModel):
    id: str = ""
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None


class WaInboundMessage(BaseModel):
    id: str
    from_: str = Field(alias="from")
    timestamp: Optional[str] = None
    type: str = "text"
    text: Optional[WaTextBody] = None
    image: Optional[WaMedia] = None
    interactive: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}

    @property
    def button_reply_id(self) -> str:
        interactive = self.interactive if isinstance(self.interactive, dict) else {}
        reply = interactive.get("button_reply") if isinstance(interactive, dict) else None
        if isinstance(reply, dict):
            return str(reply.get("id") or "").strip()
        return ""

    @property
    def button_reply_title(self) -> str:
        interactive = self.interactive if isinstance(self.interactive, dict) else {}
        reply = interactive.get("button_reply") if isinstance(interactive, dict) else None
        if isinstance(reply, dict):
            return str(reply.get("title") or "").strip()
        return ""

    @property
    def text_body(self) -> str:
        if self.text and self.text.body:
            return self.text.body.strip()
        if self.type == "interactive":
            title = self.button_reply_title
            if title:
                return title
        if self.image and self.image.caption:
            return str(self.image.caption).strip()
        return ""

    @property
    def media_id(self) -> str:
        if self.image and self.image.id:
            return str(self.image.id).strip()
        return ""

    @property
    def mime_type(self) -> str:
        if self.image and self.image.mime_type:
            return str(self.image.mime_type).strip()
        return ""


class WaContactProfile(BaseModel):
    name: Optional[str] = None


class WaContact(BaseModel):
    wa_id: str = Field(alias="wa_id", default="")
    profile: Optional[WaContactProfile] = None

    model_config = {"populate_by_name": True}


class WaStatus(BaseModel):
    id: str
    status: str
    timestamp: Optional[str] = None
    recipient_id: Optional[str] = None


class WaMetadata(BaseModel):
    display_phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None


class WaValue(BaseModel):
    messaging_product: Optional[str] = None
    metadata: Optional[WaMetadata] = None
    contacts: List[dict[str, Any]] = Field(default_factory=list)
    messages: List[dict[str, Any]] = Field(default_factory=list)
    statuses: List[dict[str, Any]] = Field(default_factory=list)


class WaChange(BaseModel):
    field: Optional[str] = None
    value: WaValue = Field(default_factory=WaValue)


class WaEntry(BaseModel):
    id: Optional[str] = None
    changes: List[WaChange] = Field(default_factory=list)


class WaWebhookPayload(BaseModel):
    object: Optional[str] = None
    entry: List[WaEntry] = Field(default_factory=list)


def parse_inbound_messages(payload: WaWebhookPayload) -> list[tuple[WaInboundMessage, str]]:
    """Return list of (message, profile_name) from a webhook payload."""
    results: list[tuple[WaInboundMessage, str]] = []
    for entry in payload.entry:
        for change in entry.changes:
            value = change.value
            name_by_wa_id: dict[str, str] = {}
            for raw_contact in value.contacts or []:
                wa_id = str(raw_contact.get("wa_id") or "").strip()
                profile = raw_contact.get("profile") or {}
                name = str(profile.get("name") or "").strip() if isinstance(profile, dict) else ""
                if wa_id:
                    name_by_wa_id[wa_id] = name
            for raw in value.messages or []:
                try:
                    msg = WaInboundMessage.model_validate(raw)
                except Exception:  # noqa: BLE001
                    continue
                results.append((msg, name_by_wa_id.get(msg.from_, "")))
    return results


def parse_statuses(payload: WaWebhookPayload) -> list[WaStatus]:
    results: list[WaStatus] = []
    for entry in payload.entry:
        for change in entry.changes:
            for raw in change.value.statuses or []:
                try:
                    results.append(WaStatus.model_validate(raw))
                except Exception:  # noqa: BLE001
                    continue
    return results
