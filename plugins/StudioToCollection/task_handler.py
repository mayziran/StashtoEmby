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
    user_id: str,
    parent_ids: str = ""
) -> List[Dict[str, Any]]:
    """
    获取所有合集（Task 专用）

    参考 emby_boxset_api.md：
    - 必须添加 Recursive=true 才能获取所有媒体库中的合集
    - 必须添加 StartIndex=0 才能正确分页
    - 如果指定 parent_ids，则只在指定的媒体库内搜索（支持多个，逗号分隔）

    只在 task_handler 中使用，不放在 utils.py 中
    """
    all_collections = []
    
    try:
        # 解析 parent_ids（支持逗号分隔的多个 ID）
        if parent_ids:
            id_list = [id.strip() for id in parent_ids.split(",") if id.strip()]
        else:
            id_list = []
        
        # 如果指定了多个 parent_ids，分别查询每个媒体库并合并结果
        if id_list:
            log.info(f"[{PLUGIN_ID}] 限定在媒体库 ID 列表：{id_list} 内搜索合集")
            
            seen_ids = set()  # 用于去重
            
            for pid in id_list:
                try:
                    url = f"{emby_server}/emby/Users/{user_id}/Items"
                    params = {
                        "api_key": emby_api_key,
                        "IncludeItemTypes": "BoxSet",
                        "Recursive": "true",
                        "StartIndex": "0",
                        "Limit": "2000",  # 每个媒体库最多获取 2000 个
                        "ParentId": pid  # 每次查询一个媒体库
                    }
                    response = requests.get(url, params=params, timeout=30)
                    items = response.json().get("Items", [])
                    
                    # 去重：只添加之前没见过的合集
                    for item in items:
                        if item["Id"] not in seen_ids:
                            all_collections.append(item)
                            seen_ids.add(item["Id"])
                    
                    log.info(f"[{PLUGIN_ID}] 媒体库 {pid}: 获取到 {len(items)} 个合集（去重后累计 {len(all_collections)} 个）")
                except Exception as e:
                    log.error(f"[{PLUGIN_ID}] 查询媒体库 {pid} 失败：{e}")
        else:
            # 没有限定，查询所有媒体库
            url = f"{emby_server}/emby/Users/{user_id}/Items"
            params = {
                "api_key": emby_api_key,
                "IncludeItemTypes": "BoxSet",
                "Recursive": "true",
                "StartIndex": "0",
                "Limit": "2000"  # 最多获取 2000 个
            }
            response = requests.get(url, params=params, timeout=30)
            all_collections = response.json().get("Items", [])
        
        return all_collections
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
        try:
            user_id = get_emby_user_id(settings["emby_server"], settings["emby_api_key"])
        except Exception as e:
            log.error(f"[{PLUGIN_ID}] 获取 Emby 用户 ID 失败：{e}")
            return "获取 Emby 用户 ID 失败"
        if not user_id:
            log.error(f"[{PLUGIN_ID}] 无法获取 Emby 用户 ID")
            return "无法获取 Emby 用户 ID"
        log.info(f"[{PLUGIN_ID}] 获取到 Emby 用户 ID: {user_id}")

        # 3. 获取所有合集，建立名称映射
        log.info(f"[{PLUGIN_ID}] 正在获取 Emby 合集列表...")
        collections = get_all_collections(
            settings["emby_server"],
            settings["emby_api_key"],
            user_id,
            settings.get("parent_ids", "")
        )
        collection_map = {c["Name"].lower(): c["Id"] for c in collections if c.get("Name")}
        log.info(f"[{PLUGIN_ID}] 获取到 {len(collection_map)} 个 Emby 合集")

        # 4. 统计
        success_list = []
        skip_count = 0
        error_count = 0

        # 5. 遍历工作室
        for i, studio in enumerate(all_studios):
            studio_name = studio.get("name", "")

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
                stash_api_key=settings.get("stash_api_key", "")
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
