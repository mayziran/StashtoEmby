"""
工作室演员同步 Task - 将工作室关联的演员同步到 Emby 合集

功能:
    1. 获取所有工作室
    2. 查询每个工作室关联的演员
    3. 将演员写入 Emby 合集的 People 字段

使用场景:
    - 手动执行，批量同步演员信息
    - 与 StudioToCollection 主 Task 配合使用
"""

import json
from typing import Any, Dict, List, Optional

import requests
import stashapi.log as log

PLUGIN_ID = "StudioToCollection"

# 工作室 Fragment（只需要 id 和 name）
STUDIO_FRAGMENT = """
    id
    name
"""

# 演员 Fragment（需要 name 和 disambiguation）
PERFORMER_FRAGMENT = """
    name
    disambiguation
"""


def task_log(message: str, progress: float | None = None) -> None:
    """向 Stash Task 界面输出日志"""
    try:
        payload: Dict[str, Any] = {"output": str(message)}
        if progress is not None:
            p = float(progress)
            payload["progress"] = max(0.0, min(1.0, p))
        print(json.dumps(payload), flush=True)
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] Task log 失败：{e}")


def get_emby_user_id(emby_server: str, emby_api_key: str) -> Optional[str]:
    """获取 Emby 用户 ID"""
    url = f"{emby_server}/emby/Users"
    params = {"api_key": emby_api_key}
    response = requests.get(url, params=params, timeout=30)
    users = response.json()
    return users[0]["Id"] if users else None


def get_all_collections(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    parent_ids: str = ""
) -> List[Dict[str, Any]]:
    """
    获取所有合集

    Args:
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        user_id: Emby 用户 ID
        parent_ids: 限定媒体库 ID 列表（逗号分隔）

    Returns:
        合集列表
    """
    all_collections = []

    try:
        # 解析 parent_ids
        if parent_ids:
            id_list = [id.strip() for id in parent_ids.split(",") if id.strip()]
        else:
            id_list = []

        if id_list:
            # 分别查询每个媒体库
            for parent_id in id_list:
                url = f"{emby_server}/emby/Users/{user_id}/Items"
                params = {
                    "api_key": emby_api_key,
                    "IncludeItemTypes": "BoxSet",
                    "Recursive": "true",
                    "StartIndex": "0",
                    "ParentId": parent_id,
                    "Limit": "2000"
                }
                response = requests.get(url, params=params, timeout=30)
                items = response.json().get("Items", [])
                all_collections.extend(items)
                log.info(f"[{PLUGIN_ID}] 媒体库 {parent_id} 中找到 {len(items)} 个合集")
        else:
            # 查询所有媒体库
            url = f"{emby_server}/emby/Users/{user_id}/Items"
            params = {
                "api_key": emby_api_key,
                "IncludeItemTypes": "BoxSet",
                "Recursive": "true",
                "StartIndex": "0",
                "Limit": "2000"
            }
            response = requests.get(url, params=params, timeout=30)
            all_collections = response.json().get("Items", [])

        # 按 Id 去重
        seen_ids = set()
        unique_collections = []
        for c in all_collections:
            if c.get("Id") not in seen_ids:
                seen_ids.add(c["Id"])
                unique_collections.append(c)

        return unique_collections

    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 获取合集失败：{e}")
        return []


def get_performers_by_studio(
    stash: Any,
    studio_id: int
) -> List[Dict[str, Any]]:
    """
    获取与工作室关联的所有演员

    Args:
        stash: Stash 接口
        studio_id: 工作室 ID

    Returns:
        演员列表（只有姓名）
    """
    try:
        # 查询所有关联了该工作室的演员
        # 使用 f 参数作为过滤器（stash-python 库的正确用法）
        performers = stash.find_performers(
            f={
                "studios": {"value": [str(studio_id)], "modifier": "INCLUDES"}
            },
            fragment=PERFORMER_FRAGMENT
        )

        # 转换为 Emby People 格式（包含消歧义的完整姓名）
        people = []
        for p in performers:
            if not isinstance(p, dict):
                continue
            # 构建完整姓名（包含消歧义）
            name = p.get("name", "")
            disambiguation = p.get("disambiguation", "")
            if name and disambiguation:
                name = f"{name} ({disambiguation})"
            if not name:
                continue

            people.append({"Name": name})

        return people

    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 获取演员失败：{e}")
        return []


