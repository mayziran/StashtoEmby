# -*- coding: utf-8 -*-
"""
file_mover.py - 文件移动模块

负责文件移动相关操作
- 使用 GraphQL API 移动文件
- 移动文件并处理后处理
- 处理场景的所有文件
- 清理空目录
- 移动字幕文件
"""

import os
import shutil
from typing import Any, Dict

import stashapi.log as log
from stashapi.stashapp import StashInterface

from path_builder import build_target_path, build_target_path_for_existing_file


# 常见字幕扩展名
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}


def move_file_with_graphql(stash: StashInterface, file_id: str, dest_folder: str, dest_basename: str) -> bool:
    """使用 GraphQL API 移动文件"""
    mutation = """
        mutation MoveFiles($input: MoveFilesInput!) {
            moveFiles(input: $input)
        }
    """
    variables = {
        "input": {
            "ids": [file_id],
            "destination_folder": dest_folder,
            "destination_basename": dest_basename
        }
    }

    try:
        result = stash.call_GQL(mutation, variables)
        success = result.get("moveFiles", False)
        return success
    except Exception as e:
        log.error(f"GraphQL moveFiles 调用失败：{e}")
        return False


def move_file_with_suffix_handling(scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """执行单个文件的移动操作。返回是否真的移动了。"""
    src = file_obj.get("path")
    file_id = file_obj.get("id")

    if not src:
        log.warning(f"File with id={file_obj.get('id')} has no path, skip")
        return False

    if not file_id:
        log.warning(f"File with path={src} has no id, skip")
        return False

    try:
        dst = build_target_path(scene, src, file_obj, settings)
    except Exception as e:
        log.error(f"构建目标路径失败：{e}")
        return False

    dst_dir = os.path.dirname(dst)
    dst_basename = os.path.basename(dst)

    # 记录原始目录，用于后续清理空目录
    original_dir = os.path.dirname(src)

    try:
        if not settings.get("dry_run"):
            # 使用 GraphQL API 移动文件，这样 Stash 会自动更新数据库
            success = move_file_with_graphql(settings.get("stash_interface"), file_id, dst_dir, dst_basename)
            if not success:
                log.error(f"GraphQL moveFiles failed for file id={file_id}")
                return False
        else:
            # dry_run 模式下创建目标目录
            os.makedirs(dst_dir, exist_ok=True)

        # 执行后处理（如移动字幕、生成 NFO 等）
        # 使用最终的目标路径
        final_dst = os.path.join(dst_dir, dst_basename)
        try:
            # 在 dry_run 模式下，我们使用原始路径作为源路径，目标路径作为目标路径
            # 在非 dry_run 模式下，文件已经被 GraphQL 移动，但我们仍需执行后处理
            post_process_moved_file(src, final_dst, scene, settings)
        except Exception as post_e:
            log.error(f"移动后处理失败 '{final_dst}': {post_e}")

        # 清理原来的空目录
        if not settings.get("dry_run"):
            # 获取配置来确定基础路径（目标目录或映射的目标目录）
            source_target_mapping = settings.get("source_target_mapping", "").strip()
            base_path = ""

            if source_target_mapping and '->' in source_target_mapping:
                # 有映射：使用映射的目标目录
                parts = source_target_mapping.split('->', 1)
                if len(parts) == 2:
                    base_path = parts[1].strip()
            else:
                # 无映射：使用目标根目录
                base_path = settings.get("target_root", "").strip()

            if base_path:
                # 判断是否应该清理目录
                is_moving_from_target_dir = should_clean_directory(original_dir, settings)

                remove_empty_parent_dirs(original_dir, base_path, source_target_mapping, is_moving_from_target_dir)

        log.info(f"Moved file: '{src}' -> '{final_dst}' (dry_run={settings.get('dry_run')})")
        return True
    except Exception as e:
        log.error(f"移动文件失败 '{src}' -> '{final_dst}': {e}")
        return False


def move_file(scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """执行单个文件的移动操作。返回是否真的移动了。"""
    return move_file_with_suffix_handling(scene, file_obj, settings)


def process_scene(scene: Dict[str, Any], settings: Dict[str, Any]) -> int:
    """
    根据给定的 scene 对象处理其下的文件。
    返回移动的文件数量。
    """
    if not scene:
        log.warning("Got empty scene object, skip")
        return 0

    scene_id = scene.get("id")
    files = scene.get("files") or []

    if not files:
        log.info(f"Scene {scene_id} has no files, skip")
        return 0

    # 多文件模式处理
    multi_file_mode = settings.get("multi_file_mode", "all")

    if len(files) > 1:
        if multi_file_mode == "skip":
            log.info(f"Scene {scene_id} has {len(files)} files, skipping due to multi_file_mode=skip")
            return 0
        elif multi_file_mode == "primary_only":
            log.debug(f"Scene {scene_id} has {len(files)} files, processing only primary file")
            files_to_process = [files[0]]
        else:  # "all" mode - process all files
            log.debug(f"Scene {scene_id} has {len(files)} files, processing all")
            files_to_process = files
    else:
        files_to_process = files

    moved_count = 0

    # API 和上层已经根据 move_only_organized 配置过滤了，所以直接处理所有文件
    for idx, f in enumerate(files_to_process):
        # 调用 move_file_with_suffix_handling
        if move_file_with_suffix_handling(scene, f, settings):
            moved_count += 1

    log.info(f"Scene {scene_id}: moved {moved_count} files")
    return moved_count


def should_clean_directory(original_dir: str, settings: Dict[str, Any]) -> bool:
    """
    判断是否应该清理指定目录
    - 有映射：由 remove_empty_parent_dirs 内部处理
    - 无映射：只有当原始目录在目标目录内时才清理
    """
    source_target_mapping = settings.get("source_target_mapping", "").strip()

    # 有映射时，由清理函数内部处理逻辑
    if source_target_mapping:
        return True

    # 无映射时，只有当原始目录在目标根目录内时才清理
    target_root = settings.get("target_root", "").strip()
    if not target_root:
        return False

    normalized_original_dir = os.path.normpath(original_dir)
    normalized_target_root = os.path.normpath(target_root)
    return normalized_original_dir.startswith(normalized_target_root + os.sep)


def _clean_up_to_stop_directory(normalized_dir: str, normalized_source: str, first_subdir: str) -> None:
    """
    从指定目录向上清理空目录，直到停止目录
    """
    # 计算停止清理的目录
    stop_dir = os.path.join(normalized_source, first_subdir)

    # 从当前目录向上清理，但不超过停止目录
    current = normalized_dir
    while current != stop_dir and os.path.dirname(current) != current:
        if os.path.isdir(current) and not os.listdir(current):
            os.rmdir(current)
            log.info(f"Removed empty directory: {current}")
            current = os.path.dirname(current)
        else:
            break

    # 检查停止目录本身是否需要清理
    if os.path.isdir(stop_dir) and current == stop_dir and not os.listdir(stop_dir):
        os.rmdir(stop_dir)
        log.info(f"Removed empty stop directory: {stop_dir}")


def _handle_mapped_directory_cleanup(directory: str, source_target_mapping: str) -> bool:
    """
    处理有映射时的目录清理逻辑
    返回是否已处理
    """
    if source_target_mapping and '->' in source_target_mapping:
        parts = source_target_mapping.split('->', 1)
        if len(parts) == 2:
            source_base_dir = parts[0].strip()
            if source_base_dir:
                normalized_source = os.path.normpath(source_base_dir)
                normalized_dir = os.path.normpath(directory)

                # 检查目录是否在源基础目录下
                if normalized_dir.startswith(normalized_source + os.sep):
                    # 获取相对于源目录的第一级子目录
                    rel_path = os.path.relpath(normalized_dir, normalized_source)
                    first_subdir = rel_path.split(os.sep)[0] if rel_path else ""

                    # 如果是源基础目录本身，跳过清理
                    if not first_subdir:
                        return True

                    _clean_up_to_stop_directory(normalized_dir, normalized_source, first_subdir)
                    return True
    return False


def _handle_unmapped_directory_cleanup(directory: str, base_path: str, is_moving_from_target_dir: bool) -> None:
    """
    处理无映射时的目录清理逻辑
    """
    # 如果文件不是从目标目录内移动（即从外部移动到目标目录），则不清理
    if not is_moving_from_target_dir:
        log.debug(f"Skip cleaning for file moved from outside target directory: {directory}")
        return

    # 通用清理逻辑：从当前目录向上清理到 base_path
    dir_path = os.path.normpath(directory)
    current = dir_path
    while current != base_path and os.path.dirname(current) != current:
        if os.path.isdir(current) and not os.listdir(current):
            os.rmdir(current)
            log.info(f"Removed empty directory: {current}")
            current = os.path.dirname(current)
        else:
            break


def remove_empty_parent_dirs(directory: str, base_path: str, source_target_mapping: str = None, is_moving_from_target_dir: bool = False) -> None:
    """
    清理空的父目录
    - 有映射时：只清理源目录的下一级（如 /data/待整理/111），不清理到 /data/待整理
    - 无映射时：
        - 从外部移动到目标目录：不清理
        - 目标目录内重新组织：清理到目标根目录
    """
    try:
        # 有映射的情况：只清理到源目录的下一级
        if _handle_mapped_directory_cleanup(directory, source_target_mapping):
            return

        # 无映射的情况：根据文件来源决定是否清理
        _handle_unmapped_directory_cleanup(directory, base_path, is_moving_from_target_dir)

    except Exception as e:
        log.error(f"Error removing empty parent directories: {e}")


def remove_old_metadata(file_path: str, settings: Dict[str, Any]) -> None:
    """
    删除旧的 NFO 和封面文件
    """
    try:
        # 删除 NFO 文件
        nfo_path = os.path.splitext(file_path)[0] + ".nfo"
        if os.path.exists(nfo_path):
            if not settings.get("dry_run"):
                os.remove(nfo_path)
                log.info(f"Removed old NFO file: {nfo_path}")
            else:
                log.info(f"[dry_run] Would remove old NFO file: {nfo_path}")

        # 删除封面文件
        video_dir = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")

        for ext in exts:
            poster_candidate = os.path.join(video_dir, f"{base_name}-poster{ext}")
            if os.path.exists(poster_candidate):
                if not settings.get("dry_run"):
                    os.remove(poster_candidate)
                    log.info(f"Removed old poster file: {poster_candidate}")
                else:
                    log.info(f"[dry_run] Would remove old poster file: {poster_candidate}")
    except Exception as e:
        log.error(f"Error removing old metadata for {file_path}: {e}")


def regenerate_file_at_target(file_obj: Dict[str, Any], scene: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    重新生成文件到目标位置（重新命名、生成 NFO 和封面）
    """
    try:
        file_path = file_obj.get("path", "")
        file_id = file_obj.get("id", "")

        if not file_path or not file_id:
            return False

        # 记录原始目录，用于后续清理空目录
        original_dir = os.path.dirname(file_path)

        # 计算新的目标路径
        # 对于已经在目标目录的文件，使用专门的函数来保留原始映射关系
        new_target_path = build_target_path_for_existing_file(file_path, scene, file_obj, settings)

        new_target_dir = os.path.dirname(new_target_path)
        new_target_basename = os.path.basename(new_target_path)

        # 使用 GraphQL API 移动文件到新位置
        if not settings.get("dry_run"):
            success = move_file_with_graphql(settings.get("stash_interface"), file_id, new_target_dir, new_target_basename)
            if not success:
                log.error(f"GraphQL moveFiles failed for file id={file_id}")
                return False
        else:
            # dry_run 模式下创建目标目录
            os.makedirs(new_target_dir, exist_ok=True)
            log.info(f"[dry_run] Would move file: '{file_path}' -> '{new_target_path}'")

        # 执行后处理（生成新的 NFO 和封面）
        post_process_moved_file(file_path, new_target_path, scene, settings)

        # 清理原来的空目录
        if not settings.get("dry_run"):
            # 获取配置来确定基础路径（目标目录或映射的目标目录）
            source_target_mapping = settings.get("source_target_mapping", "").strip()
            base_path = ""

            if source_target_mapping and '->' in source_target_mapping:
                # 有映射：使用映射的目标目录
                parts = source_target_mapping.split('->', 1)
                if len(parts) == 2:
                    base_path = parts[1].strip()
            else:
                # 无映射：使用目标根目录
                base_path = settings.get("target_root", "").strip()

            if base_path:
                # 判断是否应该清理目录
                is_moving_from_target_dir = should_clean_directory(original_dir, settings)

                remove_empty_parent_dirs(original_dir, base_path, source_target_mapping, is_moving_from_target_dir)

        log.info(f"Regenerated file at new location: '{file_path}' -> '{new_target_path}'")
        return True
    except Exception as e:
        log.error(f"Error regenerating file {file_obj.get('path', '')}: {e}")
        return False


def regenerate_metadata_only(file_path: str, scene: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    仅重新生成元数据（NFO 和封面），不移动文件
    """
    try:
        if not settings.get("dry_run"):
            # 重新生成 NFO 和封面到当前位置
            post_process_moved_file(file_path, file_path, scene, settings)
            log.info(f"Regenerated metadata for file at same location: '{file_path}'")
        else:
            log.info(f"[dry_run] Would regenerate metadata for file at same location: '{file_path}'")
            # 在 dry_run 模式下也调用，以便显示将要执行的操作
            post_process_moved_file(file_path, file_path, scene, settings)

        return True
    except Exception as e:
        log.error(f"Error regenerating metadata for {file_path}: {e}")
        return False


def move_related_subtitle_files(
    src_video_path: str,
    dst_video_path: str,
    settings: Dict[str, Any],
) -> None:
    """
    如果源目录下存在与视频同名的字幕文件，一并移动到目标目录，
    并按新视频文件名重命名，方便 Emby 识别。

    例如：
      源视频：/path/OldName.mkv
      源字幕：/path/OldName.srt, /path/OldName.chs.srt
      目标视频：/new/Studio.2025-01-01.NewName.mkv

      则字幕会移动为：
        /new/Studio.2025-01-01.NewName.srt
        /new/Studio.2025-01-01.NewName.chs.srt
    """
    src_dir = os.path.dirname(src_video_path)
    dst_dir = os.path.dirname(dst_video_path)

    if not src_dir or not os.path.isdir(src_dir):
        return

    src_base = os.path.basename(src_video_path)
    dst_base = os.path.basename(dst_video_path)
    src_stem, _ = os.path.splitext(src_base)
    dst_stem, _ = os.path.splitext(dst_base)

    # 源文件名为空，直接返回
    if not src_stem or not dst_stem:
        return

    dry_run = bool(settings.get("dry_run"))
    moved_count = 0

    try:
        for name in os.listdir(src_dir):
            full_src = os.path.join(src_dir, name)
            if not os.path.isfile(full_src):
                continue

            _, ext = os.path.splitext(name)
            if ext.lower() not in SUBTITLE_EXTS:
                continue

            # 只处理与原视频同名（含语言后缀）的字幕
            # 允许类似 OldName.srt / OldName.chs.srt / OldName.en.srt
            if not name.startswith(src_stem):
                continue

            suffix = name[len(src_stem):]
            new_name = dst_stem + suffix
            full_dst = os.path.join(dst_dir, new_name)

            if full_src == full_dst:
                continue

            # 目标已存在则跳过，避免覆盖
            if os.path.exists(full_dst):
                log.info(f"目标字幕已存在，跳过：'{full_dst}'")
                continue

            if dry_run:
                log.info(f"[dry_run] Would move subtitle: '{full_src}' -> '{full_dst}'")
            else:
                os.makedirs(dst_dir, exist_ok=True)
                shutil.move(full_src, full_dst)
                log.info(f"Moved subtitle: '{full_src}' -> '{full_dst}'")

            moved_count += 1

        if moved_count > 0:
            log.info(
                f"共移动 {moved_count} 个字幕文件，"
                f"源目录='{src_dir}', 目标目录='{dst_dir}'"
            )
    except Exception as e:
        log.error(f"移动字幕文件时出错：{e}")


def post_process_moved_file(
    src_video_path: str,
    dst_video_path: str,
    scene: Dict[str, Any],
    settings: Dict[str, Any],
) -> None:
    """
    文件移动之后的后续处理：
    1. 移动并重命名同名字幕文件
    2. 写 NFO
    3. 下载场景封面图到视频目录（folder.jpg）
    """
    from metadata_handler import write_nfo_for_scene, download_scene_art
    
    move_related_subtitle_files(src_video_path, dst_video_path, settings)

    # 后续处理都基于新视频路径
    write_nfo_for_scene(dst_video_path, scene, settings)
    download_scene_art(dst_video_path, scene, settings)


def is_file_in_target_location(file_path: str, scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    检查文件是否在目标目录树下（包括子目录）
    """
    try:
        # 获取目标根目录
        # 如果有映射，使用映射的目标目录；否则使用 target_root
        source_target_mapping = settings.get("source_target_mapping", "").strip()
        target_root = ""

        if source_target_mapping and '->' in source_target_mapping:
            # 有映射：使用映射的目标目录
            parts = source_target_mapping.split('->', 1)
            if len(parts) == 2:
                target_root = parts[1].strip()
        else:
            # 无映射：使用 target_root
            target_root = settings.get("target_root", "").strip()

        if not target_root:
            return False

        # 规范化路径
        normalized_current = os.path.normpath(file_path)
        normalized_target_root = os.path.normpath(target_root)

        # 检查当前路径是否在目标根目录下
        return normalized_current.startswith(normalized_target_root + os.sep) or normalized_current == normalized_target_root
    except Exception:
        # 如果计算失败，假设不在目标位置
        return False


def should_regenerate_metadata(file_path: str, scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    检查是否需要重新生成元数据（NFO 和封面）
    对于已经在目标路径的文件，总是需要重新生成元数据和封面
    """
    # 对于已经在目标路径的文件，总是需要重新生成元数据和封面
    return True
