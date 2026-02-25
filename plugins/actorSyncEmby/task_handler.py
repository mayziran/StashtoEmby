"""
Task 处理器 - 手动批量同步所有演员

支持模式:
    - export_mode: 0-4（本地导出）
    - upload_mode: 0-4（Emby 上传）
    - 4=补缺模式（批量检查缺失，优化 IO）
"""

import os
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests
import stashapi.log as log

# 插件 ID 常量
PLUGIN_ID = "actorSyncEmby"


def _safe_segment(segment: str) -> str:
    """清理路径段，避免出现奇怪字符。"""
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    return segment or "_"


def _check_local_missing_batch(performer_names: list, actor_output_dir: str) -> Dict[str, Dict[str, bool]]:
    """
    批量检查演员本地文件是否缺失（只读取一次磁盘目录）。

    Args:
        performer_names: 演员名称列表
        actor_output_dir: 演员输出根目录

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
                    existing_dirs[dir_name] = {
                        "has_nfo": "actor.nfo" in files,
                        "has_image": any(f in files for f in ["folder.jpg", "poster.jpg"])
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
        performer_names: 演员名称列表
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥

    Returns:
        {演员名：{"need_image": bool, "need_metadata": bool, "actor_exists": bool}}
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
    for name in performer_names:
        result = {"need_image": True, "need_metadata": True, "actor_exists": False}

        try:
            encoded_name = quote(name)
            person_url = f"{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}"
            person_resp = requests.get(person_url, timeout=10)

            if person_resp.status_code != 200:
                results[name] = result
                continue

            person_data = person_resp.json()
            person_id = person_data.get('Id')

            if not person_id:
                results[name] = result
                continue

            # 获取详细信息
            if user_id:
                item_detail_url = f"{emby_server}/emby/Users/{user_id}/Items/{person_id}"
            else:
                item_detail_url = f"{emby_server}/emby/Items/{person_id}"

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
            log.error(f"检查 Emby 演员 {name} 失败：{e}")

        results[name] = result

    return results


def _get_local_need(
    export_mode: int,
    performer_name: str,
    local_cache: Dict[str, Any]
) -> Tuple[bool, int]:
    """
    判断是否需要处理本地导出，返回实际导出模式。

    Args:
        export_mode: 导出模式 (0-4)
        performer_name: 演员名称
        local_cache: 本地缺失检查结果缓存

    Returns:
        (need_local, actual_export_mode)
        need_local: 是否需要导出
        actual_export_mode: 实际使用的导出模式 (1=都导出，2=只 NFO，3=只图片)
    """
    if export_mode == 0:
        return False, 0
    elif export_mode in [1, 2, 3]:  # 覆盖模式直接返回
        return True, export_mode
    elif export_mode == 4:  # 补缺模式：根据缓存计算
        if performer_name in local_cache:
            status = local_cache[performer_name]
            need_nfo = status["need_nfo"]
            need_image = status["need_image"]
            if need_nfo and need_image:
                return True, 1  # 都导出
            elif need_nfo:
                return True, 2  # 只 NFO
            elif need_image:
                return True, 3  # 只图片
            else:
                return False, 0  # 都不需要
    return False, 0


def _get_emby_need(
    upload_mode: int,
    performer_name: str,
    emby_cache: Dict[str, Any]
) -> Tuple[bool, int]:
    """
    判断是否需要处理 Emby 上传，返回实际上模式。

    Args:
        upload_mode: 上传模式 (0-4)
        performer_name: 演员名称
        emby_cache: Emby 缺失检查结果缓存

    Returns:
        (need_emby, actual_upload_mode)
        need_emby: 是否需要上传
        actual_upload_mode: 实际使用的上传模式 (1=都上传，2=只元数据，3=只图片)
    """
    if upload_mode == 0:
        return False, 0
    elif upload_mode in [1, 2, 3]:  # 覆盖模式直接返回
        return True, upload_mode
    elif upload_mode == 4:  # 补缺模式：根据缓存计算
        if performer_name in emby_cache:
            status = emby_cache[performer_name]
            # 演员不存在于 Emby，跳过（补缺模式只补缺，不创建新演员）
            if not status.get("actor_exists", False):
                log.info(f"[{PLUGIN_ID}] 演员 {performer_name} 在 Emby 中不存在，补缺模式跳过")
                return False, 0
            need_image = status["need_image"]
            need_metadata = status["need_metadata"]
            if need_image and need_metadata:
                return True, 1  # 都上传
            elif need_metadata:
                return True, 2  # 只元数据
            elif need_image:
                return True, 3  # 只图片
            else:
                return False, 0  # 都不需要
    return False, 0


def _process_performer(
    performer: Dict[str, Any],
    export_mode: int,
    upload_mode: int,
    local_cache: Dict[str, Any],
    emby_cache: Dict[str, Any],
    local_exporter: Dict[str, Any],
    emby_uploader: Dict[str, Any],
    settings: Dict[str, Any]
) -> Tuple[bool, bool, bool, bool]:
    """
    处理单个演员的导出和上传。

    Args:
        performer: 演员信息
        export_mode: 导出模式
        upload_mode: 上传模式
        local_cache: 本地缺失缓存
        emby_cache: Emby 缺失缓存
        local_exporter: 本地导出模块
        emby_uploader: Emby 上传模块
        settings: 配置参数

    Returns:
        (need_local, need_emby, local_success, emby_success)
    """
    performer_name = performer.get("name")
    if not performer_name:
        return False, False, True, True

    # 判断需求
    need_local, actual_export_mode = _get_local_need(export_mode, performer_name, local_cache)
    need_emby, actual_upload_mode = _get_emby_need(upload_mode, performer_name, emby_cache)

    if not need_local and not need_emby:
        return need_local, need_emby, True, True

    # 默认成功（不需要处理也算成功）
    local_success = not need_local
    emby_success = not need_emby

    # 导出本地
    if need_local and local_exporter and actual_export_mode > 0:
        export_func = local_exporter.get("export_actor_to_local")
        if export_func:
            try:
                export_func(
                    performer=performer,
                    actor_output_dir=settings.get("actor_output_dir", ""),
                    export_mode=actual_export_mode,
                    server_conn=settings.get("server_connection", {}),
                    stash_api_key=settings.get("stash_api_key", ""),
                    dry_run=settings.get("dry_run", False)
                )
                local_success = True
            except Exception as e:
                log.error(f"[{PLUGIN_ID}] 演员 {performer_name}：本地导出失败：{e}")
                local_success = False

    # 上传 Emby
    if need_emby and emby_uploader and actual_upload_mode > 0:
        upload_func = emby_uploader.get("upload_actor_to_emby")
        if upload_func:
            try:
                upload_func(
                    performer=performer,
                    emby_server=settings.get("emby_server", ""),
                    emby_api_key=settings.get("emby_api_key", ""),
                    server_conn=settings.get("server_connection", {}),
                    stash_api_key=settings.get("stash_api_key", ""),
                    upload_mode=actual_upload_mode
                )
                emby_success = True
            except Exception as e:
                log.error(f"[{PLUGIN_ID}] 演员 {performer_name}：Emby 上传失败：{e}")
                emby_success = False

    return need_local, need_emby, local_success, emby_success


def handle_task(
    stash: Any,
    settings: Dict[str, Any],
    task_log_func: Any
) -> str:
    """
    处理 Task 任务（同步所有演员）

    Args:
        stash: Stash 连接
        settings: 配置参数（包含已加载的模块引用）
        task_log_func: Task 日志函数

    Returns:
        处理结果消息
    """
    export_mode = settings.get("export_mode", 1)
    upload_mode = settings.get("upload_mode", 1)

    # 简洁的启动日志
    local_mode_names = {0: "关闭", 1: "覆盖", 2: "只 NFO", 3: "只图片", 4: "补缺"}
    emby_mode_names = {0: "关闭", 1: "覆盖", 2: "只元数据", 3: "只图片", 4: "补缺"}
    local_mode = local_mode_names.get(export_mode, str(export_mode))
    emby_mode = emby_mode_names.get(upload_mode, str(upload_mode))

    log.info(f"[{PLUGIN_ID}] Task 模式启动：本地{local_mode} + Emby{emby_mode}")
    task_log_func(f"开始处理演员 (本地={local_mode}, Emby={emby_mode})", progress=0.0)

    # 判断是否使用批量检查（先获取名称→检查缺失→只获取缺失演员完整数据）
    # 只有双方都是补缺模式（04/40/44）时才使用，因为不需要获取完整数据
    use_batch_check = (export_mode == 4 and upload_mode == 4) or \
                      (export_mode == 4 and upload_mode == 0) or \
                      (export_mode == 0 and upload_mode == 4)

    per_page = 1000
    page = 1

    # 统计信息
    total_actors = 0
    actors_processed = 0
    actors_skipped = 0
    local_ok_count = 0
    local_fail_count = 0
    emby_ok_count = 0
    emby_fail_count = 0

    # 缓存
    local_missing_cache = {}
    emby_missing_cache = {}

    # 从 settings 获取已加载的模块
    local_exporter = settings.get("local_exporter")
    emby_uploader = settings.get("emby_uploader")

    # 定义字段模板
    FULL_FRAGMENT = """
        id name image_path gender country birthdate height_cm measurements
        fake_tits disambiguation details ethnicity eye_color hair_color
        career_length tattoos piercings weight death_date circumcised
        penis_length alias_list urls
    """
    BASIC_FRAGMENT = "id\nname"

    # 根据模式决定获取哪些字段
    fragment = BASIC_FRAGMENT if use_batch_check else FULL_FRAGMENT

    while True:
        # 第 1 步：获取当前页演员数据
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

        # 第 2 步：批量检查缺失（只在批量检查模式下使用）
        if use_batch_check:
            performer_names = [p.get("name") for p in page_performers if p.get("name")]

            if export_mode == 4 and local_exporter:
                if not local_missing_cache:
                    local_missing_cache = _check_local_missing_batch(performer_names, settings.get("actor_output_dir", ""))
                    local_missing_count = sum(1 for v in local_missing_cache.values() if v['need_nfo'] or v['need_image'])
                    log.info(f"[{PLUGIN_ID}] 本地缺失检查：{local_missing_count} 位演员需要处理")

            if upload_mode == 4 and emby_uploader:
                if not emby_missing_cache:
                    emby_missing_cache = _check_emby_missing_batch(
                        performer_names,
                        settings.get("emby_server", ""),
                        settings.get("emby_api_key", "")
                    )
                    emby_missing_count = sum(1 for v in emby_missing_cache.values() if v['need_image'] or v['need_metadata'])
                    log.info(f"[{PLUGIN_ID}] Emby 缺失检查：{emby_missing_count} 位演员需要处理")

            # 第 3 步：筛选出需要处理的演员 ID
            current_page_ids = []
            for performer in page_performers:
                performer_id = performer.get("id")
                performer_name = performer.get("name")
                if not performer_id or not performer_name:
                    continue

                need_local, _ = _get_local_need(export_mode, performer_name, local_missing_cache)
                need_emby, _ = _get_emby_need(upload_mode, performer_name, emby_missing_cache)

                if need_local or need_emby:
                    current_page_ids.append(performer_id)
                else:
                    actors_skipped += 1

            total_actors += len(page_performers)
            log.info(f"[{PLUGIN_ID}] 需处理演员：{len(current_page_ids)}/{len(page_performers)}")

            # 第 4 步：处理需要处理的演员（逐个获取完整数据）
            for performer_id in current_page_ids:
                try:
                    performer = stash.find_performer(performer_id)
                    if not performer:
                        log.error(f"找不到演员 ID: {performer_id}")
                        local_fail_count += 1
                        emby_fail_count += 1
                        actors_processed += 1
                        continue

                    need_local, need_emby, local_success, emby_success = _process_performer(
                        performer, export_mode, upload_mode,
                        local_missing_cache, emby_missing_cache,
                        local_exporter, emby_uploader, settings
                    )

                    # 统计
                    if need_local or need_emby:
                        actors_processed += 1
                        if need_local:
                            if local_success:
                                local_ok_count += 1
                            else:
                                local_fail_count += 1
                        if need_emby:
                            if emby_success:
                                emby_ok_count += 1
                            else:
                                emby_fail_count += 1

                except Exception as e:
                    log.error(f"获取缺失演员完整数据失败：{e}")
                    local_fail_count += 1
                    emby_fail_count += 1
                    actors_processed += 1

        else:
            # 非批量检查模式：已获取完整数据，直接处理
            # 如果需要补缺，先批量检查缺失
            if export_mode == 4 and local_exporter:
                performer_names = [p.get("name") for p in page_performers if p.get("name")]
                if not local_missing_cache:
                    log.info(f"[{PLUGIN_ID}] 批量检查本地缺失...")
                    local_missing_cache = _check_local_missing_batch(performer_names, settings.get("actor_output_dir", ""))
                    log.info(f"[{PLUGIN_ID}] 本地缺失检查结果：{sum(1 for v in local_missing_cache.values() if v['need_nfo'] or v['need_image'])} 个演员需要处理")

            if upload_mode == 4 and emby_uploader:
                performer_names = [p.get("name") for p in page_performers if p.get("name")]
                if not emby_missing_cache:
                    log.info(f"[{PLUGIN_ID}] 批量检查 Emby 缺失...")
                    emby_missing_cache = _check_emby_missing_batch(
                        performer_names,
                        settings.get("emby_server", ""),
                        settings.get("emby_api_key", "")
                    )
                    log.info(f"[{PLUGIN_ID}] Emby 缺失检查结果：{sum(1 for v in emby_missing_cache.values() if v['need_image'] or v['need_metadata'])} 个演员需要处理")

            # 处理当前页演员
            total_actors += len(page_performers)

            for performer in page_performers:
                try:
                    if not performer.get("id"):
                        continue

                    need_local, need_emby, local_success, emby_success = _process_performer(
                        performer, export_mode, upload_mode,
                        local_missing_cache, emby_missing_cache,
                        local_exporter, emby_uploader, settings
                    )

                    # 统计
                    if need_local or need_emby:
                        actors_processed += 1
                        if need_local:
                            if local_success:
                                local_ok_count += 1
                            else:
                                local_fail_count += 1
                        if need_emby:
                            if emby_success:
                                emby_ok_count += 1
                            else:
                                emby_fail_count += 1
                    else:
                        actors_skipped += 1

                except Exception as e:
                    log.error(f"处理演员 {performer.get('name', 'Unknown')} 失败：{e}")
                    local_fail_count += 1
                    emby_fail_count += 1
                    actors_processed += 1

        # 每页完成后显示进度
        task_log_func(f"第{page}批完成：处理 {actors_processed} 位演员",
                     progress=actors_processed / max(total_actors, 1))

        # 如果当前页少于 per_page，说明已经是最后一页
        if page_total < per_page:
            break

        page += 1

    # 生成最终统计日志
    log.info(f"[{PLUGIN_ID}] 处理完成：Stash 共 {total_actors} 位演员")

    if actors_skipped > 0:
        log.info(f"  - 跳过：{actors_skipped} 位（不需要处理）")
    log.info(f"  - 处理：{actors_processed} 位")

    if export_mode > 0:
        log.info(f"  - 本地：成功 {local_ok_count} 位，失败 {local_fail_count} 位")

    if upload_mode > 0:
        log.info(f"  - Emby: 成功 {emby_ok_count} 位，失败 {emby_fail_count} 位")

    # 生成消息
    msg = f"处理完成：Stash 共 {total_actors} 位演员"
    if actors_skipped > 0:
        msg += f"，跳过 {actors_skipped} 位"
    msg += f"，处理 {actors_processed} 位"
    if export_mode > 0:
        msg += f"，本地成功 {local_ok_count}/{local_ok_count + local_fail_count} 位"
    if upload_mode > 0:
        msg += f"，Emby 成功 {emby_ok_count}/{emby_ok_count + emby_fail_count} 位"

    task_log_func(msg, progress=1.0)
    return msg
