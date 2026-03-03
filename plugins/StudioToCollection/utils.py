"""
工具模块 - task 和 hook 的公共函数

包含:
    - Stash API Fragment
    - Emby API 调用（搜索、获取用户）
    - 数据构建函数
"""

import sys
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
    try:
        url = f"{emby_server}/emby/Users"
        params = {"api_key": emby_api_key}
        response = requests.get(url, params=params, timeout=30)
        users = response.json()
        return users[0]["Id"] if users else None
    except Exception as e:
        sys.stderr.write(f"获取 Emby 用户 ID 失败：{e}\n")
        return None


# ========== 数据构建函数 ==========

def build_overview(studio: Dict[str, Any]) -> str:
    """构建 Overview（别名 → 简介 → 链接）"""
    lines = []

    aliases = studio.get('aliases', [])
    if aliases:
        lines.append("别名：" + " / ".join(aliases))

    if studio.get('details'):
        lines.append(studio['details'])

    urls = studio.get('urls', [])
    if urls:
        lines.append("\n相关链接:\n" + "\n".join(urls))

    return '\n'.join(lines)


def build_tags(studio: Dict[str, Any]) -> List[str]:
    """构建 Tags 列表"""
    tags = studio.get("tags", [])
    return [tag["name"] for tag in tags if tag.get("name")]


def build_provider_ids(studio: Dict[str, Any]) -> Dict[str, str]:
    """
    构建 ProviderIds（所有 Stash-Box 站点 ID + 本地 ID + 源链接）

    返回格式:
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
    provider_ids = {}

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
            provider_ids[identifier] = stash_id

    # 源链接：写入 scene_source_url（去掉协议前缀，反斜杠替代正斜杠）
    urls = studio.get("urls", [])
    if urls:
        url_without_scheme = urls[0].replace("https://", "").replace("http://", "")
        provider_ids["scene_source_url"] = url_without_scheme.replace('/', '\\')

    return provider_ids


def build_emby_data(studio: Dict[str, Any], collection_id: str) -> Dict[str, Any]:
    """
    构建完整的 Emby 数据

    Args:
        studio: 工作室数据
        collection_id: 合集 ID

    Returns:
        Emby 数据字典
    """
    emby_data = {"Id": collection_id}

    overview = build_overview(studio)
    if overview:
        emby_data["Overview"] = overview

    # 标签（Tags）- 使用 TagItems 格式（参考 actorSyncEmby）
    tags = build_tags(studio)
    if tags:
        emby_data["TagItems"] = [{"Name": tag, "Id": None} for tag in tags]

    if studio.get("rating100"):
        emby_data["CommunityRating"] = studio["rating100"] / 10

    # ProviderIds（所有外部 ID）- 只返回 Stash 相关的 ID
    provider_ids = build_provider_ids(studio)
    if provider_ids:
        emby_data["ProviderIds"] = provider_ids

    # 添加图片路径（供 emby_uploader 下载图片使用）
    if studio.get("image_path"):
        emby_data["_image_path"] = studio["image_path"]

    return emby_data
