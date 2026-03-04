"""
工具模块 - task 和 hook 的公共函数

包含:
    - Stash API Fragment
    - Emby API 调用（搜索、获取用户）
    - 数据构建函数
"""

from typing import Any, Dict, List, Optional

import requests


# ========== Stash API Fragment ==========

STUDIO_FRAGMENT_FOR_API = """
    id
    name
    details
    image_path
    rating100
    aliases
    urls
    tags {
        name
    }
    stash_ids {
        stash_id
        endpoint
    }
"""


# ========== Emby API 公共函数 ==========

def get_emby_user_id(emby_server: str, emby_api_key: str) -> Optional[str]:
    """获取 Emby 用户 ID"""
    url = f"{emby_server}/emby/Users"
    params = {"api_key": emby_api_key}
    response = requests.get(url, params=params, timeout=30)
    users = response.json()
    return users[0]["Id"] if users else None


# ========== 数据构建函数 ==========

def build_overview(studio: Dict[str, Any]) -> str:
    """构建 Overview（别名 → 简介 → 链接）"""
    lines = []

    # 1. 别名
    aliases = studio.get('aliases', [])
    if aliases:
        lines.append("别名：" + " / ".join(aliases))

    # 2. 详情（添加"简介："前缀，参考 actorSyncEmby）
    details = studio.get('details')
    if details and details.strip():
        lines.append("简介：" + details)

    # 3. 相关链接（统一格式，参考 actorSyncEmby）
    urls = studio.get('urls', [])
    if urls:
        valid_urls = [url for url in urls if url and url.strip()]
        if valid_urls:
            lines.append("相关链接:\n" + "\n".join(valid_urls))

    return '\n'.join(lines) if lines else ""


def build_tags(studio: Dict[str, Any]) -> List[str]:
    """构建 Tags 列表"""
    tags = studio.get("tags", [])
    return [tag["name"] for tag in tags if tag.get("name") and tag["name"].strip()]


def build_provider_ids(studio: Dict[str, Any]) -> Dict[str, str]:
    """
    构建 ProviderIds（所有 Stash-Box 站点 ID + 本地 ID + 源链接）

    返回格式（固定 7 个字段，无论是否为空都写入）:
        {
            "stash": "{本地 Stash ID}",
            "stashdb": "{UUID}",
            "theporndb": "{UUID}",
            "fansdb": "{UUID}",
            "javstash": "{UUID}",
            "pmvstash": "{UUID}",
            "scene_source_url": "example.com\\path"
        }

    注意：演员和合集只写入 UUID，不需要前缀；一个站点一个 UUID
    """
    # 初始化 7 个字段为空字符串
    provider_ids = {
        "stash": "",
        "stashdb": "",
        "theporndb": "",
        "fansdb": "",
        "javstash": "",
        "pmvstash": "",
        "scene_source_url": ""
    }

    # 本地 Stash ID
    if studio.get("id"):
        provider_ids["stash"] = str(studio["id"])

    # 处理所有 stash_ids，一个站点一个 UUID
    if studio.get("stash_ids"):
        for s in studio["stash_ids"]:
            if not isinstance(s, dict):
                continue
            endpoint = s.get("endpoint", "")
            stash_id = s.get("stash_id", "")
            if not endpoint or not stash_id:
                continue

            # 从 endpoint 提取标识符
            base_url = endpoint.replace("/graphql", "")
            domain = base_url.replace("https://", "").replace("http://", "")
            identifier = domain.split('.')[0].lower()

            # 直接写入 UUID（一个站点一个 UUID）
            if identifier in provider_ids:
                provider_ids[identifier] = stash_id

    # 源链接
    urls = studio.get("urls", [])
    if urls:
        url_without_scheme = urls[0].replace("https://", "").replace("http://", "")
        provider_ids["scene_source_url"] = url_without_scheme.replace('/', '\\')

    return provider_ids


def build_emby_data(studio: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建完整的 Emby 数据

    Args:
        studio: 工作室数据

    Returns:
        Emby 数据字典
    """
    emby_data = {}

    # 概述（Overview）- 无论是否为空都写入
    overview = build_overview(studio)
    emby_data["Overview"] = overview if overview else ""

    # 标签（TagItems）- 无论是否为空都写入
    tags = build_tags(studio)
    emby_data["TagItems"] = [{"Name": tag, "Id": None} for tag in tags] if tags else []

    # 评分（CommunityRating）- 无论是否为空都写入
    emby_data["CommunityRating"] = studio["rating100"] / 10 if studio.get("rating100") else None

    # ProviderIds（所有外部 ID）- 无论是否为空都写入
    provider_ids = build_provider_ids(studio)
    emby_data["ProviderIds"] = provider_ids if provider_ids else {}

    # 添加图片路径（供 emby_uploader 下载图片使用）
    if studio.get("image_path"):
        emby_data["_image_path"] = studio["image_path"]

    return emby_data
