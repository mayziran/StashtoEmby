"""
Task 处理器 - 批量同步所有工作室

流程:
    1. 获取所有工作室
    2. 获取所有 Emby 合集（建立名称映射）
    3. 遍历工作室，名称精确匹配
    4. 匹配成功则构建数据并调用 emby_uploader 上传
    5. 输出统计信息
"""

from typing import Any, Dict, List

import requests
import stashapi.log as log
from utils import (
    STUDIO_FRAGMENT_FOR_API,
    get_emby_user_id,
    build_emby_data,
)
from emby_uploader import upload_studio_to_emby

PLUGIN_ID = "StudioToCollection"


def get_all_collections(
    emby_server: str,
    emby_api_key: str,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    获取所有合集（Task 专用）
    
    参考 emby_boxset_api.md：
    - 必须添加 Recursive=true 才能获取所有媒体库中的合集
    - 必须添加 StartIndex=0 才能正确分页
    
    只在 task_handler 中使用，不放在 utils.py 中
    """
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "Recursive": "true",      # 关键：递归获取所有媒体库
            "StartIndex": "0",        # 起始索引
            "Limit": "1000"           # 最多获取 1000 个
        }
        response = requests.get(url, params=params, timeout=30)
        return response.json().get("Items", [])
    except Exception as e:
        log.error(f"获取合集失败：{e}")
        return []


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
    try:
        log.info(f"[{PLUGIN_ID}] Task 模式启动")
        task_log_func("开始同步工作室", progress=0.0)

        # 1. 获取所有工作室（使用 find_studios 分页获取）
        try:
            all_studios = []
            page = 1
            per_page = 1000
            
            while True:
                page_studios = stash.find_studios(
                    f=None,
                    filter={"page": page, "per_page": per_page},
                    fragment=STUDIO_FRAGMENT_FOR_API
                )
                
                if not page_studios:
                    break
                    
                all_studios.extend(page_studios)
                
                if len(page_studios) < per_page:
                    break
                    
                page += 1
            
            total_count = len(all_studios)
            log.info(f"[{PLUGIN_ID}] 获取到 {total_count} 个工作室")
        except Exception as e:
            log.error(f"[{PLUGIN_ID}] 获取工作室失败：{e}")
            return f"获取工作室失败：{e}"

        if total_count == 0:
            msg = "没有工作室需要同步"
            task_log_func(msg, progress=1.0)
            return msg

        # 2. 获取 Emby 用户 ID
        log.info(f"[{PLUGIN_ID}] 正在获取 Emby 用户 ID...")
        user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
        if not user_id:
            log.error(f"[{PLUGIN_ID}] 无法获取 Emby 用户 ID")
            return "无法获取 Emby 用户 ID"
        log.info(f"[{PLUGIN_ID}] 获取到 Emby 用户 ID: {user_id}")

        # 3. 获取所有合集，建立名称映射
        log.info(f"[{PLUGIN_ID}] 正在获取 Emby 合集列表...")
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

            # 构建 Emby 数据
            emby_data = build_emby_data(studio, collection_id)

            # 调用 emby_uploader 上传（参考 actorSyncEmby）
            if upload_studio_to_emby(
                emby_data=emby_data,
                collection_id=collection_id,
                emby_server=settings["emby_server"],
                emby_api_key=settings["emby_api_key"],
                user_id=user_id,
                server_conn=settings.get("server_connection", {}),
                stash_api_key=settings.get("stash_api_key", ""),
                dry_run=settings["dry_run"]
            ):
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
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] Task 执行异常：{e}")
        raise
