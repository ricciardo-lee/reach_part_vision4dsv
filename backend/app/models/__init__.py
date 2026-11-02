from __future__ import annotations

from datetime import datetime
from typing import Optional

from tortoise import fields, models


class TimestampMixin:
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)


class AdminUser(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=64, unique=True)
    password_hash = fields.CharField(max_length=255)
    display_name = fields.CharField(max_length=128, default="")
    role = fields.CharField(max_length=32, default="operator")
    is_active = fields.BooleanField(default=True)
    last_login_at = fields.DatetimeField(null=True)

    class Meta:
        # Shared databases may already have another service's admin_users
        # (UUID id + role_id). Keep this app's accounts in a separate table.
        table = "vision_admin_users"


class AppUser(models.Model, TimestampMixin):
    """Account that signs in on the parts recognition page. Admins manage these."""

    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=64, unique=True)
    password_hash = fields.CharField(max_length=255)
    display_name = fields.CharField(max_length=128, default="")
    is_active = fields.BooleanField(default=True)
    last_login_at = fields.DatetimeField(null=True)

    class Meta:
        table = "vision_app_users"


class DeviceSession(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    session_token = fields.CharField(max_length=128, unique=True, db_index=True)
    device_id = fields.CharField(max_length=128, db_index=True)
    user_agent = fields.CharField(max_length=512, default="")
    ip_address = fields.CharField(max_length=64, default="")
    expires_at = fields.DatetimeField()
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "device_sessions"


class RecognitionSession(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    public_id = fields.CharField(max_length=36, unique=True, db_index=True)
    device_session: fields.ForeignKeyRelation[DeviceSession] = fields.ForeignKeyField(
        "models.DeviceSession", related_name="recognition_sessions", null=True
    )
    app_user: fields.ForeignKeyRelation[AppUser] = fields.ForeignKeyField(
        "models.AppUser", related_name="recognition_sessions", null=True
    )
    status = fields.CharField(max_length=32, default="created")
    task_id = fields.CharField(max_length=64, null=True)
    confirmed_category_code = fields.CharField(max_length=64, null=True)
    confirmed_category_name = fields.CharField(max_length=128, null=True)
    vehicle_brand = fields.CharField(max_length=64, null=True)
    vehicle_series = fields.CharField(max_length=64, null=True)
    vehicle_model = fields.CharField(max_length=128, null=True)
    vehicle_year = fields.CharField(max_length=32, null=True)
    oe_number = fields.CharField(max_length=64, null=True)
    oe_source = fields.CharField(max_length=32, null=True)
    optimization_consent = fields.BooleanField(default=False)
    optimization_consent_at = fields.DatetimeField(null=True)
    feedback_correct = fields.BooleanField(null=True)
    feedback_note = fields.CharField(max_length=512, null=True)
    error_message = fields.CharField(max_length=512, null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "recognition_sessions"


class UploadedImage(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    session: fields.ForeignKeyRelation[RecognitionSession] = fields.ForeignKeyField(
        "models.RecognitionSession", related_name="images"
    )
    object_key = fields.CharField(max_length=255)
    content_type = fields.CharField(max_length=64)
    file_size = fields.IntField(default=0)
    width = fields.IntField(null=True)
    height = fields.IntField(null=True)
    phash = fields.CharField(max_length=64, null=True, db_index=True)
    purpose = fields.CharField(max_length=32, default="part")
    sort_order = fields.IntField(default=0)
    focus_point = fields.JSONField(null=True)
    foreground_object_key = fields.CharField(max_length=255, null=True)
    foreground_source = fields.CharField(max_length=32, null=True)
    expires_at = fields.DatetimeField()
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "uploaded_images"


class RecognitionResult(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    session: fields.ForeignKeyRelation[RecognitionSession] = fields.ForeignKeyField(
        "models.RecognitionSession", related_name="results"
    )
    model_name = fields.CharField(max_length=128)
    prompt_version = fields.CharField(max_length=64, default="default")
    raw_response = fields.JSONField(null=True)
    part_name = fields.CharField(max_length=128, null=True)
    confidence = fields.FloatField(null=True)
    reason = fields.CharField(max_length=512, null=True)
    candidates = fields.JSONField(null=True)
    mapped_category_code = fields.CharField(max_length=64, null=True)
    mapped_category_name = fields.CharField(max_length=128, null=True)
    is_auto_part = fields.BooleanField(null=True)
    latency_ms = fields.IntField(null=True)
    token_usage = fields.JSONField(null=True)
    success = fields.BooleanField(default=False)
    error_message = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "recognition_results"


class RetrievalResult(models.Model, TimestampMixin):
    """360 gallery SKU retrieval snapshot for a recognition session."""

    id = fields.IntField(primary_key=True)
    session: fields.ForeignKeyRelation[RecognitionSession] = fields.ForeignKeyField(
        "models.RecognitionSession", related_name="retrieval_results"
    )
    index_version = fields.CharField(max_length=128, null=True)
    embedding_model = fields.CharField(max_length=128, null=True)
    decision = fields.CharField(max_length=32, null=True)
    confidence_level = fields.CharField(max_length=16, null=True)
    accepted = fields.BooleanField(default=False)
    matched_sku = fields.CharField(max_length=64, null=True)
    score = fields.FloatField(null=True)
    margin = fields.FloatField(null=True)
    selected_category_id = fields.CharField(max_length=64, null=True)
    selected_category_cn = fields.CharField(max_length=128, null=True)
    category_confidence = fields.FloatField(null=True)
    vision_assisted = fields.BooleanField(default=False)
    candidates = fields.JSONField(null=True)
    quality_warnings = fields.JSONField(null=True)
    fallback_reason = fields.CharField(max_length=128, null=True)
    latency_ms = fields.FloatField(null=True)
    image_count = fields.IntField(default=0)
    success = fields.BooleanField(default=False)
    error_message = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "retrieval_results"


class OeOcrResult(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    session: fields.ForeignKeyRelation[RecognitionSession] = fields.ForeignKeyField(
        "models.RecognitionSession", related_name="oe_ocr_results"
    )
    image: fields.ForeignKeyRelation[UploadedImage] = fields.ForeignKeyField(
        "models.UploadedImage", related_name="oe_ocr_results", null=True
    )
    oe_numbers = fields.JSONField(null=True)
    confidence = fields.FloatField(null=True)
    reason = fields.CharField(max_length=512, null=True)
    raw_response = fields.JSONField(null=True)
    confirmed_oe = fields.CharField(max_length=64, null=True)
    success = fields.BooleanField(default=False)

    class Meta:
        table = "oe_ocr_results"


class CategoryMapping(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    alias_name = fields.CharField(max_length=128, unique=True)
    category_code = fields.CharField(max_length=64, db_index=True)
    category_name = fields.CharField(max_length=128)
    is_active = fields.BooleanField(default=True)
    priority = fields.IntField(default=0)
    note = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "category_mappings"


class PromptConfig(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    version = fields.CharField(max_length=32, default="v1")
    purpose = fields.CharField(max_length=32, default="vision")
    content = fields.TextField()
    is_active = fields.BooleanField(default=True)
    note = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "prompt_configs"


class ProductQuerySnapshot(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    session: fields.ForeignKeyRelation[RecognitionSession] = fields.ForeignKeyField(
        "models.RecognitionSession", related_name="product_snapshots"
    )
    query_payload = fields.JSONField()
    result_payload = fields.JSONField(null=True)
    result_count = fields.IntField(default=0)

    class Meta:
        table = "product_query_snapshots"


class AuditLog(models.Model, TimestampMixin):
    id = fields.IntField(primary_key=True)
    actor_type = fields.CharField(max_length=32)
    actor_id = fields.CharField(max_length=64, null=True)
    action = fields.CharField(max_length=64)
    resource_type = fields.CharField(max_length=64, null=True)
    resource_id = fields.CharField(max_length=64, null=True)
    detail = fields.JSONField(null=True)
    ip_address = fields.CharField(max_length=64, null=True)

    class Meta:
        # Shared databases may already have another service's audit_logs.
        table = "vision_audit_logs"


class VisionPartOe(models.Model, TimestampMixin):
    """App-owned OE / material / category row (Excel-maintained)."""

    id = fields.IntField(primary_key=True)
    category = fields.CharField(max_length=32, db_index=True)  # COMPRESSOR/CONDENSER/RADIATOR
    material_code = fields.CharField(max_length=64, db_index=True)  # SKU unique id
    # Long OE values appear in supplier sheets; Excel may also expand numeric cells.
    oe = fields.CharField(max_length=512, db_index=True)
    oe_normalized = fields.CharField(max_length=512, db_index=True)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "vision_part_oe"
        unique_together = (("material_code", "oe"),)


class VisionPartVehicle(models.Model, TimestampMixin):
    """App-owned material ↔ vehicle fitment (make / model / year)."""

    id = fields.IntField(primary_key=True)
    material_code = fields.CharField(max_length=64, db_index=True)
    make_name = fields.CharField(max_length=128, db_index=True)
    model_name = fields.CharField(max_length=128, null=True)
    year = fields.CharField(max_length=16, null=True)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "vision_part_vehicle"
        unique_together = (("material_code", "make_name", "model_name", "year"),)
        indexes = (("make_name", "model_name"),)


def _build_radiator_spec_model():
    """Generate VisionRadiatorSpec with all radiator columns as nullable CharFields."""
    from app.core.catalog_fields import RADIATOR_SPEC_FIELDS

    attrs: dict = {
        "id": fields.IntField(primary_key=True),
        "material_code": fields.CharField(max_length=64, unique=True, db_index=True),
        "is_active": fields.BooleanField(default=True),
        "created_at": fields.DatetimeField(auto_now_add=True),
        "updated_at": fields.DatetimeField(auto_now=True),
        "Meta": type("Meta", (), {"table": "vision_radiator_spec"}),
        "__module__": __name__,
        "__doc__": "App-owned radiator technical parameters (Excel-maintained).",
    }
    # TEXT (not VARCHAR) — ~77 tech-spec columns exceed MySQL InnoDB row size
    # with utf8mb4 VARCHAR(255) (error 1118).
    for name in RADIATOR_SPEC_FIELDS:
        attrs[name] = fields.TextField(null=True)
    return type("VisionRadiatorSpec", (models.Model,), attrs)


VisionRadiatorSpec = _build_radiator_spec_model()


class CatalogImportLog(models.Model, TimestampMixin):
    """Excel import audit trail for catalog admin."""

    id = fields.IntField(primary_key=True)
    kind = fields.CharField(max_length=64, db_index=True)  # oe/vehicles/spec_*
    filename = fields.CharField(max_length=255, default="")
    total_rows = fields.IntField(default=0)
    success_count = fields.IntField(default=0)
    failure_count = fields.IntField(default=0)
    errors = fields.JSONField(null=True)
    operator = fields.CharField(max_length=64, default="")

    class Meta:
        table = "vision_catalog_import_logs"


class WaContact(models.Model, TimestampMixin):
    """WhatsApp end-user identified by phone number (wa_id)."""

    id = fields.IntField(primary_key=True)
    wa_id = fields.CharField(max_length=32, unique=True, db_index=True)
    profile_name = fields.CharField(max_length=128, default="")
    last_seen_at = fields.DatetimeField(null=True)

    class Meta:
        table = "wa_contacts"


class WaConversation(models.Model, TimestampMixin):
    """A WhatsApp chat thread that resets after idle timeout."""

    id = fields.IntField(primary_key=True)
    contact: fields.ForeignKeyRelation[WaContact] = fields.ForeignKeyField(
        "models.WaContact", related_name="conversations"
    )
    status = fields.CharField(max_length=16, default="open", db_index=True)
    last_message_at = fields.DatetimeField(null=True)
    message_count = fields.IntField(default=0)
    llm_tokens = fields.IntField(default=0)
    welcome_sent_at = fields.DatetimeField(null=True)

    class Meta:
        table = "wa_conversations"


class WaMessage(models.Model, TimestampMixin):
    """Inbound or outbound WhatsApp message within a conversation."""

    id = fields.IntField(primary_key=True)
    conversation: fields.ForeignKeyRelation[WaConversation] = fields.ForeignKeyField(
        "models.WaConversation", related_name="messages"
    )
    direction = fields.CharField(max_length=8, db_index=True)  # in | out
    wa_message_id = fields.CharField(max_length=128, null=True, unique=True, db_index=True)
    msg_type = fields.CharField(max_length=32, default="text")
    text = fields.TextField(null=True)
    raw_payload = fields.JSONField(null=True)
    tool_calls = fields.JSONField(null=True)
    delivery_status = fields.CharField(max_length=32, null=True)
    latency_ms = fields.IntField(null=True)
    token_usage = fields.JSONField(null=True)
    error_message = fields.CharField(max_length=512, null=True)
    recognition_session_id = fields.IntField(null=True, db_index=True)
    media_id = fields.CharField(max_length=128, null=True)
    object_key = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "wa_messages"
