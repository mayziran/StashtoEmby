"""
Hook 处理器 - 处理工作室创建/更新事件

职责:
    1. 获取工作室数据
    2. 搜索合集
    3. 构建 emby_data
    4. Create Hook: 传递原始数据给 worker，延迟后上传
    5. Update Hook: 直接调用 emby_uploader 上传
"""

from typing import Any, Dict, Callable

import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    find_collection_by_name,
    build_emby_data,
)
from emby_uploader import upload_studio_to_emby

PLUGIN_ID = "StudioToCollection"


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
        return f"找不到工作室 ID: {studio_id}"

    studio_name = studio.get("name", "Unknown")

    # 搜索合集
    user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    if not user_id:
        return f"无法获取 Emby 用户 ID: {studio_name}"

    collection = find_collection_by_name(
        settings["emby_server"],
        settings["emby_api_key"],
        user_id,
        studio_name
    )

    if not collection:
        return f"未找到合集：{studio_name}，跳过同步"

    # 构建 Emby 数据
    emby_data = build_emby_data(studio, collection["Id"])

    # 构建 Stash URL
    server_conn = settings.get("server_connection", {})
    scheme = server_conn.get("Scheme", "http")
    host = server_conn.get("Host", "localhost")
    port = server_conn.get("Port", "9999")
    stash_url = f"{scheme}://{host}:{port}"

    # 启动 worker（传递原始 studio 数据 + emby_data，worker 负责延迟后调用 emby_uploader 上传）
    start_worker(
        studio_id=studio_id,
        studio_name=studio_name,
        studio=studio,  # 传递原始工作室数据
        emby_data=emby_data,  # 传递已构建好的 emby_data
        collection_id=collection["Id"],
        user_id=user_id,
        settings=settings,
        stash_url=stash_url
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
        return f"找不到工作室 ID: {studio_id}"

    studio_name = studio.get("name", "Unknown")

    # 搜索合集
    user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    if not user_id:
        return f"无法获取 Emby 用户 ID: {studio_name}"

    collection = find_collection_by_name(
        settings["emby_server"],
        settings["emby_api_key"],
        user_id,
        studio_name
    )

    if not collection:
        return f"未找到合集：{studio_name}，跳过同步"

    # 构建 Emby 数据
    emby_data = build_emby_data(studio, collection["Id"])

    # 直接调用 emby_uploader 上传
    if upload_studio_to_emby(
        studio=studio,
        collection_id=collection["Id"],
        emby_server=settings["emby_server"],
        emby_api_key=settings["emby_api_key"],
        emby_data=emby_data,
        dry_run=settings["dry_run"],
        stash_url=""
    ):
        return f"工作室 {studio_name} 更新成功，已同步到 Emby 合集"
    else:
        return f"工作室 {studio_name} 更新成功，但同步到 Emby 失败"
