from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_preference_text(text: str) -> str:
    normalized = normalize_text(text)
    lower = normalized.lower()

    language_patterns = (
        r"偏好使用中文沟通",
        r"偏好中文沟通",
        r"请用中文",
        r"请用中文回答",
        r"用中文回答",
        r"使用中文沟通",
        r"中文沟通",
        r"prefers? communication in chinese",
        r"prefers? chinese communication",
        r"prefer[s]?.*chinese",
        r"communicat\w*.*chinese",
    )
    style_patterns = (
        r"偏好简洁直接的总结",
        r"简洁直接的总结",
        r"喜欢简洁直接的总结",
        r"likes? concise,? direct summaries",
        r"prefers? concise,? direct summaries",
        r"concise,? direct summaries",
    )

    if any(re.search(pattern, lower, re.I) for pattern in language_patterns):
        return "偏好使用中文沟通"
    if any(re.search(pattern, lower, re.I) for pattern in style_patterns):
        return "偏好简洁直接的总结"
    return normalized
