"""Shared constants and protected resource lists."""

PROTECTED_MYSQL_DATABASES = {
    "ReachMDM_LMR",
    "Reach_CN_Catalogue",
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/avif",
}

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}

# Unified part-image purpose for multi-angle uploads (1–8 images).
PART_IMAGE_PURPOSE = "part"
# Legacy angle slots remain readable for old sessions.
LEGACY_PART_PURPOSES = {
    "part_overall",
    "part_connector",
    "part_label",
    "part_other",
}
PART_PURPOSES = {PART_IMAGE_PURPOSE, *LEGACY_PART_PURPOSES}
OE_LABEL_PURPOSE = "oe_label"

CATEGORY_CN = {
    "compressor": "压缩机",
    "condenser": "冷凝器",
    "fan": "风扇",
    "radiator": "散热器",
}

ROLE_SUPERADMIN = "superadmin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

PERMISSIONS = {
    ROLE_SUPERADMIN: {
        "session:read",
        "session:retry",
        "mapping:read",
        "mapping:write",
        "prompt:read",
        "prompt:write",
        "user:read",
        "user:write",
        "audit:read",
        "stats:read",
        "system:write",
    },
    ROLE_OPERATOR: {
        "session:read",
        "session:retry",
        "mapping:read",
        "mapping:write",
        "prompt:read",
        "stats:read",
        "audit:read",
    },
    ROLE_VIEWER: {
        "session:read",
        "mapping:read",
        "prompt:read",
        "stats:read",
    },
}

DEFAULT_VISION_PROMPT = (
    "请识别图片中的汽配零件。只返回一个 JSON 对象，"
    "字段固定为 is_auto_part、part_name、confidence、reason、candidates。"
    "is_auto_part 为布尔值：true 表示图片主体是汽车零配件（如散热器、冷凝器、压缩机等）；"
    "false 表示非汽配内容（如人物、风景、手机、食品、整车外观、文档截图等）。"
    "若 is_auto_part 为 false，part_name 填识别到的物体名称，candidates 返回空数组，confidence 可较低。"
    "part_name 是最可能的零件中文名称，confidence 是 0 到 1 之间的小数，保留两位小数，"
    "reason 是一句简短判断依据，candidates 是最多 3 个候选对象数组，"
    "每个候选含 name 与 confidence。"
    '示例：{"is_auto_part":true,"part_name":"散热器","confidence":0.92,"reason":"铝制散热芯和塑料水室",'
    '"candidates":[{"name":"散热器","confidence":0.92},{"name":"冷凝器","confidence":0.41}]}'
    '非汽配示例：{"is_auto_part":false,"part_name":"手机","confidence":0.88,"reason":"主体为手机而非零件","candidates":[]}'
)

DEFAULT_OE_OCR_PROMPT = (
    "请识别图片中的汽配 OE/原厂零件号。只返回一个 JSON 对象，"
    "字段固定为 oe_numbers、confidence、reason。"
    "oe_numbers 是字符串数组，最多 5 个候选零件号；confidence 是 0 到 1 的小数；"
    "reason 是简短依据。若无法识别，oe_numbers 返回空数组。"
    '示例：{"oe_numbers":["17117533485"],"confidence":0.88,"reason":"铭牌清晰可见"}'
)
