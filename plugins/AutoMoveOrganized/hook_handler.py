# -*- coding: utf-8 -*-
"""
hook_handler.py - Hook 模式处理模块

负责处理 Hook 触发的事件（Scene.Update.Post 等）
- 获取单个场景
- 分析文件位置
- 移动需要移动的文件
- 处理已在目标目录的文件（重新生成元数据）
"""

import json
import os
import re
from typing import Any, Dict

import stashapi.log as log
from stashapi.stashapp import StashInterface

from scene_fetcher import get_single_scene
from file_mover import (
    process_scene,
    remove_old_metadata,
    regenerate_file_at_target,
    regenerate_metadata_only,
    is_file_in_target_location,
)
from path_builder import build_target_path_for_existing_file


def task_log(message: str, progress: float | None = None) -> None:
    """
    向 Stash Task 界面输出一行 JSON 日志，可选带 progress（0~1）。
    """
    try:
        payload: Dict[str, Any] = {"output": str(message)}
        if progress is not None:
            try:
                p = float(progress)
                if p < 0:
                    p = 0.0
                if p > 1:
                    p = 1.0
                payload["progress"] = p
            except Exception:
                pass
        print(json.dumps(payload), flush=True)
    except Exception as e:
        # 不能因为日志输出失败导致任务崩溃
        log.error(f"[auto-move-organized] Failed to write task log: {e}")


def handle_hook(stash: StashInterface, scene_id: int, settings: Dict[str, Any]) -> str:
    """
    Hook 模式入口：处理单个场景（Scene.Update.Post 触发）

    1. 获取单个场景
    2. 分析文件位置（源目录/目标目录）
    3. 移动需要移动的文件
    4. 处理已在目标目录的文件（重新生成元数据）
    """
    dry_run = bool(settings.get("dry_run"))

    # 检查是否启用了 Hook 模式
    if not settings.get("enable_hook_mode", True):  # 默认启用，除非显式禁用
        msg = f"Hook mode disabled, skipping scene {scene_id}"
        log.info(msg)
        task_log(msg, progress=1.0)
        return msg

    scene_id = int(scene_id)
    log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] Hook mode, processing single scene id={scene_id}")

    # 获取场景信息
    scene = get_single_scene(stash, scene_id)

    if not scene:
        msg = f"Scene {scene_id} not found"
        task_log(msg, progress=1.0)
        return msg

    # 检查 move_only_organized 配置
    # 只有当 move_only_organized=true 时，才跳过 organized=false 的场景
    if not scene.get("organized") and settings.get("move_only_organized", True):
        msg = f"Scene {scene_id} not organized, skipped"
        log.info(msg)
        task_log(msg, progress=1.0)
        return msg

    # 能执行到这里，说明需要处理（organized=true 或 move_only_organized=false）

    # 获取配置
    source_target_mapping = settings.get("source_target_mapping", "").strip()
    target_root = settings.get("target_root", "").strip()

    # 检查场景中是否有文件在源目录（有映射时）或不在目标目录（无映射时）
    files_needing_processing = []
    files_already_in_target = []

    for file_obj in scene.get("files", []):
        file_path = file_obj.get("path", "")
        if not file_path:
            continue

        if source_target_mapping and '->' in source_target_mapping:
            # 有映射：检查文件是否在源目录或目标目录
            parts = source_target_mapping.split('->', 1)
            if len(parts) == 2:
                source_base_dir = parts[0].strip()
                target_base_dir = parts[1].strip()
                if source_base_dir and target_base_dir:
                    # 使用正则表达式匹配（与 scene_fetcher.py 一致）
                    # Stash 返回的路径永远是 / 格式，直接用 / 匹配
                    escaped_source = re.escape(source_base_dir)
                    escaped_target = re.escape(target_base_dir)
                    
                    # 检查文件是否在源目录
                    if re.match(f"^({escaped_source})(/.*|$)", file_path):
                        files_needing_processing.append(file_obj)
                    # 检查文件是否在目标目录
                    elif re.match(f"^({escaped_target})(/.*|$)", file_path):
                        files_already_in_target.append(file_obj)
                    else:
                        # 文件既不在源目录也不在目标目录，跳过处理
                        log.info(f"File '{file_path}' is neither in source nor in target directory, skipping.")
        else:
            # 无映射：检查文件是否不在目标目录
            if target_root and not is_file_in_target_location(file_path, scene, file_obj, settings):
                files_needing_processing.append(file_obj)
            else:
                files_already_in_target.append(file_obj)

    # 处理需要移动的文件（在源目录或不在目标目录）
    moved_count = 0
    if files_needing_processing:
        # 创建临时场景，只包含需要处理的文件
        temp_scene = dict(scene)
        temp_scene["files"] = files_needing_processing
        moved_count = process_scene(temp_scene, settings)

    # 处理已经在目标目录的文件（重新生成 NFO 和封面，如果命名规则参数变化则移动到新路径）
    if files_already_in_target:
        # 多文件模式处理
        multi_file_mode = settings.get("multi_file_mode", "all")

        if len(files_already_in_target) > 1:
            if multi_file_mode == "skip":
                log.info(f"Scene {scene_id} has {len(files_already_in_target)} files already in target directory, skipping due to multi_file_mode=skip")
                files_to_process = []
            elif multi_file_mode == "primary_only":
                log.debug(f"Scene {scene_id} has {len(files_already_in_target)} files already in target directory, processing only primary file")
                files_to_process = [files_already_in_target[0]]
            else:  # "all" mode - process all files
                log.debug(f"Scene {scene_id} has {len(files_already_in_target)} files already in target directory, processing all")
                files_to_process = files_already_in_target
        else:
            files_to_process = files_already_in_target

        for file_obj in files_to_process:
            file_path = file_obj.get("path", "")
            if not file_path:
                continue

            # 删除旧的 NFO 和封面
            remove_old_metadata(file_path, settings)

            # 检查是否需要移动到新路径（如果命名规则中的参数发生了变化）
            # 对于已经在目标目录的文件，使用专门的函数计算目标路径
            try:
                current_target_path = build_target_path_for_existing_file(file_path, scene, file_obj, settings)
                # 直接比较字符串（Stash 路径永远是 / 格式）
                if file_path != current_target_path:
                    # 需要移动到新路径
                    new_moved = regenerate_file_at_target(file_obj, scene, settings)
                    if new_moved:
                        moved_count += 1
                else:
                    # 不需要移动路径，只需重新生成元数据
                    regenerate_metadata_only(file_path, scene, settings)
            except Exception as e:
                log.error(f"Error checking if file needs to be moved: {e}")
                # 出错时，至少更新元数据
                regenerate_metadata_only(file_path, scene, settings)

    msg = f"Processed scene {scene_id}, moved {moved_count} file(s), dry_run={dry_run}"
    log.info(msg)
    task_log(msg, progress=1.0)
    return msg
