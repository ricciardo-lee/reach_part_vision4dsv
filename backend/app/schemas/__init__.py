from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class APIResponse(BaseModel):
    success: bool = True
    message: str = "ok"
    data: Any = None


class DeviceSessionCreate(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)


class DeviceSessionOut(APIModel):
    session_token: str
    expires_at: datetime


class FocusPointOut(BaseModel):
    x: float
    y: float
    source: Optional[str] = None


class ImageFocusPointIn(BaseModel):
    image_id: int
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    source: Optional[str] = None


class ImageFocusPointsIn(BaseModel):
    items: List[ImageFocusPointIn] = Field(min_length=1)


class ImageOut(APIModel):
    id: int
    object_key: str
    purpose: str
    sort_order: int
    preview_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    focus_point: Optional[FocusPointOut] = None
    foreground_preview_url: Optional[str] = None
    foreground_source: Optional[str] = None


class CandidateOut(BaseModel):
    name: str
    confidence: float
    category_code: Optional[str] = None
    category_name: Optional[str] = None


class RecognitionResultOut(APIModel):
    is_auto_part: bool = True
    part_name: Optional[str] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None
    candidates: List[CandidateOut] = Field(default_factory=list)
    mapped_category_code: Optional[str] = None
    mapped_category_name: Optional[str] = None


class RetrievalCandidateOut(BaseModel):
    sku: str
    category_id: Optional[str] = None
    category_cn: Optional[str] = None
    score: float = 0.0
    matched_views: List[str] = Field(default_factory=list)
    reason: str = "vector_match"


class RetrievalMatchOut(BaseModel):
    accepted: bool = False
    decision: Optional[str] = None
    confidence_level: Optional[str] = None
    matched_sku: Optional[str] = None
    score: Optional[float] = None
    margin: Optional[float] = None
    selected_category_id: Optional[str] = None
    selected_category_cn: Optional[str] = None
    category_confidence: Optional[float] = None
    vision_assisted: bool = False
    index_version: Optional[str] = None
    embedding_model: Optional[str] = None
    fallback_reason: Optional[str] = None
    candidates: List[RetrievalCandidateOut] = Field(default_factory=list)


class RecognitionSessionOut(APIModel):
    public_id: str
    status: str
    progress_hint: Optional[str] = None
    is_auto_part: bool = True
    recognition_mode: Optional[str] = None  # sku_match | category_match | vision_fallback
    images: List[ImageOut] = Field(default_factory=list)
    result: Optional[RecognitionResultOut] = None
    retrieval: Optional[RetrievalMatchOut] = None
    confirmed_category_code: Optional[str] = None
    confirmed_category_name: Optional[str] = None
    vehicle_brand: Optional[str] = None
    vehicle_series: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[str] = None
    oe_number: Optional[str] = None
    oe_source: Optional[str] = None
    optimization_consent: bool = False
    error_message: Optional[str] = None


class ConfirmCategoryIn(BaseModel):
    category_code: Optional[str] = None
    category_name: str
    optimization_consent: bool = False


class VehicleFilterIn(BaseModel):
    brand: Optional[str] = None
    series: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    oe_number: Optional[str] = None
    oe_source: Optional[str] = "manual"


class OeConfirmIn(BaseModel):
    oe_number: str = Field(min_length=3, max_length=64)


class FeedbackIn(BaseModel):
    correct: bool
    note: Optional[str] = None


class ProductOut(BaseModel):
    sku: str
    name: str
    category_name: Optional[str] = None
    oe_number: Optional[str] = None
    brand: Optional[str] = None
    fitment: Optional[str] = None
    image_url: Optional[str] = None
    stock_status: Optional[str] = None
    price: Optional[float] = None
    match_reason: Optional[str] = None
    # Reserved for future technical-attribute narrowing (empty for now).
    attributes: Optional[dict] = None


class AdminLoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    display_name: str


class AdminUserOut(APIModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None


class CategoryMappingIn(BaseModel):
    alias_name: str
    category_code: str
    category_name: str
    is_active: bool = True
    priority: int = 0
    note: Optional[str] = None


class CategoryMappingOut(CategoryMappingIn, APIModel):
    id: int


class PromptConfigIn(BaseModel):
    name: str
    version: str = "v1"
    purpose: str = "vision"
    content: str
    is_active: bool = True
    note: Optional[str] = None


class PromptConfigOut(PromptConfigIn, APIModel):
    id: int


class AuditLogOut(APIModel):
    id: int
    actor_type: str
    actor_id: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    detail: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime


class StatsOut(BaseModel):
    total_sessions: int
    success_sessions: int
    failed_sessions: int
    avg_confidence: Optional[float]
    feedback_correct_rate: Optional[float]
    top1_hit_rate: Optional[float] = None
    top3_hit_rate: Optional[float] = None
    reject_rate: Optional[float] = None
    labeled_sessions: int = 0
    sku_match_sessions: int = 0
    category_match_sessions: int = 0
    vision_fallback_sessions: int = 0
    sku_match_rate: Optional[float] = None
    category_match_rate: Optional[float] = None


class ConsentIn(BaseModel):
    optimization_consent: bool = True
