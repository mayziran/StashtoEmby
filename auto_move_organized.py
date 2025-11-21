#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import sys
from typing import Dict, Any, List

import stashapi.log as log
from stashapi.stashapp import StashInterface

# 必须和 YAML 里的 id 对应
PLUGIN_ID = "auto-move-organized"


def read_input() -> Dict[str, Any]:
    """从 stdin 读取 Stash 插件 JSON 输入。"""
    raw = sys.stdin.read()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception as e:
        log.error(f"Failed to parse JSON input: {e}")
        return {}


def connect_stash(server_connection: Dict[str, Any]) -> StashInterface:
    """
    用 stashapi 的 StashInterface 建立连接。

    server_connection 就是 docs 里给的结构：
    {
        "Scheme": "...",
        "Port": ...,
        "SessionCookie": {...},
        "Dir": "...",
        "PluginDir": "..."
    }
    """
    return StashInterface(server_connection)


def load_settings(stash: StashInterface) -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings。
    """
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "target_root": "",
            "filename_template": "{original_basename}",
            "move_only_organized": True,
            "dry_run": False,
        }

    plugins_settings = cfg.get("plugins", {}).get("auto_move_organized", {})

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    target_root = _get_val("target_root", "")
    filename_template = _get_val("filename_template", "{original_basename}")
    move_only_org = bool(_get_val("move_only_organized", True))
    dry_run = bool(_get_val("dry_run", False))

    log.info(
        f"Loaded settings: target_root='{target_root}', "
        f"template='{filename_template}', move_only_organized={move_only_org}, dry_run={dry_run}"
    )

    return {
        "target_root": target_root,
        "filename_template": filename_template,
        "move_only_organized": move_only_org,
        "dry_run": dry_run,
    }


def safe_segment(segment: str) -> str:
    """
    简单清理路径段，避免出现奇怪字符。
    你可以按需要改规则。
    """
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    # 去掉常见非法字符
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    # 防止空字符串
    return segment or "_"


def build_target_path(
    scene: Dict[str, Any],
    file_path: str,
    settings: Dict[str, Any],
) -> str:
    """
    根据模板生成目标路径（绝对路径）。

    支持的占位符：
      {id}                -> scene id
      {scene_title}       -> 场景标题
      {scene_date}        -> 场景日期（原始字符串）
      {studio}            -> Studio 名
      {performers}        -> Performer 名（逗号分隔）
      {original_basename} -> 原始文件名（含扩展名）
      {original_name}     -> 原始文件名（不含扩展名）
      {ext}               -> 扩展名（不含点）
    """

    target_root = settings["target_root"].strip()
    template = settings["filename_template"].strip()

    if not target_root:
        raise RuntimeError("目标目录(target_root)未配置")

    # 解析文件名
    original_basename = os.path.basename(file_path)
    original_name, ext = os.path.splitext(original_basename)
    ext = ext.lstrip(".")

    scene_id = scene.get("id")
    scene_title = scene.get("title") or ""
    scene_date = scene.get("date") or ""

    studio_name = ""
    studio = scene.get("studio")
    if isinstance(studio, dict):
        studio_name = studio.get("name") or ""

    performer_names: List[str] = []
    for p in scene.get("performers", []):
        if isinstance(p, dict) and p.get("name"):
            performer_names.append(p["name"])

    performers_str = ", ".join(performer_names)

    vars_map = {
        "id": scene_id,
        "scene_title": scene_title,
        "scene_date": scene_date,
        "studio": studio_name,
        "performers": performers_str,
        "original_basename": original_basename,
        "original_name": original_name,
        "ext": ext,
    }

    # 先做模板替换
    try:
        rel_path = template.format(**vars_map)
    except Exception as e:
        raise RuntimeError(f"命名模板解析失败: {e}")

    # 把路径里的每一段都 sanitize 一下
    rel_parts = []
    for part in re.split(r"[\\/]+", rel_path):
        if part:
            rel_parts.append(safe_segment(part))

    rel_path_clean = os.path.join(*rel_parts) if rel_parts else original_basename

    # 如果模板里没有扩展名，就保留原始扩展名
    if not os.path.splitext(rel_path_clean)[1] and ext:
        rel_path_clean = f"{rel_path_clean}.{ext}"

    abs_target = os.path.join(target_root, rel_path_clean)
    return abs_target


def move_file(scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """执行单个文件的移动操作。返回是否真的移动了。"""
    src = file_obj.get("path")
    if not src:
        log.warning(f"File with id={file_obj.get('id')} has no path, skip")
        return False

    try:
        dst = build_target_path(scene, src, settings)
    except Exception as e:
        log.error(f"构建目标路径失败: {e}")
        return False

    if src == dst:
        log.info(f"源路径和目标路径相同，跳过: {src}")
        return False

    if not os.path.exists(src):
        log.warning(f"源文件不存在，跳过: {src}")
        return False

    if os.path.exists(dst):
        log.warning(f"目标文件已存在，跳过: {dst}")
        return False

    dst_dir = os.path.dirname(dst)
    try:
        if not settings["dry_run"]:
            os.makedirs(dst_dir, exist_ok=True)
            # 使用 replace 确保跨设备也能工作（Python 会自动选择 copy+remove）
            shutil.move(src, dst)
        log.info(f"Moved file: '{src}' -> '{dst}' (dry_run={settings['dry_run']})")
        return True
    except Exception as e:
        log.error(f"移动文件失败 '{src}' -> '{dst}': {e}")
        return False


def process_scene(stash: StashInterface, scene_id: int, settings: Dict[str, Any]) -> int:
    """
    根据 scene_id 处理该场景下的文件。
    返回移动的文件数量。
    """
    try:
        scene = stash.find_scene(scene_id)
    except Exception as e:
        log.error(f"find_scene({scene_id}) 失败: {e}")
        return 0

    if not scene:
        log.warning(f"Scene {scene_id} not found")
        return 0

    files = scene.get("files", []) or []
    moved_count = 0

    for f in files:
        if settings["move_only_organized"]:
            # file 对象上通常有 organized 字段
            if not f.get("organized"):
                continue

        if move_file(scene, f, settings):
            moved_count += 1

    log.info(f"Scene {scene_id}: moved {moved_count} files")
    return moved_count

def get_all_scenes(stash: StashInterface, per_page: int = 1000) -> List[Dict[str, Any]]:
    """
    使用 stash.find_scenes 分页把所有 scenes 一次性拉成一个 list 返回，
    方便在 IDE 里直接看变量调试。
    """
    all_scenes: List[Dict[str, Any]] = []
    page = 1

    fragment = """
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

    while True:
        log.info(f"[{PLUGIN_ID}] Fetching scenes page={page}, per_page={per_page}")
        page_scenes = stash.find_scenes(
            f=None,
            filter={"page": page, "per_page": per_page},
            fragment=fragment,
        )

        # 这里 page_scenes 正如你截图，是一个 list[dict]
        if not page_scenes:
            log.info(f"[{PLUGIN_ID}] No more scenes at page={page}, stop paging")
            break

        log.info(f"[{PLUGIN_ID}] Got {len(page_scenes)} scenes in page={page}")
        all_scenes.extend(page_scenes)
        page += 1

    log.info(f"[{PLUGIN_ID}] Total scenes fetched: {len(all_scenes)}")
    return all_scenes


