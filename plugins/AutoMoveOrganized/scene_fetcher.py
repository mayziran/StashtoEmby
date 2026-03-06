# -*- coding: utf-8 -*-
"""
scene_fetcher.py - 场景获取模块

负责从 Stash API 获取场景数据
- 统一的 Scene Fragment
- 获取单个场景
- 分页获取所有场景
"""

import re
from typing import Any, Dict, List

import stashapi.log as log
from stashapi.stashapp import StashInterface

# 插件 ID
PLUGIN_ID = "auto-move-organized"

# 统一的 Scene Fragment，用于获取完整的场景信息（包含 NFO 写入需要的所有字段）
# Task 模式和 Hook 模式都使用这个 Fragment
SCENE_FRAGMENT = """
        id
        title
        code
        details
        director
        urls
        date
        rating100
        o_counter
        organized
        interactive
        interactive_speed
        resume_time
        play_duration
        play_count

        files {
          id
          path
          size
          mod_time
          duration
          video_codec
          audio_codec
          width
          height
          frame_rate
          bit_rate
          fingerprints {
            type
            value
          }
        }

        paths {
          screenshot
          preview
          stream
          webp
          vtt
          sprite
          funscript
          interactive_heatmap
          caption
        }

        scene_markers {
          id
          title
          seconds
          primary_tag {
            id
            name
          }
        }

        galleries {
          id
          files {
            path
          }
          folder {
            path
          }
          title
        }

        studio {
          id
          name
          image_path
        }

        groups {
          group {
            id
            name
            front_image_path
          }
          scene_index
        }

        tags {
          id
          name
        }

        performers {
          id
          name
          disambiguation
          gender
          favorite
          image_path
          gender
          birthdate
          country
          eye_color
          height_cm
          measurements
          fake_tits
        }

        stash_ids {
          endpoint
          stash_id
          updated_at
        }
"""


def get_single_scene(stash: StashInterface, scene_id: int) -> Dict[str, Any] | None:
    """
    获取单个场景的完整信息（使用统一的 Fragment）
    Task 模式和 Hook 模式都使用这个函数
    """
    try:
        scene = stash.find_scene(scene_id, fragment=SCENE_FRAGMENT)
        return scene
    except Exception as e:
        log.error(f"Failed to fetch scene {scene_id}: {e}")
        return None


def get_all_scenes(stash: StashInterface, settings: Dict[str, Any], per_page: int = 1000) -> List[Dict[str, Any]]:
    """
    使用 stash.find_scenes 分页把所有 scenes 一次性拉成一个 list 返回，
    方便在 IDE 里直接看变量调试。
    """
    all_scenes: List[Dict[str, Any]] = []
    page = 1

    fragment = SCENE_FRAGMENT

    # 检查是否设置了源目录映射
    source_target_mapping = settings.get("source_target_mapping", "").strip()
    query_f = None

    if source_target_mapping and '->' in source_target_mapping:
        # 有映射：筛选源路径下的文件
        parts = source_target_mapping.split('->', 1)
        if len(parts) == 2:
            source_base_dir = parts[0].strip()
            if source_base_dir:
                # 使用正则表达式筛选源路径下的文件
                # 转义路径中的特殊字符，确保精确匹配（防止"已整理"匹配"已整理 2"）
                escaped_path = re.escape(source_base_dir)
                query_f = {
                    "path": {
                        "modifier": "MATCHES_REGEX",
                        "value": f"^({escaped_path})(/.*|$)"
                    }
                }
    else:
        # 没有映射：筛选不在目标路径的文件
        target_root = settings.get("target_root", "").strip()
        if target_root:
            # 使用正则表达式筛选不在目标路径的文件
            # 使用 re.escape 转义特殊字符，确保精确匹配
            escaped_target = re.escape(target_root)
            query_f = {
                "path": {
                    "modifier": "NOT_MATCHES_REGEX",
                    "value": f"^({escaped_target})(/.*|$)"
                }
            }

    # 构建查询过滤条件
    # 根据 move_only_organized 配置决定是否过滤 organized
    move_only_organized = settings.get("move_only_organized", True)
    
    query_filter = {
        "page": page,
        "per_page": per_page,
    }
    
    # 只有当 move_only_organized=true 时才在 API 层面过滤 organized
    # 使用 f 参数（SceneFilterType）而不是 filter 参数
    if move_only_organized:
        if query_f:
            # 已有路径过滤，添加到现有过滤条件中
            query_f["organized"] = True
        else:
            # 没有路径过滤，创建新的 organized 过滤
            query_f = {"organized": True}
        log.info(f"[{PLUGIN_ID}] Using organized filter: organized=True")
    else:
        log.info(f"[{PLUGIN_ID}] move_only_organized=false, fetching all scenes")

    while True:
        log.info(f"[{PLUGIN_ID}] Fetching scenes page={page}, per_page={per_page}")
        if query_f:
            log.info(f"[{PLUGIN_ID}] Using path filter: {query_f}")

        page_scenes = stash.find_scenes(
            f=query_f,  # 使用 f 参数传递过滤条件
            filter=query_filter,
            fragment=fragment,
        )

        # 这里 page_scenes 正如你截图，是一个 list[dict]
        if not page_scenes:
            log.info(f"[{PLUGIN_ID}] No more scenes at page={page}, stop paging")
            break

        log.info(f"[{PLUGIN_ID}] Got {len(page_scenes)} scenes in page={page}")
        all_scenes.extend(page_scenes)

        # 更新页码和过滤器（除了第一页，后续页码需要更新）
        page += 1
        query_filter["page"] = page

    log.info(f"[{PLUGIN_ID}] Total scenes fetched: {len(all_scenes)}")
    return all_scenes
