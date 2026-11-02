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

# Only these three categories are supported for recognition / catalog / WhatsApp.
SUPPORTED_CATEGORY_IDS = ("compressor", "condenser", "radiator")
SUPPORTED_CATEGORY_CODES = ("COMPRESSOR", "CONDENSER", "RADIATOR")

CATEGORY_CN = {
    "compressor": "压缩机",
    "condenser": "冷凝器",
    "radiator": "散热器",
}

CATEGORY_EN = {
    "compressor": "Compressor",
    "condenser": "Condenser",
    "radiator": "Radiator",
    "COMPRESSOR": "Compressor",
    "CONDENSER": "Condenser",
    "RADIATOR": "Radiator",
    "压缩机": "Compressor",
    "冷凝器": "Condenser",
    "散热器": "Radiator",
    "空调压缩机": "Compressor",
    "水箱": "Radiator",
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
        "whatsapp:read",
        "catalog:read",
        "catalog:write",
    },
    ROLE_OPERATOR: {
        "session:read",
        "session:retry",
        "mapping:read",
        "mapping:write",
        "prompt:read",
        "stats:read",
        "audit:read",
        "whatsapp:read",
        "catalog:read",
        "catalog:write",
    },
    ROLE_VIEWER: {
        "session:read",
        "mapping:read",
        "prompt:read",
        "stats:read",
        "whatsapp:read",
        "catalog:read",
    },
}

DEFAULT_VISION_PROMPT = (
    "请识别图片中的汽配零件。只返回一个 JSON 对象，"
    "字段固定为 is_auto_part、part_name、confidence、reason、candidates。"
    "本系统目前仅支持三类零件的后续匹配：压缩机、冷凝器、散热器。"
    "is_auto_part 为布尔值：true 表示图片主体是汽车零配件；"
    "false 表示非汽配内容（如人物、风景、手机、食品、整车外观、文档截图等）。"
    "若是汽配但不是压缩机/冷凝器/散热器（例如风扇、蒸发器、中冷器），"
    "仍将 is_auto_part 设为 true，part_name 填写实际零件中文名，便于系统判定为不支持品类。"
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

DEFAULT_WHATSAPP_CHAT_PROMPT = (
    "You are the Reach Auto Parts WhatsApp assistant. "
    "Always reply in English. Be concise and professional.\n"
    "Your only job is to identify the correct Reach SKU (material_code) from the "
    "customer's photo, OE/part number, vehicle, category, or technical specs.\n"
    "You only support Compressor, Condenser, and Radiator. "
    "If asked about other part types (fan, evaporator, intercooler, etc.), "
    "say those are not supported yet and offer help for the three above.\n"
    "Use the provided tools and photo-analysis JSON only. "
    "Never invent SKUs, OE numbers, fitment, or technical specs.\n"
    "Do not mention price, stock, or availability. Do not add Price/Stock columns, "
    "and do not say 'not listed', 'in stock', 'available', or similar. "
    "If asked about price or availability, say you can only help identify the SKU "
    "and suggest contacting Reach sales for commercial details.\n"
    "If the request is ambiguous, ask for brand/model/year, OE/part number, "
    "category (compressor/condenser/radiator), or tech specs before guessing.\n"
    "When the customer gives technical parameters, confirm the category first, then call "
    "search_products_by_specs to narrow SKUs.\n"
    "When listing matches, keep it short: SKU, category, OE/ref if known, "
    "and a brief fitment sample when useful. Cap at a few options and ask what would "
    "narrow further if needed.\n"
    "If there are no matches, say so and ask for the next useful clue "
    "(vehicle, OE, or a clearer photo). "
    "Never invent products beyond the analysis JSON or tool results."
)

WHATSAPP_UNSUPPORTED_MEDIA_REPLY = (
    "Sorry, I can only handle text messages and part photos right now. "
    "Please type your part number, OE number, or vehicle details, "
    "or send a clear photo of the part."
)

WHATSAPP_RATE_LIMIT_REPLY = (
    "You are sending messages too quickly. Please wait a moment and try again."
)

WHATSAPP_ERROR_FALLBACK_REPLY = (
    "Sorry, I ran into a temporary issue while looking that up. "
    "Please try again in a moment."
)

WHATSAPP_IMAGE_RECEIVED_REPLY = (
    "Got your photo. I will analyze it shortly — you can send a few more angles "
    "of the same part within the next few seconds."
)

WHATSAPP_IMAGE_NOT_PART_REPLY = (
    "I could not identify an automotive part in that photo. "
    "Please send a clearer picture of the part, or type the OE/part number."
)

WHATSAPP_UNSUPPORTED_CATEGORY_REPLY = (
    "I recognized an automotive part, but Reach currently only supports "
    "Compressor, Condenser, and Radiator. "
    "Please send a photo of one of those parts, or type an OE/part number "
    "for Compressor / Condenser / Radiator."
)

WHATSAPP_IMAGE_TOO_MANY_REPLY = (
    "You already sent the maximum number of photos for this analysis. "
    "Please wait for the current results, then send a new photo if needed."
)

WHATSAPP_IMAGE_FAILED_REPLY = (
    "Sorry, I could not finish analyzing that photo. "
    "Please try again in a moment, or type the OE/part number instead."
)

WHATSAPP_IMAGE_UNAVAILABLE_REPLY = (
    "Photo recognition is temporarily unavailable. "
    "Please try again shortly, or type your OE/part number or vehicle details."
)

WHATSAPP_WELCOME_BODY = (
    "Hi, I'm RAI, Reach's AI assistant for auto parts.\n"
    "I currently support Compressor, Condenser, and Radiator only.\n"
    "I can help you three ways:\n"
    "- Send a photo of the part and I'll identify it\n"
    '- Type an OE / part number, e.g. "17117533485"\n'
    '- Tell me the vehicle, e.g. "radiator for 2018 Toyota Camry"\n'
    "Tap a button below to get started."
)

WHATSAPP_WELCOME_BUTTONS = [
    ("guide_photo", "Send a photo"),
    ("guide_oe", "Find by OE"),
    ("guide_vehicle", "Search by vehicle"),
]

WHATSAPP_GUIDE_REPLIES = {
    "guide_photo": (
        "Please send one or more clear photos of the part (up to 8). "
        "Multiple angles help."
    ),
    "guide_oe": (
        "Please type the OE or part number printed on the part or box."
    ),
    "guide_vehicle": (
        "Please tell me the vehicle brand, model, and year, plus the part you need "
        "(radiator, condenser, or compressor)."
    ),
}