def handle_hook_or_task(stash: StashInterface, args: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    统一入口：
    - 如果是 Hook（Scene.Create.Post / Scene.Update.Post 等），只处理当前 Scene
    - 如果是 Task（手动在 Tasks 页面点执行），遍历所有 Scene，移动 organized=true 的
    """
    # 你的 YAML 里一般会定义 args 里的字段，比如 mode 等
    mode = (args or {}).get("mode") or "all"
    dry_run = bool(settings.get("dry_run"))

    # 1) Hook 场景：如果有 hookContext.id，就只处理这个 scene
    hook_ctx = (args or {}).get("hookContext") or {}
    scene_id = hook_ctx.get("id") or hook_ctx.get("scene_id")
    if scene_id is not None:
        scene_id = int(scene_id)
        log.info(f"[{PLUGIN_ID}] Hook mode, processing single scene id={scene_id}")

        # 单个 scene 的详细信息可以重新用 find_scene 拉一下，也可以直接用 hookContext 里带的
        scene = stash.find_scene(scene_id, fragment="""
            id
            organized
            title
            date
            studio { name }
            performers { name }
            files { id path }
        """)

        if not scene:
            return f"Scene {scene_id} not found"

        if not scene.get("organized"):
            log.info(f"Scene {scene_id} is not organized=True, skip")
            return f"Scene {scene_id} not organized, skipped"

        moved = process_scene(stash, scene, settings)
        return f"Processed scene {scene_id}, moved {moved} file(s), dry_run={dry_run}"

    # 2) Task 场景：遍历所有 scene
    log.info(f"[{PLUGIN_ID}] Task mode '{mode}': scanning all scenes and moving organized=True ones")

    total_scenes = 0
    organized_scenes = 0
    total_moved = 0

    scenes = get_all_scenes(stash, per_page=int(settings.get("per_page", 1000)))

    for scene in scenes:
        total_scenes += 1
        sid = int(scene["id"])
        # 保存json, 调试用
        with open(f'scene-{sid}.json', 'w', encoding='utf-8') as f:
            json.dump(scene, f, indent=2,ensure_ascii=False)

        if not scene.get("organized"):
            continue

        # organized_scenes += 1
        # sid = int(scene["id"])
        #
        #
        # log.info(f"Processing organized scene id={sid} title={scene.get('title')!r}")
        # moved = process_scene(stash, sid, settings)
        # total_moved += moved

    msg = (
        f"Scanned {total_scenes} scenes, "
        f"organized=True: {organized_scenes}, "
        f"moved files: {total_moved}, dry_run={dry_run}"
    )
    log.info(f"[{PLUGIN_ID}] {msg}")
    return msg




def read_input_file():
    with open('input.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    # json_input = read_input()  # 插件运行时从 stdin 读
    json_input = read_input_file()  # 调试时从文件读
    print(json_input)
    log.info(f"Plugin input: {json_input}")
    server_conn = json_input.get("server_connection") or {}

    if not server_conn:
        out = {"error": "Missing server_connection in input"}
        print(json.dumps(out))
        return
    
    if server_conn.get("Host") == '0.0.0.0':
        server_conn["Host"] = "localhost"

    args = json_input.get("args") or {}

    stash = connect_stash(server_conn)
    settings = load_settings(stash)



    try:
        msg = handle_hook_or_task(stash, args, settings)
        out = {"output": msg}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    # 输出必须是单行 JSON
    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
