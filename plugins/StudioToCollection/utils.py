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
        print(f"获取 Emby 用户 ID 失败：{e}")
        return None


def find_collection_by_name(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    studio_name: str
) -> Optional[Dict[str, Any]]:
    """按名称搜索合集（精确匹配）"""
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "SearchTerm": studio_name,
            "Limit": 10
        }
        response = requests.get(url, params=params, timeout=30)
        items = response.json().get("Items", [])
        
        for item in items:
            if item["Name"].lower() == studio_name.lower():
                return item
        return None
    except Exception as e:
        print(f"搜索合集失败：{e}")
        return None


def get_all_collections(
    emby_server: str,
    emby_api_key: str,
    user_id: str
) -> List[Dict[str, Any]]:
    """获取所有合集（Task 专用）"""
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "Limit": 1000
        }
        response = requests.get(url, params=params, timeout=30)
        return response.json().get("Items", [])
    except Exception as e:
        print(f"获取合集失败：{e}")
        return []


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


def build_provider_ids(studio: Dict[str, Any]) -> Dict[str, str]:
    """构建 ProviderIds"""
    provider_ids = {}
    
    if studio.get("id"):
        provider_ids["Stash"] = str(studio["id"])
    
    if studio.get("stash_ids"):
        stashdb_ids = [s["stash_id"] for s in studio["stash_ids"] if s.get("stash_id")]
        if stashdb_ids:
            provider_ids["StashDB"] = ",".join(stashdb_ids)
    
    return provider_ids


def build_external_id(studio: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """构建 ExternalId（第一个链接，反斜杠格式）"""
    urls = studio.get("urls", [])
    if urls:
        return {"scene_source_url": urls[0].replace('/', '\\')}
    return None


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
    
    if studio.get("rating100"):
        emby_data["CommunityRating"] = studio["rating100"] / 10
    
    provider_ids = build_provider_ids(studio)
    if provider_ids:
        emby_data["ProviderIds"] = provider_ids
    
    external_id = build_external_id(studio)
    if external_id:
        emby_data["ExternalId"] = external_id
    
    return emby_data
