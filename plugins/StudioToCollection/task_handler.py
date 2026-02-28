"""
Task 处理器 - 批量同步所有工作室

流程:
    1. 获取所有工作室
    2. 获取所有 Emby 合集（建立名称映射）
    3. 遍历工作室，名称精确匹配
    4. 匹配成功则构建数据并上传
    5. 输出统计信息
"""

from typing import Any, Dict

import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    get_all_collections,
    build_emby_data,
)
from emby_uploader import upload_metadata, download_image, upload_image

PLUGIN_ID = "StudioToCollection"


def _sync_studio(
    studio: Dict[str, Any],
    collection_id: str,
    settings: Dict[str, Any]
) -> bool:
    """同步单个工作室（构建数据 + 上传）"""
    try:
        # 构建数据
        emby_data = build_emby_data(studio, collection_id)
        
        # 上传元数据
        if not upload_metadata(
            collection_id,
            emby_data,
            settings["emby_server"],
            settings["emby_api_key"],
            settings["dry_run"]
        ):
            return False
        
        # 上传图片
        if studio.get("image_path"):
            image_url = studio["image_path"]
            if not image_url.startswith("http"):
                image_url = f"http://localhost:9999{image_url}"
            
            image_bytes = download_image(image_url)
            if image_bytes:
                upload_image(collection_id, image_bytes, "Primary",
                           settings["emby_server"], settings["emby_api_key"], settings["dry_run"])
                upload_image(collection_id, image_bytes, "Logo",
                           settings["emby_server"], settings["emby_api_key"], settings["dry_run"])
        
        return True
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 同步工作室 {studio.get('name')} 失败：{e}")
        return False


def handle_task(stash: Any, settings: Dict[str, Any], task_log_func: Any) -> str:
    """
    处理 Task 任务
    
    Args:
        stash: Stash 连接
        settings: 配置参数
        task_log_func: Task 日志函数
    
    Returns:
        处理结果消息
    """
    log.info(f"[{PLUGIN_ID}] Task 模式启动")
    task_log_func("开始同步工作室", progress=0.0)
    
    # 1. 获取所有工作室
    try:
        all_studios = stash.all_studios(fragment=STUDIO_FRAGMENT_FOR_API)
        total_count = len(all_studios)
        log.info(f"[{PLUGIN_ID}] 获取到 {total_count} 个工作室")
    except Exception as e:
        return f"获取工作室失败：{e}"
    
    if total_count == 0:
        msg = "没有工作室需要同步"
        task_log_func(msg, progress=1.0)
        return msg
    
    # 2. 获取 Emby 用户 ID
    user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
    if not user_id:
        return "无法获取 Emby 用户 ID"
    
    # 3. 获取所有合集，建立名称映射
    collections = get_all_collections(settings["emby_server"], settings["emby_api_key"], user_id)
    collection_map = {c["Name"].lower(): c["Id"] for c in collections if c.get("Name")}
    log.info(f"[{PLUGIN_ID}] 获取到 {len(collection_map)} 个 Emby 合集")
    
    # 4. 统计
    success_list = []
    skip_count = 0
    error_count = 0
    
    # 5. 遍历工作室
    for i, studio in enumerate(all_studios):
        studio_name = studio.get("name", "")
        progress = (i + 1) / total_count
        
        # 名称精确匹配
        collection_id = collection_map.get(studio_name.lower())
        if not collection_id:
            skip_count += 1
            continue
        
        # 同步
        if _sync_studio(studio, collection_id, settings):
            success_list.append(studio_name)
            log.info(f"[{PLUGIN_ID}] ✓ {studio_name}")
        else:
            error_count += 1
            log.error(f"[{PLUGIN_ID}] ✗ {studio_name} - 同步失败")
    
    # 6. 输出统计
    success_count = len(success_list)
    msg = f"完成：成功 {success_count} 个，跳过 {skip_count} 个，失败 {error_count} 个"
    
    if success_list:
        msg += "\n\n成功列表:\n" + "\n".join(success_list)
    
    task_log_func(msg, progress=1.0)
    return msg
