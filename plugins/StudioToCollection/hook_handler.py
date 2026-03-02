"""
Hook 处理器 - 处理工作室创建/更新事件

职责:
    1. 获取工作室数据
    2. 搜索合集
    3. 构建 emby_data
    4. Create Hook: 传递原始数据给 worker，延迟后上传
    5. Update Hook: 直接调用 emby_uploader 上传
"""

from typing import Any, Dict, Callable, Optional

import requests
import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    build_emby_data,
)
from emby_uploader import upload_studio_to_emby

PLUGIN_ID = "StudioToCollection"


def find_collection_by_name(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    studio_name: str
) -> Optional[Dict[str, Any]]:
    """
    按名称搜索合集（精确匹配）

    只在 hook_handler 中使用，不放在 utils.py 中
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


def handle_create_hook(
    stash: Any,
    studio_id: int,
    settings: Dict[str, Any],
    start_worker: Callable
) -> str:
    """
    处理 Create Hook

    流程:
        1. 获取工作室数据
        2. 搜索合集
        3. 构建 emby_data
        4. 启动 worker（传递原始 studio 数据 + emby_data），延迟后调用 emby_uploader 上传
    """
    # 获取工作室数据
    studio = stash.find_studio(studio_id, fragment=STUDIO_FRAGMENT_FOR_API)
    if not studio:
        log.error(f"[{PLUGIN_ID}] [Create] 找不到工作室 ID: {studio_id}")
        return f"找不到工作室 ID: {studio_id}"

    studio_name = studio.get("name", "Unknown")

    # 获取 Emby 用户 ID
    user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    if not user_id:
        log.error(f"[{PLUGIN_ID}] [Create] 无法获取 Emby 用户 ID: {studio_name}")
        return f"无法获取 Emby 用户 ID: {studio_name}"

    # 搜索合集
    collection = find_collection_by_name(
        settings["emby_server"],
        settings["emby_api_key"],
        user_id,
        studio_name
    )

    if not collection:
        log.error(f"[{PLUGIN_ID}] [Create] 未找到合集：{studio_name}")
        return f"未找到合集：{studio_name}，跳过同步"

    # 构建 Emby 数据
    emby_data = build_emby_data(studio, collection["Id"])

    # 启动 worker 异步执行
    log.info(f"[{PLUGIN_ID}] [Create] 启动 Worker: {studio_name}")
    start_worker(
        studio_id=studio_id,
        studio_name=studio_name,
        studio=studio,
        emby_data=emby_data,
        collection_id=collection["Id"],
        user_id=user_id,
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
        1. 获取工作室数据
        2. 搜索合集
        3. 构建数据
        4. 直接调用 emby_uploader 上传
    """
    # 获取工作室数据
    studio = stash.find_studio(studio_id, fragment=STUDIO_FRAGMENT_FOR_API)
    if not studio:
        log.error(f"[{PLUGIN_ID}] [Update] 找不到工作室 ID: {studio_id}")
        return f"找不到工作室 ID: {studio_id}"

    studio_name = studio.get("name", "Unknown")

    # 获取 Emby 用户 ID
    user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    if not user_id:
        log.error(f"[{PLUGIN_ID}] [Update] 无法获取 Emby 用户 ID: {studio_name}")
        return f"无法获取 Emby 用户 ID: {studio_name}"

    # 搜索合集
    collection = find_collection_by_name(
        settings["emby_server"],
        settings["emby_api_key"],
        user_id,
        studio_name
    )

    if not collection:
        log.error(f"[{PLUGIN_ID}] [Update] 未找到合集：{studio_name}")
        return f"未找到合集：{studio_name}，跳过同步"

    # 构建 Emby 数据
    emby_data = build_emby_data(studio, collection["Id"])

    # 上传到 Emby
    log.info(f"[{PLUGIN_ID}] [Update] 同步到 Emby: {studio_name}")
    if upload_studio_to_emby(
        emby_data=emby_data,
        collection_id=collection["Id"],
        emby_server=settings["emby_server"],
        emby_api_key=settings["emby_api_key"],
        user_id=user_id,
        server_conn=settings.get("server_connection", {}),
        stash_api_key=settings.get("stash_api_key", ""),
        dry_run=settings["dry_run"]
    ):
        return f"工作室 {studio_name} 更新成功，已同步到 Emby 合集"
    else:
        return f"工作室 {studio_name} 更新成功，但同步到 Emby 失败"
