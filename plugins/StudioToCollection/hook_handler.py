"""
Hook 处理器 - 处理工作室创建/更新事件

职责:
    1. 获取工作室数据
    2. 获取 Emby 用户 ID
    3. 构建 emby_data
    4. Create Hook: 启动 Worker 延迟上传（不搜索合集，合集还不存在）
    5. Update Hook: 搜索合集后直接上传（合集已存在）
"""

from typing import Any, Dict, Callable, Optional, Tuple

import requests
import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    build_emby_data,
)
from emby_uploader import upload_studio_to_emby

PLUGIN_ID = "StudioToCollection"


def _prepare_sync_data(
    stash: Any,
    studio_id: int,
    settings: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    准备同步数据（Create 和 Update 共用）

    Returns:
        (data_dict, error_message)
        - 成功：返回 (数据字典，None)
        - 失败：返回 (None, 错误消息)
    """
    # 获取工作室数据
    studio = stash.find_studio(studio_id, fragment=STUDIO_FRAGMENT_FOR_API)
    if not studio:
        log.error(f"[{PLUGIN_ID}] 找不到工作室 ID: {studio_id}")
        return None, f"找不到工作室 ID: {studio_id}"

    studio_name = studio.get("name", "Unknown")

    # 获取 Emby 用户 ID
    try:
        user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 获取 Emby 用户 ID 失败：{e}")
        return None, f"无法获取 Emby 用户 ID：{studio_name}"

    if not user_id:
        log.error(f"[{PLUGIN_ID}] 无法获取 Emby 用户 ID")
        return None, "无法获取 Emby 用户 ID"

    log.info(f"[{PLUGIN_ID}] 获取到 Emby 用户 ID: {user_id}")

    # 构建 Emby 数据
    emby_data = build_emby_data(studio)

    return {
        "studio": studio,
        "studio_name": studio_name,
        "user_id": user_id,
        "emby_data": emby_data,
    }, None


def handle_create_hook(
    stash: Any,
    studio_id: int,
    settings: Dict[str, Any],
    start_worker: Callable
) -> str:
    """
    处理 Create Hook

    流程:
        1. 准备同步数据（获取工作室、用户 ID、构建 emby_data）
        2. 启动 Worker（延迟等待 Emby 扫描后搜索并上传）
    """
    # 准备共用数据
    data, error = _prepare_sync_data(stash, studio_id, settings)
    if error:
        return error

    studio_name = data["studio_name"]

    # 启动 Worker（Worker 自己搜索合集）
    log.info(f"[{PLUGIN_ID}] [Create] 启动 Worker: {studio_name}")
    start_worker(
        studio_id=studio_id,
        studio_name=studio_name,
        studio=data["studio"],
        emby_data=data["emby_data"],
        user_id=data["user_id"],
        settings=settings,
        server_conn=settings.get("server_connection", {}),
        stash_api_key=settings.get("stash_api_key", "")
    )

    return f"工作室 {studio_name} 创建成功，已启动异步同步任务"


def handle_update_hook(
    stash: Any,
    studio_id: int,
    settings: Dict[str, Any]
) -> str:
    """
    处理 Update Hook

    流程:
        1. 准备同步数据（获取工作室、用户 ID、构建 emby_data）
        2. 搜索合集（Update 时合集已存在）
        3. 填充 collection_id 并上传
    """
    # 准备共用数据
    data, error = _prepare_sync_data(stash, studio_id, settings)
    if error:
        return error

    studio_name = data["studio_name"]

    # 搜索合集（Update 时合集应该已存在）
    collection = _find_collection_by_name(
        settings["emby_server"],
        settings["emby_api_key"],
        data["user_id"],
        studio_name
    )

    if not collection:
        log.error(f"[{PLUGIN_ID}] [Update] 未找到合集：{studio_name}")
        return f"未找到合集：{studio_name}，跳过同步"

    # 上传到 Emby
    log.info(f"[{PLUGIN_ID}] [Update] 同步到 Emby: {studio_name}")
    if upload_studio_to_emby(
        emby_data=data["emby_data"],
        collection_id=collection["Id"],
        emby_server=settings["emby_server"],
        emby_api_key=settings["emby_api_key"],
        user_id=data["user_id"],
        server_conn=settings.get("server_connection", {}),
        stash_api_key=settings.get("stash_api_key", "")
    ):
        return f"工作室 {studio_name} 更新成功，已同步到 Emby 合集"
    else:
        return f"工作室 {studio_name} 更新成功，但同步到 Emby 失败"


def _find_collection_by_name(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    studio_name: str
) -> Optional[Dict[str, Any]]:
    """
    按名称搜索合集（精确匹配）

    Args:
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        user_id: Emby 用户 ID
        studio_name: 工作室名称

    Returns:
        合集信息，未找到返回 None
    """
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "Recursive": "true",
            "SearchTerm": studio_name,
            "Limit": "20"
        }
        response = requests.get(url, params=params, timeout=30)
        items = response.json().get("Items", [])

        # 本地精确匹配（因为 SearchTerm 是模糊搜索）
        for item in items:
            item_name = item.get("Name", "")
            if item_name.lower() == studio_name.lower():
                log.info(f"[{PLUGIN_ID}] ✓ 找到合集：{item_name}")
                return item

        log.info(f"[{PLUGIN_ID}] ✗ 未找到合集：{studio_name}")
        return None
    except Exception as e:
        log.error(f"搜索合集失败：{e}")
        return None
