# -*- coding: utf-8 -*-
"""
task_handler.py - Task 模式处理模块

负责处理 Task 模式（手动批量执行）
- 分页获取所有场景（API 已根据 move_only_organized 配置过滤）
- 遍历处理场景
- 输出进度和统计
"""

import json
from typing import Any, Dict

import stashapi.log as log
from stashapi.stashapp import StashInterface

from scene_fetcher import get_all_scenes
from file_mover import process_scene


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


def handle_task(stash: StashInterface, settings: Dict[str, Any]) -> str:
    """
    Task 模式入口：手动执行，遍历所有场景

    1. 分页获取所有场景（API 已根据 move_only_organized 配置过滤）
    2. 遍历处理场景
    3. 输出进度和统计
    """
    dry_run = bool(settings.get("dry_run"))

    log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] Task mode: scanning all scenes")

    scenes = get_all_scenes(stash, settings, per_page=int(settings.get("per_page", 1000)))
    total_scenes = len(scenes)
    total_moved = 0

    if total_scenes == 0:
        msg = "No scenes found"
        log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] {msg}")
        task_log(msg, progress=1.0)
        return msg

    # API 已经根据 move_only_organized 配置过滤了场景，所以返回的都是需要处理的
    for index, scene in enumerate(scenes, start=1):
        sid = int(scene["id"])

        log.info(f"Processing scene id={sid} title={scene.get('title')!r}")
        progress = index / total_scenes
        task_log(f"Processing scene {sid} ({index}/{total_scenes})", progress=progress)

        moved = process_scene(scene, settings)
        total_moved += moved

    msg = (
        f"Scanned {total_scenes} scenes, "
        f"moved files: {total_moved}, dry_run={dry_run}"
    )
    log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] {msg}")
    task_log(msg, progress=1.0)
    return msg
