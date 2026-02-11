#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
import stashapi.log as log
from ai_translate import translate_title_and_plot
from stashapi.stashapp import StashInterface

# 必须和 YAML 里的 id 对应
PLUGIN_ID = "auto-move-organized"

# 常见字幕扩展名
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}

_AUTO_INSTALL_ATTEMPTED: set[str] = set()


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
        log.error(f"[{PLUGIN_ID}] Failed to write task log: {e}")


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
    从 Stash 配置里读取本插件的 settings，并把常用的 AI 翻译配置也一并返回。
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
    # 调试用：保存一份完整配置到本地，结构与 stash_configuration.json 相同
    # try:
    #     with open("stash_configuration.json", "w", encoding="utf-8") as f:
    #         json.dump(cfg, f, ensure_ascii=False, indent=5)
    # except Exception:
    #     pass

    plugins_settings = cfg.get("plugins", {}).get("auto_move_organized", {})

    # 保存一份到本地，便于调试
    # with open("auto_move_organized_plugins_settings.json", "w", encoding="utf-8") as f:
    #     json.dump(plugins_settings, f, ensure_ascii=False, indent=4)

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    # 基本选项
    target_root = _get_val("target_root", "")
    filename_template = _get_val("filename_template", "{original_basename}")
    move_only_org = bool(_get_val("move_only_organized", True))
    dry_run = bool(_get_val("dry_run", False))
    write_nfo = bool(_get_val("write_nfo", True))
    download_poster = bool(_get_val("download_poster", True))
    overlay_studio_logo_on_poster = bool(_get_val("overlay_studio_logo_on_poster", False))

    # AI / 翻译 相关配置
    translate_enable = bool(_get_val("translate_enable", False))
    translate_api_base = _get_val("translate_api_base", "") or ""
    translate_api_key = _get_val("translate_api_key", "") or ""
    translate_model = _get_val("translate_model", "") or ""
    # 有些配置界面可能把布尔值和字符串混用，兼容处理
    translate_plot = bool(_get_val("translate_plot", False))
    translate_title = bool(_get_val("translate_title", False))
    # temperature 可能是字符串或数字，尝试转为 float，如果失败则保留原样
    translate_temperature = _get_val("translate_temperature", "")
    translate_prompt = _get_val("translate_prompt", "")

    # 从全局配置中获取 Stash API Key（对应 stash_configuration.json.general.apiKey）
    stash_api_key = ""
    try:
        stash_api_key = cfg.get("general", {}).get("apiKey") or ""
    except Exception:
        stash_api_key = ""

    # 新增：启用 Hook 模式设置
    enable_hook_mode = bool(_get_val("enable_hook_mode", True))
    # 新增：源目录到目标目录的映射设置
    source_target_mapping = _get_val("source_target_mapping", "")

    # translate_temperature = None
    # try:
    #     if temp_raw is not None and str(temp_raw).strip() != "":
    #         translate_temperature = float(temp_raw)
    # except Exception:
    #     translate_temperature = str(temp_raw)

    log.info(
        f"Loaded settings: target_root='{target_root}', "
        f"template='{filename_template}', move_only_organized={move_only_org}, "
        f"dry_run={dry_run}, write_nfo={write_nfo}, "
        f"download_poster={download_poster}, "
        f"overlay_studio_logo_on_poster={overlay_studio_logo_on_poster}"
    )

    # 也把 AI 配置 log 出来（注意：不要在生产环境 log 明文 API key）
    log.info(
        f"Translate config: enabled={translate_enable}, api_base='{translate_api_base}', "
        f"model='{translate_model}', translate_title={translate_title}, translate_plot={translate_plot}, "
        f"temperature={translate_temperature}"
    )

    return {
        "target_root": target_root,
        "filename_template": filename_template,
        "move_only_organized": move_only_org,
        "dry_run": dry_run,
        "write_nfo": write_nfo,
        "download_poster": download_poster,
        "overlay_studio_logo_on_poster": overlay_studio_logo_on_poster,
        # AI / 翻译
        "translate_enable": translate_enable,
        "translate_api_base": translate_api_base,
        "translate_api_key": translate_api_key,
        "translate_model": translate_model,
        "translate_plot": translate_plot,
        "translate_title": translate_title,
        "translate_temperature": translate_temperature,
        "translate_prompt": translate_prompt,
        # Stash 全局 API Key，用于下载图片时避免 Session 失效问题
        "stash_api_key": stash_api_key,
        # 新增：源目录到目标目录的映射
        "source_target_mapping": source_target_mapping,
        # 新增：启用 Hook 模式
        "enable_hook_mode": enable_hook_mode,
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


def apply_multi_file_suffix(filename: str, scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
    """
    # 检查当前使用的多文件模式
    multi_file_mode = settings.get("multi_file_mode", "all")
    
    # 只在 all 模式下添加后缀，primary_only 或 skip 模式下不添加
    if multi_file_mode != "all":
        return filename
    
    # 获取场景中的所有文件
    all_files = scene.get("files", [])
    
    # 如果文件数量不大于1，不需要添加后缀
    if len(all_files) <= 1:
        return filename
    
    # 优化：创建文件ID到索引的映射，避免重复遍历
    file_id_to_index = {f.get("id"): idx for idx, f in enumerate(all_files)}
    
    # 获取当前文件在场景中的索引
    current_file_id = file_obj.get("id")
    file_index = file_id_to_index.get(current_file_id, 0)

    # 为所有文件添加后缀，包括第一个文件
    # 在文件名主体和扩展名之间添加 -cdN 后缀
    name_without_ext, file_ext = os.path.splitext(filename)
    filename = f"{name_without_ext}-cd{file_index + 1}{file_ext}"
    
    return filename


def build_absolute_url(url: str, settings: Dict[str, Any]) -> str:
    """
    把相对路径补全为带协议/主机的绝对 URL，方便下载图片。
    """
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url

    server_conn = settings.get("server_connection") or {}
    scheme = server_conn.get("Scheme", "http")
    host = server_conn.get("Host", "localhost")
    port = server_conn.get("Port")

    base = f"{scheme}://{host}"
    if port:
        base = f"{base}:{port}"

    if not url.startswith("/"):
        url = "/" + url

    return base + url


def _ensure_python_package(package: str) -> bool:
    """
    尝试在容器内自动安装第三方库。
    """
    if package in _AUTO_INSTALL_ATTEMPTED:
        return False
    _AUTO_INSTALL_ATTEMPTED.add(package)

    try:
        log.info(
            f"{package} 未安装，尝试自动安装: python -m pip install {package} --break-system-packages"
        )
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "--break-system-packages"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log.info(result.stdout or "")
        return result.returncode == 0
    except Exception as e:
        log.error(f"自动安装 {package} 失败: {e}")
        return False


def _ensure_pillow() -> bool:
    return _ensure_python_package("Pillow")


def _ensure_cairosvg() -> bool:
    return _ensure_python_package("cairosvg")


def build_template_vars(
        scene: Dict[str, Any],
        file_path: str,
        file_obj: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    根据 scene 信息和文件路径构建一份变量字典，
    既用于路径模板，也可用于 NFO 等其它场景。
    """
    original_basename = os.path.basename(file_path)
    original_name, ext = os.path.splitext(original_basename)
    ext = ext.lstrip(".")

    scene_id = scene.get("id")
    scene_title = scene.get("title") or ""
    scene_date = scene.get("date") or ""
    code = scene.get("code") or ""
    director = scene.get("director") or ""

    # 拆分日期，方便按年/月/日建目录
    date_year = ""
    date_month = ""
    date_day = ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", scene_date)
    if m:
        date_year, date_month, date_day = m.groups()

    studio_name = ""
    studio_id = ""
    studio = scene.get("studio")
    if isinstance(studio, dict):
        studio_name = studio.get("name") or ""
        studio_id = str(studio.get("id") or "")

    performer_names: List[str] = []
    for p in scene.get("performers", []):
        if isinstance(p, dict) and p.get("name"):
            performer_names.append(p["name"])

    performers_str = "-".join(performer_names)
    first_performer = performer_names[0] if performer_names else ""
    performer_count = len(performer_names)

    # tags
    tag_names: List[str] = []
    for t in scene.get("tags", []):
        if isinstance(t, dict) and t.get("name"):
            tag_names.append(t["name"])
    tags_str = ", ".join(tag_names)

    # 第一个分组名
    group_name = ""
    groups = scene.get("groups") or []
    if groups and isinstance(groups, list):
        g0 = groups[0]
        if isinstance(g0, dict):
            g = g0.get("group")
            if isinstance(g, dict):
                group_name = g.get("name") or ""

    # 评分
    rating100 = scene.get("rating100")
    rating = "" if rating100 is None else str(rating100)

    # 可能的外部 ID（例如 stashdb）
    external_id = ""
    stash_ids = scene.get("stash_ids") or []
    if stash_ids and isinstance(stash_ids, list):
        s0 = stash_ids[0]
        if isinstance(s0, dict):
            external_id = s0.get("stash_id") or ""

    width = None
    height = None
    if isinstance(file_obj, dict):
        width = file_obj.get("width")
        height = file_obj.get("height")

    resolution = ""
    quality = ""
    try:
        w = int(width) if width is not None else None
        h = int(height) if height is not None else None
        if w and h and w > 0 and h > 0:
            min_dim = min(w, h)
            if min_dim >= 4320:
                resolution, quality = "8K", "FUHD"
            elif min_dim >= 2160:
                resolution, quality = "4K", "UHD"
            elif min_dim >= 1440:
                resolution, quality = "1440p", "QHD"
            elif min_dim >= 1080:
                resolution, quality = "1080p", "FHD"
            elif min_dim >= 720:
                resolution, quality = "720p", "HD"
            elif min_dim >= 480:
                resolution, quality = "480p", "SD"
            else:
                resolution, quality = "480p", "LOW"

            if resolution == "1080p" and w >= 2000 and w < 2560:
                quality = "2K"
    except Exception:
        resolution, quality = "", ""

    return {
        "id": scene_id,
        "scene_title": scene_title,
        "scene_date": scene_date,
        "date_year": date_year,
        "date_month": date_month,
        "date_day": date_day,
        "studio": studio_name,
        "studio_name": studio_name,
        "studio_id": studio_id,
        "code": code,
        "director": director,
        "performers": performers_str,
        "first_performer": first_performer,
        "performer_count": performer_count,
        "tag_names": tags_str,
        "tags": tags_str,
        "group_name": group_name,
        "rating100": rating100,
        "rating": rating,
        "original_basename": original_basename,
        "original_name": original_name,
        "ext": ext,
        "external_id": external_id,
        "width": width,
        "height": height,
        "resolution": resolution,
        "quality": quality,
    }


def build_target_path(
        scene: Dict[str, Any],
        file_path: str,
        file_obj: Dict[str, Any],
        settings: Dict[str, Any],
) -> str:
    """
    根据模板生成目标路径（绝对路径）。

    常用占位符示例（不完全列表，实际以 build_template_vars 返回为准）：
      {id}                -> scene id
      {scene_title}       -> 场景标题
      {scene_date}        -> 场景日期（原始字符串，例如 2025-01-02）
      {date_year}         -> 场景年份
      {date_month}        -> 场景月份（两位）
      {date_day}          -> 场景日期（两位）
      {studio} / {studio_name}
      {studio_id}
      {code}
      {director}
      {performers}
      {first_performer}
      {performer_count}
      {tag_names} / {tags}
      {group_name}
      {rating} / {rating100}
      {resolution}
      {quality}
      {original_basename}
      {original_name}
      {ext}
    """

    # 获取源目录到目标目录的映射设置
    source_target_mapping = settings.get("source_target_mapping", "").strip()

    # 如果设置了源目录到目标目录的映射，则使用映射逻辑
    if source_target_mapping:
        # 解析映射设置，格式为 "源目录->目标目录" (简化版)
        if '->' in source_target_mapping:
            parts = source_target_mapping.split('->', 1)
            if len(parts) == 2:
                source_base_dir = parts[0].strip()
                target_base_dir = parts[1].strip()

                if source_base_dir and target_base_dir:
                    # 规范化路径分隔符
                    normalized_source_base = os.path.normpath(source_base_dir)
                    normalized_target_base = os.path.normpath(target_base_dir)
                    normalized_file_path = os.path.normpath(file_path)

                    # 检查文件路径是否以源基础目录开头（源目录文件）
                    if normalized_file_path.startswith(normalized_source_base + os.sep) or normalized_file_path == normalized_source_base:
                        # 计算相对于源基础目录的路径
                        rel_path_from_base = os.path.relpath(file_path, normalized_source_base)

                        # 获取第一级子目录（如果存在）
                        rel_parts = rel_path_from_base.split(os.sep)
                        first_level_dir = rel_parts[0] if rel_parts and rel_parts[0] else ""

                        # 使用模板生成文件名部分
                        template = settings["filename_template"].strip()
                        vars_map = build_template_vars(scene, file_path, file_obj)
                        original_basename = vars_map["original_basename"]
                        ext = vars_map["ext"]

                        # 避免变量中出现路径分隔符导致被当成子目录
                        vars_map_for_path = dict(vars_map)
                        for k, v in vars_map_for_path.items():
                            if isinstance(v, str):
                                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

                        # 先做模板替换
                        try:
                            filename_part = template.format(**vars_map_for_path)
                        except Exception as e:
                            raise RuntimeError(f"命名模板解析失败: {e}")

                        # 把路径里的每一段都 sanitize 一下
                        filename_parts = []
                        for part in re.split(r"[\\/]+", filename_part):
                            if part:
                                filename_parts.append(safe_segment(part))

                        filename_clean = os.path.join(*filename_parts) if filename_parts else original_basename

                        # 如果模板里没有扩展名，就保留原始扩展名
                        if not os.path.splitext(filename_clean)[1] and ext:
                            filename_clean = f"{filename_clean}.{ext}"

                        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
                        filename_clean = apply_multi_file_suffix(filename_clean, scene, file_obj, settings)

                        # 组合最终路径：目标基础目录 + 第一级子目录 + 文件名
                        abs_target = os.path.join(target_base_dir, first_level_dir, filename_clean)
                        return os.path.normpath(abs_target)
                    # 检查文件路径是否以目标基础目录开头（目标目录文件）
                    elif normalized_file_path.startswith(normalized_target_base + os.sep) or normalized_file_path == normalized_target_base:
                        # 文件已经在目标目录，使用目标目录映射逻辑
                        # 计算相对于目标基础目录的路径，获取第一级子目录
                        rel_path_from_base = os.path.relpath(file_path, normalized_target_base)
                        rel_parts = rel_path_from_base.split(os.sep)
                        first_level_dir = rel_parts[0] if rel_parts and rel_parts[0] else ""

                        # 使用模板生成文件名部分
                        template = settings["filename_template"].strip()
                        vars_map = build_template_vars(scene, file_path, file_obj)
                        original_basename = vars_map["original_basename"]
                        ext = vars_map["ext"]

                        # 避免变量中出现路径分隔符导致被当成子目录
                        vars_map_for_path = dict(vars_map)
                        for k, v in vars_map_for_path.items():
                            if isinstance(v, str):
                                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

                        # 先做模板替换
                        try:
                            filename_part = template.format(**vars_map_for_path)
                        except Exception as e:
                            raise RuntimeError(f"命名模板解析失败: {e}")

                        # 把路径里的每一段都 sanitize 一下
                        filename_parts = []
                        for part in re.split(r"[\\/]+", filename_part):
                            if part:
                                filename_parts.append(safe_segment(part))

                        filename_clean = os.path.join(*filename_parts) if filename_parts else original_basename

                        # 如果模板里没有扩展名，就保留原始扩展名
                        if not os.path.splitext(filename_clean)[1] and ext:
                            filename_clean = f"{filename_clean}.{ext}"

                        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
                        filename_clean = apply_multi_file_suffix(filename_clean, scene, file_obj, settings)

                        # 组合最终路径：目标基础目录 + 第一级子目录 + 文件名
                        abs_target = os.path.join(target_base_dir, first_level_dir, filename_clean)
                        return os.path.normpath(abs_target)
                    else:
                        # 文件既不在源目录也不在目标目录，使用标准路径构建逻辑
                        # 这种情况可能发生在文件已被移动到其他位置或路径配置变更
                        log.warning(f"文件路径 '{file_path}' 既不在源基础目录 '{source_base_dir}' 也不在目标目录 '{target_base_dir}' 下，使用标准路径构建逻辑")
                        # 使用标准的路径构建逻辑（不使用映射）
                        target_root = settings["target_root"].strip()
                        if not target_root:
                            raise RuntimeError("目标目录(target_root)未配置，无法构建路径")
                        
                        # 使用模板生成路径
                        template = settings["filename_template"].strip()
                        vars_map = build_template_vars(scene, file_path, file_obj)
                        original_basename = vars_map["original_basename"]
                        ext = vars_map["ext"]

                        # 避免变量中出现路径分隔符导致被当成子目录
                        vars_map_for_path = dict(vars_map)
                        for k, v in vars_map_for_path.items():
                            if isinstance(v, str):
                                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

                        # 先做模板替换
                        try:
                            rel_path = template.format(**vars_map_for_path)
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

                        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
                        rel_path_clean = apply_multi_file_suffix(rel_path_clean, scene, file_obj, settings)

                        abs_target = os.path.join(target_root, rel_path_clean)
                        return abs_target
                else:
                    # 如果源目录或目标目录为空，抛出错误
                    raise RuntimeError("源目录或目标目录不能为空")
            else:
                # 如果格式不正确，抛出错误
                raise RuntimeError("源目录到目标目录的映射格式错误，应为 '源目录->目标目录'")
        else:
            # 如果格式不正确，抛出错误
            raise RuntimeError("源目录到目标目录的映射格式错误，应为 '源目录->目标目录'")
    else:
        # 如果没有设置映射，使用原有逻辑
        target_root = settings["target_root"].strip()
        template = settings["filename_template"].strip()

        if not target_root:
            raise RuntimeError("目标目录(target_root)未配置")

        vars_map = build_template_vars(scene, file_path, file_obj)
        original_basename = vars_map["original_basename"]
        ext = vars_map["ext"]

        # 避免变量中出现路径分隔符导致被当成子目录
        vars_map_for_path = dict(vars_map)
        for k, v in vars_map_for_path.items():
            if isinstance(v, str):
                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

        # 先做模板替换
        try:
            rel_path = template.format(**vars_map_for_path)
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

        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
        rel_path_clean = apply_multi_file_suffix(rel_path_clean, scene, file_obj, settings)

        abs_target = os.path.join(target_root, rel_path_clean)
        return abs_target


def move_file_with_graphql(stash: StashInterface, file_id: str, dest_folder: str, dest_basename: str) -> bool:
    """使用GraphQL API移动文件"""
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
        log.error(f"GraphQL moveFiles调用失败: {e}")
        return False


def move_file_with_suffix_handling(scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any], used_paths: set, file_idx: int) -> bool:
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
        log.error(f"构建目标路径失败: {e}")
        return False

    dst_dir = os.path.dirname(dst)
    dst_basename = os.path.basename(dst)

    # 记录原始目录，用于后续清理空目录
    original_dir = os.path.dirname(src)

    try:
        if not settings.get("dry_run"):
            # 使用GraphQL API移动文件，这样Stash会自动更新数据库
            success = move_file_with_graphql(settings.get("stash_interface"), file_id, dst_dir, dst_basename)
            if not success:
                log.error(f"GraphQL moveFiles failed for file id={file_id}")
                return False
        else:
            # dry_run模式下创建目标目录
            os.makedirs(dst_dir, exist_ok=True)

        # 执行后处理（如移动字幕、生成NFO等）
        # 使用最终的目标路径
        final_dst = os.path.join(dst_dir, dst_basename)
        try:
            # 在dry_run模式下，我们使用原始路径作为源路径，目标路径作为目标路径
            # 在非dry_run模式下，文件已经被GraphQL移动，但我们仍需执行后处理
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
    return move_file_with_suffix_handling(scene, file_obj, settings, set(), 0)


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

    def _is_file_organized(file_obj: Dict[str, Any]) -> bool:
        if not settings.get("move_only_organized"):
            return True
        # 如果文件上没有，则退回到 scene 级别
        if "organized" in scene:
            return bool(scene.get("organized"))
        return False

    for idx, f in enumerate(files_to_process):
        if not _is_file_organized(f):
            continue

        # 调用move_file_with_suffix_handling
        if move_file_with_suffix_handling(scene, f, settings, set(), idx):
            moved_count += 1

    log.info(f"Scene {scene_id}: moved {moved_count} files")
    return moved_count


def get_all_scenes(stash: StashInterface, settings: Dict[str, Any], per_page: int = 1000) -> List[Dict[str, Any]]:
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
                # 转义路径中的特殊字符
                escaped_path = source_base_dir.replace('\\', '\\\\').replace('.', '\\.').replace('[', '\\[').replace(']', '\\]')
                query_f = {
                    "path": {
                        "modifier": "MATCHES_REGEX",
                        "value": f"^{escaped_path}.*"
                    }
                }
    else:
        # 没有映射：筛选不在目标路径的文件
        target_root = settings.get("target_root", "").strip()
        if target_root:
            # 使用正则表达式筛选不在目标路径的文件
            escaped_target = target_root.replace('\\', '\\\\').replace('.', '\\.').replace('[', '\\[').replace(']', '\\]')
            query_f = {
                "path": {
                    "modifier": "NOT_MATCHES_REGEX",
                    "value": f"^{escaped_target}.*"
                }
            }

    # 构建查询过滤条件
    query_filter = {"page": page, "per_page": per_page}

    while True:
        log.info(f"[{PLUGIN_ID}] Fetching scenes page={page}, per_page={per_page}")
        if query_f:
            log.info(f"[{PLUGIN_ID}] Using path filter: {query_f}")

        page_scenes = stash.find_scenes(
            f=query_f,  # 使用f参数传递过滤条件
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


def should_regenerate_metadata(file_path: str, scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    检查是否需要重新生成元数据（NFO和封面）
    对于已经在目标路径的文件，总是需要重新生成元数据和封面
    """
    # 对于已经在目标路径的文件，总是需要重新生成元数据和封面
    return True


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


def build_target_path_for_existing_file(file_path: str, scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    为已存在于目标目录的文件构建目标路径，保留目标路径下的一级子目录
    """
    try:
        # 获取源目录到目标目录的映射设置
        source_target_mapping = settings.get("source_target_mapping", "").strip()

        if source_target_mapping and '->' in source_target_mapping:
            # 有映射：使用映射逻辑，保留目标路径下的一级子目录
            parts = source_target_mapping.split('->', 1)
            if len(parts) == 2:
                target_base_dir = parts[1].strip()

                if target_base_dir:
                    # 获取当前文件在目标目录下的一级子目录
                    normalized_target_base = os.path.normpath(target_base_dir)
                    normalized_file_path = os.path.normpath(file_path)

                    # 检查文件是否在目标目录下
                    if normalized_file_path.startswith(normalized_target_base + os.sep):
                        # 计算相对于目标基础目录的路径，获取第一级子目录
                        rel_path_from_base = os.path.relpath(file_path, normalized_target_base)
                        rel_parts = rel_path_from_base.split(os.sep)
                        first_level_dir = rel_parts[0] if rel_parts and rel_parts[0] else ""

                        # 使用模板生成文件名部分（不包含路径）
                        template = settings["filename_template"].strip()
                        vars_map = build_template_vars(scene, file_path, file_obj)
                        original_basename = vars_map["original_basename"]
                        ext = vars_map["ext"]

                        # 避免变量中出现路径分隔符导致被当成子目录
                        vars_map_for_path = dict(vars_map)
                        for k, v in vars_map_for_path.items():
                            if isinstance(v, str):
                                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

                        # 先做模板替换
                        try:
                            filename_part = template.format(**vars_map_for_path)
                        except Exception as e:
                            raise RuntimeError(f"命名模板解析失败: {e}")

                        # 把路径里的每一段都 sanitize 一下
                        filename_parts = []
                        for part in re.split(r"[\\/]+", filename_part):
                            if part:
                                filename_parts.append(safe_segment(part))

                        filename_clean = os.path.join(*filename_parts) if filename_parts else original_basename

                        # 如果模板里没有扩展名，就保留原始扩展名
                        if not os.path.splitext(filename_clean)[1] and ext:
                            filename_clean = f"{filename_clean}.{ext}"

                        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
                        filename_clean = apply_multi_file_suffix(filename_clean, scene, file_obj, settings)

                        # 组合最终路径：目标基础目录 + 第一级子目录 + 文件名
                        abs_target = os.path.join(target_base_dir, first_level_dir, filename_clean)
                        return os.path.normpath(abs_target)
                    else:
                        # 如果文件不在目标目录下，这可能是因为：
                        # 1. 这是同一场景的另一个文件，位于源目录
                        # 2. 我们需要使用标准的路径构建逻辑来处理这种情况
                        # 使用build_target_path函数来处理这种情况
                        # 但现在build_target_path已经可以处理文件在源目录或目标目录的情况
                        return build_target_path(scene, file_path, file_obj, settings)
                else:
                    raise RuntimeError("目标目录不能为空")
            else:
                raise RuntimeError("源目录到目标目录的映射格式错误，应为 '源目录->目标目录'")
        else:
            # 无映射：使用 target_root
            target_root = settings.get("target_root", "").strip()

        if not target_root:
            raise RuntimeError("目标目录未配置")

        # 使用目标根目录和模板来计算路径（普通逻辑）
        template = settings["filename_template"].strip()
        vars_map = build_template_vars(scene, file_path, file_obj)
        original_basename = vars_map["original_basename"]
        ext = vars_map["ext"]

        # 避免变量中出现路径分隔符导致被当成子目录
        vars_map_for_path = dict(vars_map)
        for k, v in vars_map_for_path.items():
            if isinstance(v, str):
                vars_map_for_path[k] = v.replace("\\", "_").replace("/", "_")

        # 先做模板替换
        try:
            rel_path = template.format(**vars_map_for_path)
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

        # 为同一场景的多个文件添加区分后缀（仅在 multi_file_mode 为 "all" 时）
        rel_path_clean = apply_multi_file_suffix(rel_path_clean, scene, file_obj, settings)

        abs_target = os.path.join(target_root, rel_path_clean)
        return abs_target
    except Exception as e:
        raise RuntimeError(f"计算目标路径失败: {e}")


def remove_old_metadata(file_path: str, settings: Dict[str, Any]) -> None:
    """
    删除旧的NFO和封面文件
    """
    try:
        # 删除NFO文件
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


def remove_empty_parent_dirs(directory: str, base_path: str, source_target_mapping: str = None, is_moving_from_target_dir: bool = False) -> None:
    """
    清理空的父目录
    - 有映射时：只清理源目录的下一级（如 /data/待整理/111），不清理到 /data/待整理
    - 无映射时：
        - 从外部移动到目标目录：不清理
        - 目标目录内重新组织：清理到目标根目录
    """
    try:
        # 规范化路径
        dir_path = os.path.normpath(directory)
        base_path = os.path.normpath(base_path)
        
        # 有映射的情况：只清理到源目录的下一级
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
                            return
                        
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
                        return

        # 无映射的情况：根据文件来源决定是否清理
        if not source_target_mapping:
            # 如果文件不是从目标目录内移动（即从外部移动到目标目录），则不清理
            if not is_moving_from_target_dir:
                log.debug(f"Skip cleaning for file moved from outside target directory: {directory}")
                return

        # 通用清理逻辑：从当前目录向上清理到 base_path
        current = dir_path
        while current != base_path and os.path.dirname(current) != current:
            if os.path.isdir(current) and not os.listdir(current):
                os.rmdir(current)
                log.info(f"Removed empty directory: {current}")
                current = os.path.dirname(current)
            else:
                break
                
    except Exception as e:
        log.error(f"Error removing empty parent directories: {e}")


def regenerate_file_at_target(file_obj: Dict[str, Any], scene: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    重新生成文件到目标位置（重新命名、生成NFO和封面）
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

        # 使用GraphQL API移动文件到新位置
        if not settings.get("dry_run"):
            success = move_file_with_graphql(settings.get("stash_interface"), file_id, new_target_dir, new_target_basename)
            if not success:
                log.error(f"GraphQL moveFiles failed for file id={file_id}")
                return False
        else:
            # dry_run模式下创建目标目录
            os.makedirs(new_target_dir, exist_ok=True)
            log.info(f"[dry_run] Would move file: '{file_path}' -> '{new_target_path}'")

        # 执行后处理（生成新的NFO和封面）
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
    仅重新生成元数据（NFO和封面），不移动文件
    """
    try:
        if not settings.get("dry_run"):
            # 重新生成NFO和封面到当前位置
            post_process_moved_file(file_path, file_path, scene, settings)
            log.info(f"Regenerated metadata for file at same location: '{file_path}'")
        else:
            log.info(f"[dry_run] Would regenerate metadata for file at same location: '{file_path}'")
            # 在dry_run模式下也调用，以便显示将要执行的操作
            post_process_moved_file(file_path, file_path, scene, settings)

        return True
    except Exception as e:
        log.error(f"Error regenerating metadata for {file_path}: {e}")
        return False



def _build_requests_session(settings: Dict[str, Any]) -> requests.Session:
    """
    基于 server_connection 构建一个带 SessionCookie 的 requests 会话，
    用于从 Stash 下载截图和演员图片。
    """
    server_conn = settings.get("server_connection") or {}
    session = requests.Session()

    # 1) 使用 SessionCookie（保持向后兼容）
    cookie = server_conn.get("SessionCookie") or {}
    name = cookie.get("Name") or cookie.get("name")
    value = cookie.get("Value") or cookie.get("value")
    domain = cookie.get("Domain") or cookie.get("domain")
    path = cookie.get("Path") or cookie.get("path") or "/"

    if name and value:
        cookie_kwargs = {"path": path or "/"}
        if domain:
            cookie_kwargs["domain"] = domain
        session.cookies.set(name, value, **cookie_kwargs)

    # 2) 优先使用 Stash API Key，避免 Session 过期导致返回登录页 HTML
    api_key = settings.get("stash_api_key") or ""
    if api_key:
        session.headers["ApiKey"] = api_key

    return session


def _download_binary(url: str, dst_path: str, settings: Dict[str, Any], detect_ext: bool = False) -> bool:
    """
    从 Stash（或其它 HTTP 源）下载二进制文件到指定路径。
    """
    if not url:
        return False

    url = build_absolute_url(url, settings)
    session = _build_requests_session(settings)

    # 最多重试 3 次，简单指数退避
    max_attempts = 3
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.get(url, timeout=30, stream=True)
            resp.raise_for_status()

            # 默认直接使用调用方给的目标路径（完整文件名主体已经在上层构造好，例如包含演员名和 -poster）
            final_path = dst_path

            if detect_ext:
                content_type = (resp.headers.get("Content-Type") or "").lower()
                guessed_ext = ""

                if "image/" in content_type:
                    if "jpeg" in content_type or "jpg" in content_type:
                        guessed_ext = ".jpg"
                    elif "png" in content_type:
                        guessed_ext = ".png"
                    elif "webp" in content_type:
                        guessed_ext = ".webp"
                    elif "gif" in content_type:
                        guessed_ext = ".gif"
                    elif "svg" in content_type:
                        guessed_ext = ".svg"

                if not guessed_ext:
                    try:
                        parsed = urlparse(resp.url or url)
                        _, ext_from_url = os.path.splitext(parsed.path)
                        guessed_ext = ext_from_url
                    except Exception:
                        guessed_ext = ""

                # 这里只负责“补上扩展名”，不再尝试从 dst_path 中拆分文件名/扩展名，避免截断演员名等信息
                # 如果上层已经带了明确的图片扩展名，就保持原样；否则直接在末尾追加推断出的扩展名
                lower_path = dst_path.lower()
                has_known_ext = lower_path.endswith(".jpg") or lower_path.endswith(".jpeg") or lower_path.endswith(".png") or lower_path.endswith(".webp") or lower_path.endswith(".gif")

                if guessed_ext and not has_known_ext:
                    final_path = dst_path + guessed_ext

            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            log.info(f"Downloaded '{url}' -> '{final_path}'")
            return True
        except Exception as e:
            last_error = e
            log.error(f"下载失败(第{attempt}次) '{url}' -> '{dst_path}': {e}")
            if attempt < max_attempts:
                # 简单退避：2s, 4s
                time.sleep(2 * attempt)

    log.error(f"下载失败，已重试 {max_attempts} 次仍失败 '{url}' -> '{dst_path}': {last_error}")
    return False


def write_nfo_for_scene(video_path: str, scene: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    把 scene 的详细信息写成 Emby/Kodi 兼容的 movie NFO，放在视频同名 .nfo 文件里。
    """
    if not settings.get("write_nfo", True):
        return

    vars_map = build_template_vars(scene, video_path)
    title = vars_map.get("scene_title") or vars_map.get("original_name") or os.path.basename(video_path)
    plot = scene.get("details") or ""
    studio = vars_map.get("studio_name") or ""
    director = vars_map.get("director") or ""
    date = vars_map.get("scene_date") or ""
    year = vars_map.get("date_year") or ""
    code = vars_map.get("code") or ""
    rating = vars_map.get("rating")
    external_id = vars_map.get("external_id") or ""
    urls = scene.get("urls") or []
    url0 = urls[0] if urls else ""

    # 片长（分钟）以及用于 fileinfo 的文件对象
    runtime_minutes = ""
    file_for_info: Dict[str, Any] | None = None
    for f in scene.get("files") or []:
        if not isinstance(f, dict):
            continue
        dur = f.get("duration")
        if dur:
            try:
                runtime_minutes = str(int(round(float(dur) / 60)))
            except Exception:
                runtime_minutes = ""
            file_for_info = f
            break

    # 标签 / 类型
    tag_names: List[str] = []
    for t in scene.get("tags") or []:
        if isinstance(t, dict) and t.get("name"):
            tag_names.append(t["name"])

    # 系列 / 合集：取第一个 group 名称
    collection_name = vars_map.get("group_name") or ""

    # AI 翻译（可选）
    translated_title = None
    translated_plot = None
    task_log("Start translating scene title and plot, It will take a long time")
    try:
        translated_title, translated_plot = translate_title_and_plot(
            title=title,
            plot=plot,
            settings=settings,
        )
    except Exception as e:
        log.error(f"[translator] 调用翻译失败: {e}")

    # 根据配置决定最终写入 NFO 的简介；标题使用自定义格式
    final_plot = plot
    original_title_for_nfo = title
    original_plot_for_nfo = plot

    if translated_plot:
        final_plot = translated_plot

    # 构造 NFO <title>:
    # 未翻译: {scene_title}
    # 翻译成功: {scene_title}.{chinese_title}
    base_title = title
    if translated_title:
        title_for_nfo = f"{base_title}.{translated_title}"
    else:
        title_for_nfo = base_title

    root = ET.Element("movie")

    def _set_text(tag: str, value: str) -> None:
        if value is None:
            return
        value = str(value).strip()
        if not value:
            return
        el = ET.SubElement(root, tag)
        el.text = value

    _set_text("title", title_for_nfo)
    # 原始标题：可以加上番号以便在 Emby 中区分（保留未翻译的标题）
    original_for_field = original_title_for_nfo
    if code:
        original_for_field = f"{code} {original_for_field}"
    _set_text("originaltitle", original_for_field)
    _set_text("sorttitle", title_for_nfo)
    _set_text("year", year)
    # Emby/Kodi 都识别 premiered / releasedate
    _set_text("premiered", date)
    _set_text("releasedate", date)
    # runtime 使用分钟
    _set_text("runtime", runtime_minutes)
    _set_text("plot", final_plot)
    # 保存原始简介文本，方便需要时查看原文
    _set_text("originalplot", original_plot_for_nfo)
    _set_text("studio", studio)
    _set_text("director", director)
    _set_text("id", external_id or str(vars_map.get("id") or ""))
    _set_text("code", code)
    if rating:
        _set_text("rating", rating)
    _set_text("url", url0)

    # fileinfo / streamdetails（供 Emby/Kodi 使用的文件技术信息）
    def _set_child(parent: ET.Element, tag: str, value: Any) -> None:
        if value is None:
            return
        value = str(value).strip()
        if not value:
            return
        el = ET.SubElement(parent, tag)
        el.text = value

    if file_for_info:
        fileinfo_el = ET.SubElement(root, "fileinfo")
        sd_el = ET.SubElement(fileinfo_el, "streamdetails")

        # video
        video_el = ET.SubElement(sd_el, "video")
        width = file_for_info.get("width")
        height = file_for_info.get("height")
        duration_seconds = None
        try:
            if file_for_info.get("duration"):
                duration_seconds = int(round(float(file_for_info["duration"])))
        except Exception:
            duration_seconds = None

        bitrate_kbps = None
        try:
            if file_for_info.get("bit_rate"):
                bitrate_kbps = int(round(float(file_for_info["bit_rate"]) / 1000))
        except Exception:
            bitrate_kbps = None

        aspect = None
        try:
            if width and height:
                aspect = f"{float(width) / float(height):.3f}"
        except Exception:
            aspect = None

        _set_child(video_el, "codec", file_for_info.get("video_codec"))
        _set_child(video_el, "width", width)
        _set_child(video_el, "height", height)
        _set_child(video_el, "aspect", aspect)
        _set_child(video_el, "durationinseconds", duration_seconds)
        _set_child(video_el, "bitrate", bitrate_kbps)
        _set_child(video_el, "filesize", file_for_info.get("size"))

        # audio
        audio_el = ET.SubElement(sd_el, "audio")
        _set_child(audio_el, "codec", file_for_info.get("audio_codec"))

    # genre / tag：用 tags.name 填充
    for name in tag_names:
        _set_text("genre", name)
        _set_text("tag", name)

    # collection / set：使用 group 名称
    if collection_name:
        _set_text("set", collection_name)
        _set_text("collection", collection_name)

    # uniqueid：stashdb 及本地 scene id
    if external_id:
        uid_el = ET.SubElement(root, "uniqueid", {"type": "stashdb", "default": "true"})
        uid_el.text = external_id
    if vars_map.get("id"):
        uid_local = ET.SubElement(root, "uniqueid", {"type": "stash", "default": "false"})
        uid_local.text = str(vars_map.get("id"))

    # 演员列表
    performers = scene.get("performers") or []
    for p in performers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        actor_el = ET.SubElement(root, "actor")
        name_el = ET.SubElement(actor_el, "name")
        name_el.text = name

    nfo_path = os.path.splitext(video_path)[0] + ".nfo"

    if settings.get("dry_run"):
        try:
            xml_str = ET.tostring(root, encoding="unicode")
        except Exception:
            xml_str = "<movie>...</movie>"
        log.info(f"[dry_run] Would write NFO for scene {vars_map.get('id')} -> {nfo_path}")
        log.info(xml_str)
        return

    tree = ET.ElementTree(root)
    try:
        os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
        tree.write(nfo_path, encoding="utf-8", xml_declaration=True)
        log.info(f"Wrote NFO for scene {vars_map.get('id')} -> {nfo_path}")
    except Exception as e:
        log.error(f"写入 NFO 失败 '{nfo_path}': {e}")


def download_scene_art(video_path: str, scene: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    下载场景封面图到视频所在目录，命名成
    「{视频完整文件名（无扩展名）}-poster.[ext]」的格式，便于 Emby 识别。
    """
    if not settings.get("download_poster", True):
        return

    paths = scene.get("paths") or {}
    poster_url = paths.get("screenshot") or paths.get("webp") or ""
    if not poster_url:
        log.warning("Scene has no screenshot/webp path, skip poster download")
        return

    video_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    log.info(f"Video path: {video_path}")
    log.info(f"Video directory: {video_dir}, base name: {base_name}")
    log.info(f"Poster URL: {poster_url}")
    log.info(f"pic base name: {base_name}")
    # 先不带扩展名，真实扩展名在下载时根据 Content-Type/URL 决定
    poster_base = os.path.join(video_dir, f"{base_name}-poster")
    poster_stem = os.path.basename(poster_base)
    exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    # 如果已经存在与当前视频名匹配的 -poster 文件，直接跳过
    for ext in exts:
        candidate = poster_base + ext
        if os.path.exists(candidate):
            log.info(f"Poster already exists, skip: {candidate}")
            return

    # 如果没有匹配的 -poster 文件，但目录里存在"旧命名"的 -poster 文件，尝试重命名为新前缀
    # existing_posters = []
    # try:
    #     for name in os.listdir(video_dir):
    #         stem, ext = os.path.splitext(name)
    #         if ext.lower() not in exts:
    #             continue
    #         if stem.endswith("-poster") and stem != poster_stem:
    #             existing_posters.append(os.path.join(video_dir, name))
    # except Exception as e:
    #     log.error(f"扫描目录中的旧 poster 文件失败: {e}")

    # if len(existing_posters) == 1:
    #     old_path = existing_posters[0]
    #     old_ext = os.path.splitext(old_path)[1]
    #     new_path = poster_base + old_ext

    #     if settings.get("dry_run"):
    #         log.info(f"[dry_run] Would rename poster: '{old_path}' -> '{new_path}'")
    #         return

    #     try:
    #         os.rename(old_path, new_path)
    #         log.info(f"Renamed poster: '{old_path}' -> '{new_path}'")
    #         return
    #     except Exception as e:
    #         log.error(f"重命名 poster 文件失败 '{old_path}' -> '{new_path}': {e}")
    # 如果重命名失败，则继续尝试重新下载

    abs_url = build_absolute_url(poster_url, settings)
    log.info(f"Downloading poster from URL: {abs_url}")

    if settings.get("dry_run"):
        log.info(f"[dry_run] Would download poster: '{abs_url}' -> '{poster_base}.[ext]'")
        return

    log.info(f"Would download poster: '{abs_url}' -> '{poster_base}.[ext]'")
    ok = _download_binary(abs_url, poster_base, settings, detect_ext=True)

    if not ok:
        return

    try:
        overlay_studio_logo_on_poster(poster_base, scene, settings)
    except Exception as e:
        log.error(f"叠加厂商 logo 到 poster 时出错: {e}")


def overlay_studio_logo_on_poster(poster_base: str, scene: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    在已下载好的 poster 右上角叠加厂商 logo。
    poster_base 为不含扩展名的前缀路径（与 download_scene_art 中一致）。
    """
    if not settings.get("overlay_studio_logo_on_poster", False):
        return

    if settings.get("dry_run"):
        log.info("[dry_run] Would overlay studio logo on poster, skip actual image processing")
        return

    max_ratio = 0.15

    studio = scene.get("studio") or {}
    studio_name = studio.get("name") or ""
    studio_image_url = studio.get("image_path") or ""

    if not studio_name or not studio_image_url:
        log.info("Scene has no studio logo image, skip overlay")
        return

    # Stash 对没有自定义 logo 的厂商会返回带 default=true 的占位图，直接跳过
    if "default=true" in str(studio_image_url):
        log.info("Studio logo is default placeholder image, skip overlay")
        return

    # 找到实际的 poster 文件（带扩展名）
    exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")
    poster_path = None
    for ext in exts:
        candidate = poster_base + ext
        if os.path.exists(candidate):
            poster_path = candidate
            break

    # 兼容没有扩展名的 poster 文件
    if not poster_path and os.path.exists(poster_base):
        poster_path = poster_base

    if not poster_path:
        log.warning(f"Poster file not found for overlay, base='{poster_base}'")
        return

    try:
        from PIL import Image  # type: ignore[import]
    except Exception:
        if not _ensure_pillow():
            log.error("Pillow 未安装且自动安装失败，无法在 poster 上叠加厂商 logo")
            return
        try:
            from PIL import Image  # type: ignore[import]
        except Exception:
            log.error("Pillow 自动安装后仍无法导入，无法在 poster 上叠加厂商 logo")
            return

    try:
        poster_img = Image.open(poster_path).convert("RGBA")
    except Exception as e:
        log.error(f"打开 poster 图片失败: {e}")
        return

    poster_dir = os.path.dirname(poster_path)

    # 在与 poster 相同目录下缓存厂商 logo，文件名中带上清洗后的厂商名
    safe_name = safe_segment(studio_name)
    logo_base = os.path.join(poster_dir, f"{safe_name}-logo")

    logo_path = None
    for ext in exts:
        candidate = logo_base + ext
        if os.path.exists(candidate):
            logo_path = candidate
            break

    # 兼容没有扩展名的 logo 文件
    if not logo_path and os.path.exists(logo_base):
        logo_path = logo_base

    if not logo_path:
        abs_logo_url = build_absolute_url(studio_image_url, settings)
        log.info(f"Downloading studio logo from URL: {abs_logo_url}")

        ok = _download_binary(abs_logo_url, logo_base, settings, detect_ext=True)
        if not ok:
            log.error("Failed to download studio logo, skip overlay")
            return

        for ext in exts:
            candidate = logo_base + ext
            if os.path.exists(candidate):
                logo_path = candidate
                break

        if not logo_path and os.path.exists(logo_base):
            logo_path = logo_base

    if not logo_path:
        log.warning(f"Studio logo file not found for overlay, base='{logo_base}'")
        return

    # 如果是 SVG 格式的 logo，则尝试先转换为 PNG，尺寸直接按目标高度生成，以减少二次缩放损失
    def _is_svg_file(path: str) -> bool:
        try:
            with open(path, "rb") as f:
                header = f.read(512).lower()
            return b"<svg" in header
        except Exception:
            return False

    logo_ext = os.path.splitext(logo_path)[1].lower()
    if logo_ext == ".svg" or _is_svg_file(logo_path):
        try:
            import cairosvg  # type: ignore[import]
        except Exception:
            if not _ensure_cairosvg():
                log.error("检测到 SVG 格式厂商 logo，但未安装 cairosvg，无法转换为位图，跳过叠加")
                return
            try:
                import cairosvg  # type: ignore[import]
            except Exception:
                log.error("cairosvg 自动安装后仍无法导入，跳过叠加")
                return

        # 直接以目标高度渲染为 PNG，避免再缩放一次
        target_height_svg = int(poster_img.height * max_ratio)
        if target_height_svg <= 0:
            log.error("计算 SVG logo 目标高度无效，跳过叠加")
            return

        png_logo_path = os.path.splitext(logo_path)[0] + ".png"
        try:
            cairosvg.svg2png(
                url=logo_path, write_to=png_logo_path, output_height=target_height_svg
            )
            logo_path = png_logo_path
            log.info(f"Converted SVG studio logo to PNG for overlay: {png_logo_path}")
        except Exception as e:
            log.error(f"将 SVG logo 转换为 PNG 失败，跳过叠加: {e}")
            return

    try:
        logo_img = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        log.error(f"打开 poster 或 logo 图片失败: {e}")
        return

    if poster_img.width <= 0 or poster_img.height <= 0:
        log.error("Poster 图片尺寸异常，跳过叠加")
        return

    if logo_img.width <= 0 or logo_img.height <= 0:
        log.error("Logo 图片尺寸异常，跳过叠加")
        return

    # 控制 logo 大小：不超过 poster 高度的一定比例，按高度等比缩放宽度；
    # 同时增加横向限制：宽度最多为 poster 宽度的 50%
    target_height = int(poster_img.height * max_ratio)
    if target_height <= 0:
        log.error("计算得到的 logo 目标高度无效，跳过叠加")
        return

    target_width = int(target_height * logo_img.width / logo_img.height)
    if target_width <= 0:
        log.error("计算得到的 logo 目标宽度无效，跳过叠加")
        return

    max_width_ratio = 0.5
    max_width = int(poster_img.width * max_width_ratio)
    if max_width <= 0:
        log.error("计算得到的 logo 最大宽度无效，跳过叠加")
        return

    if target_width > max_width:
        # 如果按高度计算的宽度超过 50%，整体按宽度比例再缩小一次
        scale = max_width / float(target_width)
        target_width = max_width
        target_height = int(target_height * scale)
        if target_height <= 0:
            log.error("按照宽度限制缩放后，logo 高度无效，跳过叠加")
            return

    logo_img = logo_img.resize((target_width, target_height), Image.LANCZOS)

    padding = int(poster_img.width * 0.02)
    x = poster_img.width - target_width - padding
    y = padding
    if x < 0:
        x = 0
    if y < 0:
        y = 0

    poster_img.paste(logo_img, (x, y), logo_img)

    save_kwargs: Dict[str, Any] = {}
    if poster_path.lower().endswith((".jpg", ".jpeg")):
        poster_img = poster_img.convert("RGB")
        save_kwargs["quality"] = 95

    try:
        poster_img.save(poster_path, **save_kwargs)
        log.info(f"Overlayed studio logo on poster: {poster_path}")
    except Exception as e:
        log.error(f"保存叠加 logo 后的 poster 失败: {e}")
        return

    # 处理完成后，删除本地缓存的厂商 logo 原图，避免在目录中留下多余文件
    try:
        # 当前使用的 logo 文件
        if os.path.exists(logo_path):
            os.remove(logo_path)

        # 如果存在同一前缀的其他格式（例如 SVG 原图 + 转换后的 PNG），一并清理
        cleanup_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")
        for ext in cleanup_exts:
            candidate = logo_base + ext
            if os.path.exists(candidate):
                try:
                    os.remove(candidate)
                except Exception as e_remove:
                    log.error(f"删除厂商 logo 缓存文件失败 '{candidate}': {e_remove}")
    except Exception as e:
        log.error(f"清理厂商 logo 缓存文件时出错: {e}")






def move_related_subtitle_files(
    src_video_path: str,
    dst_video_path: str,
    settings: Dict[str, Any],
) -> None:
    """
    如果源目录下存在与视频同名的字幕文件，一并移动到目标目录，
    并按新视频文件名重命名，方便 Emby 识别。

    例如：
      源视频: /path/OldName.mkv
      源字幕: /path/OldName.srt, /path/OldName.chs.srt
      目标视频: /new/Studio.2025-01-01.NewName.mkv

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

            suffix = name[len(src_stem) :]
            new_name = dst_stem + suffix
            full_dst = os.path.join(dst_dir, new_name)

            if full_src == full_dst:
                continue

            # 目标已存在则跳过，避免覆盖
            if os.path.exists(full_dst):
                log.info(f"目标字幕已存在，跳过: '{full_dst}'")
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
        log.error(f"移动字幕文件时出错: {e}")


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
    move_related_subtitle_files(src_video_path, dst_video_path, settings)

    # 后续处理都基于新视频路径
    write_nfo_for_scene(dst_video_path, scene, settings)
    download_scene_art(dst_video_path, scene, settings)


def handle_hook_or_task(stash: StashInterface, args: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    统一入口：
    - 如果是 Hook（Scene.Create.Post / Scene.Update.Post 等），只处理当前 Scene
    - 如果是 Task（手动在 Tasks 页面点执行），遍历所有 Scene，移动 organized=true 的
    """
    # 你的 YAML 里一般会定义 args 里的字段，比如 mode 等
    mode = (args or {}).get("mode") or "all"
    dry_run = bool(settings.get("dry_run"))

    # 添加stash接口到settings中，以便move_file函数可以使用
    settings["stash_interface"] = stash

    # 1) Hook 场景：如果有 hookContext.id，就只处理这个 scene
    hook_ctx = (args or {}).get("hookContext") or {}
    scene_id = hook_ctx.get("id") or hook_ctx.get("scene_id")

    # 1) Hook 模式：只处理单个 scene（通常从 Scene.Update.Post 触发）
    if scene_id is not None:
        # 检查是否启用了 Hook 模式
        if not settings.get("enable_hook_mode", True):  # 默认启用，除非显式禁用
            msg = f"Hook mode disabled, skipping scene {scene_id}"
            log.info(msg)
            task_log(msg, progress=1.0)
            return msg
        
        scene_id = int(scene_id)
        log.info(f"[{PLUGIN_ID}] Hook mode, processing single scene id={scene_id}")

        # 单个 scene 的详细信息可以重新用 find_scene 拉一下，也可以直接用 hookContext 里带的
        scene = stash.find_scene(scene_id, fragment="""
            id
            organized
            title
            code
            details
            director
            date
            rating100
            studio { id name image_path }
            performers { id name disambiguation gender birthdate country eye_color height_cm measurements fake_tits }
            tags { id name }
            groups { group { id name } }
            files { id path width height }
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
        """)

        if not scene:
            msg = f"Scene {scene_id} not found"
            task_log(msg, progress=1.0)
            return msg

        if not scene.get("organized"):
            msg = f"Scene {scene_id} not organized, skipped"
            log.info(msg)
            task_log(msg, progress=1.0)
            return msg

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
                        normalized_source_base = os.path.normpath(source_base_dir)
                        normalized_target_base = os.path.normpath(target_base_dir)
                        normalized_file_path = os.path.normpath(file_path)

                        # 检查文件是否在源目录
                        if normalized_file_path.startswith(normalized_source_base + os.sep):
                            files_needing_processing.append(file_obj)
                        # 检查文件是否在目标目录
                        elif normalized_file_path.startswith(normalized_target_base + os.sep):
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

        # 处理已经在目标目录的文件（重新生成NFO和封面，如果命名规则参数变化则移动到新路径）
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

                # 删除旧的NFO和封面
                remove_old_metadata(file_path, settings)

                # 检查是否需要移动到新路径（如果命名规则中的参数发生了变化）
                # 对于已经在目标目录的文件，使用专门的函数计算目标路径
                try:
                    current_target_path = build_target_path_for_existing_file(file_path, scene, file_obj, settings)
                    normalized_current = os.path.normpath(file_path)
                    normalized_target = os.path.normpath(current_target_path)

                    if normalized_current != normalized_target:
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

    # 2) Task 模式：遍历所有 scene
    log.info(f"[{PLUGIN_ID}] Task mode '{mode}': scanning all scenes and moving organized=True ones")
    task_log(f"[Task] Scanning scenes (mode={mode}, dry_run={dry_run})", progress=0.0)

    scenes = get_all_scenes(stash, settings, per_page=int(settings.get("per_page", 1000)))
    total_scenes = len(scenes)
    organized_scenes = 0
    total_moved = 0

    if total_scenes == 0:
        msg = "No scenes found"
        log.info(f"[{PLUGIN_ID}] {msg}")
        task_log(msg, progress=1.0)
        return msg

    for index, scene in enumerate(scenes, start=1):
        sid = int(scene["id"])
        # 保存json, 调试用（如不需要可保持注释状态）
        # with open(f'scene-{sid}.json', 'w', encoding='utf-8') as f:
        #     json.dump(scene, f, indent=2, ensure_ascii=False)

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
        # break  # 单个完成后打断, 方便调试

    msg = (
        f"Scanned {total_scenes} scenes, "
        f"organized=True: {organized_scenes}, "
        f"moved files: {total_moved}, dry_run={dry_run}"
    )
    log.info(f"[{PLUGIN_ID}] {msg}")
    task_log(msg, progress=1.0)
    return msg


def read_input_file():
    with open('input.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    json_input = read_input()  # 插件运行时从 stdin 读
    # json_input = read_input_file()  # 调试时从文件读
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
    # 把 server_connection 也塞到 settings 里，方便下载图片等功能使用 cookie
    settings["server_connection"] = server_conn

    # with open('settings.json', 'w', encoding='utf-8') as f:
    #     json.dump(settings, f, indent=2, ensure_ascii=False)

    try:
        msg = handle_hook_or_task(stash, args, settings)
        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    # 输出必须是单行 JSON
    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
