"""
Task 处理器 - 手动批量同步所有演员

两个独立 Task:
    - task_local: 导出演员到本地（export_mode: 1/2/3/4）
    - task_emby: 上传演员到 Emby（upload_mode: 1/2/3/4）
"""

import os
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests
import stashapi.log as log
from utils import PERFORMER_FRAGMENT_FOR_API

# 插件 ID 常量
PLUGIN_ID = "actorSyncEmby"


# ==================== 工具函数 ====================


def _safe_segment(segment: str) -> str:
    """清理路径段，避免出现奇怪字符。"""
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    return segment or "_"


def _check_local_missing_batch(performer_names: list, actor_output_dir: str) -> Dict[str, Dict[str, bool]]:
    """
    批量检查演员本地文件是否缺失（只读取一次磁盘目录）。

    Returns:
        {演员名：{"need_nfo": bool, "need_image": bool}}
    """
    results = {}

    if not actor_output_dir or not performer_names:
        for name in performer_names:
            results[name] = {"need_nfo": True, "need_image": True}
        return results

    # 第 1 步：一次性读取所有本地目录（只读 1 次磁盘）
    existing_dirs = {}
    if os.path.exists(actor_output_dir):
        try:
            for dir_name in os.listdir(actor_output_dir):
                actor_dir = os.path.join(actor_output_dir, dir_name)
                if os.path.isdir(actor_dir):
                    files = os.listdir(actor_dir)
                    # 检查 NFO
                    has_nfo = "actor.nfo" in files
                    # 检查图片：folder.{ext} 格式（支持 jpg/png/webp/bmp/gif）
                    has_image = any(f.lower().startswith("folder.") for f in files)
                    existing_dirs[dir_name] = {
                        "has_nfo": has_nfo,
                        "has_image": has_image
                    }
        except Exception as e:
            log.error(f"读取本地目录失败：{e}")

    # 第 2 步：内存比对（不读磁盘）
    for name in performer_names:
        safe_name = _safe_segment(name)
        if safe_name in existing_dirs:
            dir_info = existing_dirs[safe_name]
            results[name] = {
                "need_nfo": not dir_info["has_nfo"],
                "need_image": not dir_info["has_image"]
            }
        else:
            results[name] = {"need_nfo": True, "need_image": True}

    return results


def _check_emby_missing_batch(performer_names: list, emby_server: str, emby_api_key: str) -> Dict[str, Dict[str, bool]]:
    """
    批量检查演员在 Emby 中是否缺失。

    Args:
        performer_names: 演员完整姓名列表（包含消歧义，如 "John Doe (Studio A)"）

    Returns:
        {演员完整姓名：{"need_image": bool, "need_metadata": bool, "actor_exists": bool}}
    """
    results = {}

    if not emby_server or not emby_api_key or not performer_names:
        for name in performer_names:
            results[name] = {"need_image": True, "need_metadata": True, "actor_exists": False}
        return results

    # 获取用户 ID（只需要一次）
    user_id = None
    try:
        users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
        users_response = requests.get(users_url, timeout=10)
        if users_response.status_code == 200:
            users_data = users_response.json()
            if users_data:
                user_id = users_data[0]['Id']
    except Exception as e:
        log.error(f"获取 Emby 用户 ID 失败：{e}")

    # 批量查询演员
    # 使用完整姓名搜索（包含消歧义），因为 Emby 通过 NFO 已经知道完整姓名
    for full_name in performer_names:
        result = {"need_image": True, "need_metadata": True, "actor_exists": False}

        try:
            encoded_name = quote(full_name)
            person_url = f"{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}"
            person_resp = requests.get(person_url, timeout=10)

            if person_resp.status_code != 200:
                results[full_name] = result
                continue

            person_data = person_resp.json()
            person_id = person_data.get('Id')

            if not person_id:
                results[full_name] = result
                continue

            # 获取详细信息
            if not user_id:
                log.error(f"无法获取 Emby 用户 ID，演员 {full_name} 标记为缺失")
                results[full_name] = result
                continue

            item_detail_url = f"{emby_server}/emby/Users/{user_id}/Items/{person_id}"

            params = {
                "api_key": emby_api_key,
                "Fields": "Name,ImageTags,Overview,ProviderIds"
            }

            item_resp = requests.get(item_detail_url, params=params, timeout=10)

            if item_resp.status_code == 200:
                item_data = item_resp.json()
                emby_has_image = bool(item_data.get('ImageTags', {}).get('Primary'))
                emby_has_overview = bool(item_data.get('Overview'))

                result["actor_exists"] = True
                result["need_image"] = not emby_has_image
                result["need_metadata"] = not emby_has_overview

        except Exception as e:
            log.error(f"检查 Emby 演员 {full_name} 失败：{e}")

        results[full_name] = result

    return results


