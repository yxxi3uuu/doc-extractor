# -*- coding: utf-8 -*-
"""
設定管理：讀寫 config.json，提供 API 給前端用。
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "filter_keywords": {
        "暑期寒假工讀": [
            "暑期工讀", "暑期打工", "暑假打工", "工讀生", "暑期實習",
            "寒假打工", "寒假工讀", "寒期打工",
        ],
        "房仲房地產": [
            "房仲", "房地產", "不動產", "建案", "廠辦", "售屋", "租屋",
            "戴德梁行", "仲量聯行", "預售屋", "房價",
        ],
        "競選政見": [
            "競選", "政見", "候選人", "選舉", "造勢", "投票",
            "選戰", "參選", "連任", "施政", "政見發表",
        ],
        "軟性離題新聞": [
            "緝毒犬", "寵物", "狗狗", "明星", "八卦",
            "離婚", "臉書帳號", "演唱會",
        ],
        "銀行信用卡金控": [
            "信用卡", "卡友", "刷卡回饋", "辦卡", "紅利點數",
            "分期0利率", "金控", "獲利王", "金控榜單",
        ],
    },
    "filter_settings": {
        "銀行信用卡金控_need_two": True,
        "競選政見_enabled": True,
    },
}


def load_config() -> dict:
    """載入設定檔，不存在時建立預設"""
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return DEFAULT_CONFIG


def save_config(config: dict) -> None:
    """儲存設定檔"""
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_filter_keywords() -> dict[str, list[str]]:
    """取得所有過濾類別和關鍵字"""
    config = load_config()
    return config.get("filter_keywords", {})


def add_keyword(category: str, keyword: str) -> dict:
    """新增關鍵字到指定類別"""
    config = load_config()
    keywords = config.setdefault("filter_keywords", {})
    if category not in keywords:
        keywords[category] = []
    if keyword not in keywords[category]:
        keywords[category].append(keyword)
    save_config(config)
    return config["filter_keywords"]


def remove_keyword(category: str, keyword: str) -> dict:
    """從指定類別移除關鍵字"""
    config = load_config()
    keywords = config.get("filter_keywords", {})
    if category in keywords and keyword in keywords[category]:
        keywords[category].remove(keyword)
    save_config(config)
    return config["filter_keywords"]


def add_category(category: str) -> dict:
    """新增一個過濾類別"""
    config = load_config()
    keywords = config.setdefault("filter_keywords", {})
    if category not in keywords:
        keywords[category] = []
    save_config(config)
    return config["filter_keywords"]


def remove_category(category: str) -> dict:
    """刪除一個過濾類別"""
    config = load_config()
    keywords = config.get("filter_keywords", {})
    if category in keywords:
        del keywords[category]
    save_config(config)
    return config["filter_keywords"]
