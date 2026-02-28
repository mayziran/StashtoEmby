"""
Hook 处理器 - 处理工作室创建/更新事件

Create Hook: 构建数据 → 启动 worker 异步上传
Update Hook: 构建数据 → 同步上传
"""

from typing import Any, Dict, Callable

import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    find_collection_by_name,
    build_emby_data,
)
from emby_uploader import upload_metadata, download_image, upload_image

PLUGIN_ID = "StudioToCollection"


def _sync_to_emby(
    studio: Dict[str, Any],
    collection_id: str,
    emby_server: str,
    emby_api_key: str,
    dry_run: bool = False
) -> bool:
    """同步到 Emby（构建数据 + 上传）"""
    # 构建数据
    emby_data = build_emby_data(studio, collection_id)
    
    # 上传元数据
    if not upload_metadata(collection_id, emby_data, emby_server, emby_api_key, dry_run):
        return False
    
    # 上传图片
    if studio.get("image_path"):
        image_url = studio["image_path"]
        if not image_url.startswith("http"):
            image_url = f"http://localhost:9999{image_url}"
        
        image_bytes = download_image(image_url)
        if image_bytes:
            upload_image(collection_id, image_bytes, "Primary", emby_server, emby_api_key, dry_run)
            upload_image(collection_id, image_bytes, "Logo", emby_server, emby_api_key, dry_run)
    
    return True


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
        4. 启动 worker 异步上传
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

    # 构建数据
    emby_data = build_emby_data(studio, collection["Id"])

    # 启动 worker（传递 collection_id 和 user_id）
    start_worker(studio_id, studio_name, emby_data, collection["Id"], user_id, settings)

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
        3. 构建数据 + 同步上传
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
    
    # 同步上传
    if _sync_to_emby(
        studio,
        collection["Id"],
        settings["emby_server"],
        settings["emby_api_key"],
        settings["dry_run"]
    ):
        return f"工作室 {studio_name} 更新成功，已同步到 Emby 合集"
    else:
        return f"工作室 {studio_name} 更新成功，但同步到 Emby 失败"