def _get_local_need(
    export_mode: int,
    performer_name: str,
    local_cache: Dict[str, Any]
) -> Tuple[bool, int]:
    """
    判断是否需要处理本地导出，返回实际导出模式。
    """
    if export_mode == 0:
        return False, 0
    elif export_mode in [1, 2, 3]:
        return True, export_mode
    elif export_mode == 4:
        if performer_name in local_cache:
            status = local_cache[performer_name]
            need_nfo = status["need_nfo"]
            need_image = status["need_image"]
            if need_nfo and need_image:
                return True, 1
            elif need_nfo:
                return True, 2
            elif need_image:
                return True, 3
            else:
                return False, 0
    return False, 0


def _get_emby_need(
    upload_mode: int,
    performer_name: str,
    emby_cache: Dict[str, Any]
) -> Tuple[bool, int]:
    """
    判断是否需要处理 Emby 上传，返回实际上模式。
    """
    if upload_mode == 0:
        return False, 0
    elif upload_mode in [1, 2, 3]:
        return True, upload_mode
    elif upload_mode == 4:
        if performer_name in emby_cache:
            status = emby_cache[performer_name]
            if not status.get("actor_exists", False):
                return False, 0
            need_image = status["need_image"]
            need_metadata = status["need_metadata"]
            if need_image and need_metadata:
                return True, 1
            elif need_metadata:
                return True, 2
            elif need_image:
                return True, 3
            else:
                return False, 0
    return False, 0


# ==================== Task 入口函数 ====================


