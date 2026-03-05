# -*- coding: utf-8 -*-
"""
task_handler.py - Task 模式处理模块

负责处理 Task 模式（手动批量执行）
- 分页获取所有场景
- 遍历处理 organized=true 的场景
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
        log.error(f"Failed to write task log: {e}")


def handle_task(stash: StashInterface, settings: Dict[str, Any]) -> str:
    """
    Task 模式入口：手动执行，遍历所有场景，移动 organized=true 的

    1. 分页获取所有场景
    2. 遍历处理 organized=true 的场景
    3. 输出进度和统计
    """
    dry_run = bool(settings.get("dry_run"))

    log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] Task mode: scanning all scenes and moving organized=True ones")

    scenes = get_all_scenes(stash, settings, per_page=int(settings.get("per_page", 1000)))
    total_scenes = len(scenes)
    organized_scenes = 0
    total_moved = 0

    if total_scenes == 0:
        msg = "No scenes found"
        log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] {msg}")
        task_log(msg, progress=1.0)
        return msg

    for index, scene in enumerate(scenes, start=1):
        sid = int(scene["id"])

        if not scene.get("organized") and settings.get("move_only_organized"):
            # 仍然更新一下进度条
            progress = index / total_scenes
            task_log(f"Skipping unorganized scene {sid} ({index}/{total_scenes})", progress=progress)
            continue

        organized_scenes += 1
        log.info(f"Processing organized scene id={sid} title={scene.get('title')!r}")
        progress = index / total_scenes
        task_log(f"Processing scene {sid} ({index}/{total_scenes})", progress=progress)

        moved = process_scene(scene, settings)
        total_moved += moved

    msg = (
        f"Scanned {total_scenes} scenes, "
        f"organized=True: {organized_scenes}, "
        f"moved files: {total_moved}, dry_run={dry_run}"
    )
    log.info(f"[{settings.get('PLUGIN_ID', 'auto-move-organized')}] {msg}")
    task_log(msg, progress=1.0)
    return msg