def upload_people_to_emby(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    collection_id: str,
    people: List[Dict[str, Any]]
) -> bool:
    """
    上传演员列表到 Emby 合集

    Args:
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        user_id: Emby 用户 ID
        collection_id: Emby 合集 ID
        people: 演员列表（Emby People 格式）

    Returns:
        上传是否成功
    """
    try:
        # 第 1 步：获取合集现有数据
        get_url = f"{emby_server}/emby/Users/{user_id}/Items/{collection_id}?api_key={emby_api_key}"
        get_response = requests.get(get_url, timeout=30)

        if get_response.status_code != 200:
            log.error(f"[{PLUGIN_ID}] 获取合集现有数据失败：{get_response.status_code}")
            return False

        existing_data = get_response.json()

        # 第 2 步：更新 People 字段
        update_data = existing_data.copy()
        update_data["People"] = people
        update_data["Id"] = collection_id

        # 第 3 步：POST 完整数据回去
        update_url = f"{emby_server}/emby/Items/{collection_id}?api_key={emby_api_key}"
        response = requests.post(
            update_url,
            json=update_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code in [200, 204]:
            log.info(f"[{PLUGIN_ID}] ✓ 演员已同步：{len(people)} 个")
            return True

        log.error(
            f"[{PLUGIN_ID}] 同步演员失败："
            f"{response.status_code} - {response.text[:200] if response.text else ''}"
        )
        return False

    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 同步演员失败：{e}")
        return False


def handle_task(
    stash: Any,
    settings: Dict[str, Any],
    task_log_func
) -> str:
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
        task_log_func("开始同步工作室演员", progress=0.0)

        # 1. 获取所有工作室
        try:
            all_studios = []
            page = 1
            per_page = 1000

            while True:
                page_studios = stash.find_studios(
                    f=None,
                    filter={"page": page, "per_page": per_page},
                    fragment=STUDIO_FRAGMENT
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
        total_performers = 0

        # 5. 遍历工作室
        for i, studio in enumerate(all_studios):
            studio_name = studio.get("name", "")
            progress = (i + 1) / total_count

            # 名称精确匹配
            collection_id = collection_map.get(studio_name.lower())
            if not collection_id:
                skip_count += 1
                continue

            # 获取演员列表
            performers = get_performers_by_studio(stash, studio["id"])
            if not performers:
                log.info(f"[{PLUGIN_ID}] - {studio_name}: 无演员")
                continue

            # 上传演员到 Emby
            if upload_people_to_emby(
                emby_server=settings["emby_server"],
                emby_api_key=settings["emby_api_key"],
                user_id=user_id,
                collection_id=collection_id,
                people=performers
            ):
                success_list.append(studio_name)
                total_performers += len(performers)
                log.info(f"[{PLUGIN_ID}] ✓ {studio_name}: {len(performers)} 个演员")
            else:
                error_count += 1
                log.error(f"[{PLUGIN_ID}] ✗ {studio_name}: 同步失败")

            task_log_func(f"同步中：{studio_name}", progress=progress)

        # 6. 输出统计
        msg = (
            f"演员同步完成！\n"
            f"成功：{len(success_list)} 个工作室\n"
            f"跳过：{skip_count} 个工作室（无匹配合集或无演员）\n"
            f"失败：{error_count} 个工作室\n"
            f"共同步：{total_performers} 个演员"
        )

        log.info(msg)
        task_log_func(msg, progress=1.0)
        return msg

    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 执行失败：{e}")
        task_log_func(f"执行失败：{e}", progress=1.0)
        return f"执行失败：{e}"