def task_local(
    stash: Any,
    settings: Dict[str, Any],
    task_log_func: Any
) -> str:
    """
    Task 1: 导出演员到本地

    Args:
        stash: Stash 连接
        settings: 配置参数（包含 export_mode）
        task_log_func: Task 日志函数

    Returns:
        处理结果消息
    """
    from utils import build_performer_name

    export_mode = settings.get("export_mode", 1)

    # 模式 0=关闭，直接返回
    if export_mode == 0:
        msg = "本地导出模式已关闭，未执行任何操作"
        log.info(f"[{PLUGIN_ID}] {msg}")
        task_log_func(msg, progress=1.0)
        return msg

    # 启动日志
    mode_names = {0: "关闭", 1: "覆盖", 2: "只 NFO", 3: "只图片", 4: "补缺"}
    mode_name = mode_names.get(export_mode, str(export_mode))
    log.info(f"[{PLUGIN_ID}] 本地 Task 启动：{mode_name}")
    task_log_func(f"开始导出演员到本地 ({mode_name})", progress=0.0)

    # 补缺模式才检查缺失
    use_batch_check = (export_mode == 4)

    # 缓存
    local_cache = {}
    local_exporter = settings.get("local_exporter")

    # 根据模式决定获取哪些字段
    # 模式 3 (只图片): 只需要 id, name, disambiguation, image_path
    # 模式 4 (补缺): 先只获取 id+name+disambiguation，后续再获取完整数据
    # 其他模式：获取完整 24 个字段
    if export_mode == 3:
        fragment = "id\nname\ndisambiguation\nimage_path"
    elif export_mode == 4:
        fragment = "id\nname\ndisambiguation"
    else:
        fragment = PERFORMER_FRAGMENT_FOR_API

    # 统计
    total_actors = 0
    actors_processed = 0
    actors_skipped = 0
    ok_count = 0
    fail_count = 0

    per_page = 1000
    page = 1

    while True:
        # 获取当前页演员数据
        try:
            page_performers = stash.find_performers(
                f=None,
                filter={"page": page, "per_page": per_page},
                fragment=fragment,
            )
        except Exception as e:
            log.error(f"获取演员列表失败：{e}")
            break

        if not page_performers:
            break

        page_total = len(page_performers)
        total_actors += len(page_performers)

        # 补缺模式：批量检查缺失（只检查第一页）
        if use_batch_check and local_exporter and not local_cache:
            # 使用完整姓名（包含消歧义），与本地目录名匹配
            performer_names = [build_performer_name(p) for p in page_performers if p.get("name")]
            local_cache = _check_local_missing_batch(performer_names, settings.get("actor_output_dir", ""))
            check_count = sum(1 for v in local_cache.values() if v['need_nfo'] or v['need_image'])
            log.info(f"[{PLUGIN_ID}] 本地缺失检查：{check_count} 位演员需要处理")

        # 补缺模式：筛选需要处理的演员
        if use_batch_check:
            current_page_ids = []
            for performer in page_performers:
                performer_id = performer.get("id")
                performer_name = build_performer_name(performer)
                if not performer_id or not performer_name:
                    continue

                need_local, _ = _get_local_need(export_mode, performer_name, local_cache)
                if need_local:
                    current_page_ids.append(performer_id)
                else:
                    actors_skipped += 1

            if current_page_ids:
                log.info(f"[{PLUGIN_ID}] 需处理演员：{len(current_page_ids)}/{len(page_performers)}")
        else:
            # 覆盖模式：处理所有演员
            current_page_ids = [p.get("id") for p in page_performers if p.get("id")]

        # 处理演员
        for performer_id in current_page_ids:
            try:
                # 补缺模式：获取完整数据
                if use_batch_check:
                    performer = stash.find_performer(performer_id, fragment=PERFORMER_FRAGMENT_FOR_API)
                    if not performer:
                        log.error(f"找不到演员 ID: {performer_id}")
                        fail_count += 1
                        actors_processed += 1
                        continue
                else:
                    # 覆盖模式：已有完整数据
                    performer = next((p for p in page_performers if p.get("id") == performer_id), None)
                    if not performer:
                        continue

                # 执行导出
                need_local, actual_mode = _get_local_need(export_mode, build_performer_name(performer), local_cache)

                if need_local and local_exporter and actual_mode > 0:
                    export_func = local_exporter.get("export_actor_to_local")
                    if export_func:
                        export_func(
                            performer=performer,
                            actor_output_dir=settings.get("actor_output_dir", ""),
                            export_mode=actual_mode,
                            server_conn=settings.get("server_connection", {}),
                            stash_api_key=settings.get("stash_api_key", "")
                        )
                        ok_count += 1
                    else:
                        fail_count += 1
                else:
                    actors_skipped += 1

                actors_processed += 1

            except Exception as e:
                log.error(f"处理演员 ID {performer_id} 失败：{e}")
                fail_count += 1
                actors_processed += 1

        # 进度
        task_log_func(f"第{page}批完成：处理 {actors_processed} 位演员",
                     progress=actors_processed / max(total_actors, 1))

        # 最后一页
        if page_total < per_page:
            break

        page += 1

    # 统计日志
    log.info(f"[{PLUGIN_ID}] 处理完成：Stash 共 {total_actors} 位演员")
    if actors_skipped > 0:
        log.info(f"  - 跳过：{actors_skipped} 位")
    log.info(f"  - 处理：{actors_processed} 位")
    log.info(f"  - 本地：成功 {ok_count} 位，失败 {fail_count} 位")

    msg = f"处理完成：Stash 共 {total_actors} 位演员"
    if actors_skipped > 0:
        msg += f"，跳过 {actors_skipped} 位"
    msg += f"，处理 {actors_processed} 位"
    if ok_count + fail_count > 0:
        msg += f"，本地成功 {ok_count}/{ok_count + fail_count} 位"

    task_log_func(msg, progress=1.0)
    return msg


