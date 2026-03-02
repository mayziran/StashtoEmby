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


def build_provider_ids(studio: Dict[str, Any]) -> Dict[str, str]:
    """
    构建 ProviderIds（支持所有 5 个 Stash-Box 实例 + 源链接）
    
    支持的实例:
        - StashDB
        - ThePornDB
        - FansDB
        - JAVStash
        - PMVStash
        - scene_source_url (源链接)
    """
    provider_ids = {}

    if studio.get("id"):
        provider_ids["Stash"] = str(studio["id"])

    # 处理所有 stash_ids，按 endpoint 分类
    if studio.get("stash_ids"):
        stash_ids_map = {}  # endpoint -> [stash_id, ...]
        
        for s in studio["stash_ids"]:
            if not isinstance(s, dict):
                continue
            endpoint = s.get("endpoint", "")
            stash_id = s.get("stash_id", "")
            if not endpoint or not stash_id:
                continue
            
            # 从 endpoint 提取标识符
            # https://stashdb.org/graphql -> stashdb
            # https://theporndb.net/graphql -> theporndb
            # https://fansdb.cc/graphql -> fansdb
            # https://javstash.org/graphql -> javstash
            # https://pmvstash.org/graphql -> pmvstash
            base_url = endpoint.replace("/graphql", "")
            domain = base_url.replace("https://", "").replace("http://", "")
            identifier = domain.split('.')[0].lower()
            
            if identifier not in stash_ids_map:
                stash_ids_map[identifier] = []
            stash_ids_map[identifier].append(stash_id)
        
        # 映射到 Emby ProviderIds 键名
        key_mapping = {
            "stashdb": "StashDB",
            "theporndb": "ThePornDB",
            "fansdb": "FansDB",
            "javstash": "JAVStash",
            "pmvstash": "PMVStash",
        }
        
        for identifier, ids in stash_ids_map.items():
            if identifier in key_mapping and ids:
                provider_ids[key_mapping[identifier]] = ",".join(ids)

    # 源链接：写入 scene_source_url（去掉协议前缀，反斜杠替代正斜杠）
    urls = studio.get("urls", [])
    if urls:
        url_without_scheme = urls[0].replace("https://", "").replace("http://", "")
        provider_ids["scene_source_url"] = url_without_scheme.replace('/', '\\')

    return provider_ids


def build_external_id(studio: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    构建 ExternalId（用于 Stash-Box ID 跳转）
    
    返回格式:
        {
            "stashdb": "studios\\{uuid}",
            "theporndb": "studios\\{uuid}",
            "fansdb": "studios\\{uuid}",
            ...
        }
    
    注意：源链接已移至 ProviderIds.scene_source_url
    """
    external_ids = {}

    # 处理所有 stash_ids，写入 studios\{uuid} 格式
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

            # 写入 studios\{uuid} 格式（反斜杠）
            external_ids[identifier] = f"studios\\{stash_id}"

    return external_ids if external_ids else None


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

    # 添加图片路径（供 emby_uploader 下载图片使用）
    if studio.get("image_path"):
        emby_data["_image_path"] = studio["image_path"]

    return emby_data
