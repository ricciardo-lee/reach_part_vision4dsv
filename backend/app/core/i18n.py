"""Lightweight Accept-Language helpers for public API user-facing messages."""

from __future__ import annotations

from typing import Any

from fastapi import Request

DEFAULT_LOCALE = "zh-CN"
SUPPORTED = ("zh-CN", "en-US")

MESSAGES: dict[str, dict[str, str]] = {
    "zh-CN": {
        "auth.bad_credentials": "用户名或密码错误",
        "auth.login_required": "请先登录",
        "auth.token_invalid": "Token 无效",
        "auth.token_type": "Token 类型错误",
        "auth.user_disabled": "用户不存在或已禁用",
        "auth.missing_device_token": "缺少设备会话 Token",
        "auth.device_expired": "设备会话无效或已过期",
        "auth.rate_limited": "登录过于频繁，请稍后再试",
        "auth.device_disabled": "设备会话接口已停用，请使用账号登录",
        "session.not_found": "识别会话不存在",
        "session.forbidden": "无权访问该识别会话",
        "upload.purpose_invalid": "purpose 仅支持 part / oe_label（兼容旧角度字段会自动转为 part）",
        "upload.min_one": "请至少上传 1 张图片",
        "upload.purpose_max": "该用途最多上传 {count} 张图片",
        "upload.part_total_max": "零件图合计最多上传 {count} 张",
        "upload.batch_max": "单次最多上传 {count} 张图片",
        "upload.done": "已上传 {count} 张图片",
        "focus.images_missing": "图片不属于当前会话: {missing}",
        "focus.part_only": "仅零件图可设置焦点",
        "focus.saved": "已保存焦点",
        "recognize.rate_limited": "识别过于频繁，请稍后再试",
        "recognize.need_images": "请先上传零件图片",
        "recognize.done": "识别完成",
        "recognize.started": "识别任务已启动",
        "consent.updated": "授权已更新",
        "consent.revoked": "已撤回优化授权",
        "oe.need_label": "请先上传铭牌/包装图片",
        "oe.confirm_before_query": "请确认 OE 号后再查询",
        "feedback.thanks": "感谢反馈",
        "gallery.not_found": "360 图片不存在",
        "files.not_found": "文件不存在",
        "part.not_auto": "图片内容不是汽配零件，请重新拍摄零件照片",
        "errors.unauthorized": "未授权",
        "errors.forbidden": "无权限",
        "errors.not_found": "资源不存在",
        "errors.rate_limited": "请求过于频繁，请稍后再试",
        "errors.internal": "服务内部错误",
    },
    "en-US": {
        "auth.bad_credentials": "Incorrect username or password",
        "auth.login_required": "Please sign in first",
        "auth.token_invalid": "Invalid token",
        "auth.token_type": "Invalid token type",
        "auth.user_disabled": "User not found or disabled",
        "auth.missing_device_token": "Missing device session token",
        "auth.device_expired": "Device session is invalid or expired",
        "auth.rate_limited": "Too many login attempts. Please try again later.",
        "auth.device_disabled": "Device sessions are disabled. Please sign in with an account.",
        "session.not_found": "Recognition session not found",
        "session.forbidden": "You do not have access to this recognition session",
        "upload.purpose_invalid": "purpose must be part or oe_label (legacy angle fields map to part)",
        "upload.min_one": "Please upload at least one image",
        "upload.purpose_max": "At most {count} image(s) allowed for this purpose",
        "upload.part_total_max": "At most {count} part image(s) per session",
        "upload.batch_max": "At most {count} image(s) per upload",
        "upload.done": "Uploaded {count} image(s)",
        "focus.images_missing": "Image(s) not in this session: {missing}",
        "focus.part_only": "Focus points can only be set on part images",
        "focus.saved": "Focus points saved",
        "recognize.rate_limited": "Too many recognition requests. Please try again later.",
        "recognize.need_images": "Please upload part images first",
        "recognize.done": "Recognition complete",
        "recognize.started": "Recognition task started",
        "consent.updated": "Consent updated",
        "consent.revoked": "Optimization consent revoked",
        "oe.need_label": "Please upload a nameplate / packaging photo first",
        "oe.confirm_before_query": "Please confirm the OE number before searching",
        "feedback.thanks": "Thanks for your feedback",
        "gallery.not_found": "360° image not found",
        "files.not_found": "File not found",
        "part.not_auto": "The image does not show an automotive part. Please retake a part photo.",
        "errors.unauthorized": "Unauthorized",
        "errors.forbidden": "Forbidden",
        "errors.not_found": "Resource not found",
        "errors.rate_limited": "Too many requests. Please try again later.",
        "errors.internal": "Internal server error",
    },
}

# Chinese defaults → keys (for translating AppError messages raised with zh text).
_ZH_TO_KEY = {text: key for key, text in MESSAGES["zh-CN"].items()}


def resolve_locale(accept_language: str | None) -> str:
    raw = (accept_language or "").strip()
    if not raw:
        return DEFAULT_LOCALE
    # Take first tag: "en-US,en;q=0.9" → "en-US"
    primary = raw.split(",")[0].strip().split(";")[0].strip()
    lower = primary.lower()
    if lower.startswith("en"):
        return "en-US"
    if lower.startswith("zh"):
        return "zh-CN"
    if primary in SUPPORTED:
        return primary
    return DEFAULT_LOCALE


def locale_from_request(request: Request | None) -> str:
    if request is None:
        return DEFAULT_LOCALE
    return resolve_locale(request.headers.get("accept-language"))


def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    lang = locale if locale in MESSAGES else DEFAULT_LOCALE
    template = MESSAGES[lang].get(key) or MESSAGES[DEFAULT_LOCALE].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def translate_message(message: str, locale: str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    """Translate a known Chinese default message, or return as-is."""
    if locale == DEFAULT_LOCALE or not message:
        if kwargs and "{" in message:
            try:
                return message.format(**kwargs)
            except (KeyError, ValueError):
                return message
        return message
    key = _ZH_TO_KEY.get(message)
    if key:
        return t(key, locale, **kwargs)
    return message