def task_emby(
    stash: Any,
    settings: Dict[str, Any],
    task_log_func: Any
) -> str:
    """
    Task 2: 上传演员到 Emby

    Args:
        stash: Stash 连接
        settings: 配置参数（包含 upload_mode）
        task_log_func: Task 日志函数

    Returns:
        处理结果消息
    """
    from utils import build_performer_name

    upload_mode = settings.get("upload_mode", 1)

    # 模式 0=关闭，直接返回
    if upload_mode == 0:
        msg = "Emby 上传模式已关闭，未执行任何操作"
        log.info(f"[{PLUGIN_ID}] {msg}")
        task_log_func(msg, progress=1.0)
        return msg

    # 启动日志
    mode_names = {0: "关闭", 1: "覆盖", 2: "只元数据", 3: "只图片", 4: "补缺"}
    mode_name = mode_names.get(upload_mode, str(upload_mode))
    log.info(f"[{PLUGIN_ID}] Emby Task 启动：{mode_name}")
    task_log_func(f"开始上传演员到 Emby ({mode_name})", progress=0.0)

    # 补缺模式才检查缺失
    use_batch_check = (upload_mode == 4)

    # 缓存
    emby_cache = {}
    emby_uploader = settings.get("emby_uploader")

    # 根据模式决定获取哪些字段
    # 模式 3 (只图片): 只需要 id, name, disambiguation, image_path
    # 模式 4 (补缺): 先只获取 id+name+disambiguation，后续再获取完整数据
    # 其他模式：获取完整 24 个字段
    if upload_mode == 3:
        fragment = "id\nname\ndisambiguation\nimage_path"
    elif upload_mode == 4:
        fragment = "id\nname\ndisambiguation"
    else:
        fragment = PERFORMER_FRAGMENT_FOR_API

    # 统计
    total_actors = 0
    actors_processed = 0
    actors_skipped = 0
    ok_count = 0
    fail_count = 0

    per_page = 1000
    page = 1

    while True:
        # 获取当前页演员数据
        try:
            page_performers = stash.find_performers(
                f=None,
                filter={"page": page, "per_page": per_page},
                fragment=fragment,
            )
        except Exception as e:
            log.error(f"获取演员列表失败：{e}")
            break

        if not page_performers:
            break

        page_total = len(page_performers)
        total_actors += len(page_performers)

        # 补缺模式：批量检查缺失（只检查第一页）
        if use_batch_check and emby_uploader and not emby_cache:
            # 使用完整姓名（包含消歧义），与后续判断时的 key 一致
            performer_names = [build_performer_name(p) for p in page_performers if p.get("name")]
            emby_cache = _check_emby_missing_batch(
                performer_names,
                settings.get("emby_server", ""),
                settings.get("emby_api_key", "")
            )
            check_count = sum(1 for v in emby_cache.values() if v['need_image'] or v['need_metadata'])
            log.info(f"[{PLUGIN_ID}] Emby 缺失检查：{check_count} 位演员需要处理")

        # 补缺模式：筛选需要处理的演员
        if use_batch_check:
            current_page_ids = []
            for performer in page_performers:
                performer_id = performer.get("id")
                performer_name = build_performer_name(performer)
                if not performer_id or not performer_name:
                    continue

                need_emby, _ = _get_emby_need(upload_mode, performer_name, emby_cache)
                if need_emby:
                    current_page_ids.append(performer_id)
                else:
                    actors_skipped += 1

            if current_page_ids:
                log.info(f"[{PLUGIN_ID}] 需处理演员：{len(current_page_ids)}/{len(page_performers)}")
        else:
            # 覆盖模式：处理所有演员
            current_page_ids = [p.get("id") for p in page_performers if p.get("id")]

        # 处理演员
        for performer_id in current_page_ids:
            try:
                # 补缺模式：获取完整数据
                if use_batch_check:
                    performer = stash.find_performer(performer_id, fragment=PERFORMER_FRAGMENT_FOR_API)
                    if not performer:
                        log.error(f"找不到演员 ID: {performer_id}")
                        fail_count += 1
                        actors_processed += 1
                        continue
                else:
                    # 覆盖模式：已有完整数据
                    performer = next((p for p in page_performers if p.get("id") == performer_id), None)
                    if not performer:
                        continue

                # 执行上传
                need_emby, actual_mode = _get_emby_need(upload_mode, build_performer_name(performer), emby_cache)

                if need_emby and emby_uploader and actual_mode > 0:
                    upload_func = emby_uploader.get("upload_actor_to_emby")
                    if upload_func:
                        upload_func(
                            performer=performer,
                            emby_server=settings.get("emby_server", ""),
                            emby_api_key=settings.get("emby_api_key", ""),
                            server_conn=settings.get("server_connection", {}),
                            stash_api_key=settings.get("stash_api_key", ""),
                            upload_mode=actual_mode
                        )
                        ok_count += 1
                    else:
                        fail_count += 1
                else:
                    actors_skipped += 1

                actors_processed += 1

            except Exception as e:
                log.error(f"处理演员 ID {performer_id} 失败：{e}")
                fail_count += 1
                actors_processed += 1

        # 进度
        task_log_func(f"第{page}批完成：处理 {actors_processed} 位演员",
                     progress=actors_processed / max(total_actors, 1))

        # 最后一页
        if page_total < per_page:
            break

        page += 1

    # 统计日志
    log.info(f"[{PLUGIN_ID}] 处理完成：Stash 共 {total_actors} 位演员")
    if actors_skipped > 0:
        log.info(f"  - 跳过：{actors_skipped} 位")
    log.info(f"  - 处理：{actors_processed} 位")
    log.info(f"  - Emby: 成功 {ok_count} 位，失败 {fail_count} 位")

    msg = f"处理完成：Stash 共 {total_actors} 位演员"
    if actors_skipped > 0:
        msg += f"，跳过 {actors_skipped} 位"
    msg += f"，处理 {actors_processed} 位"
    if ok_count + fail_count > 0:
        msg += f"，Emby 成功 {ok_count}/{ok_count + fail_count} 位"

    task_log_func(msg, progress=1.0)
    return msg
