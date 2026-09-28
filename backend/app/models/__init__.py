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
