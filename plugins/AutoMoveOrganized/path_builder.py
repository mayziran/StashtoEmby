# -*- coding: utf-8 -*-
"""
path_builder.py - 路径构建模块

负责根据模板和映射设置构建目标路径
- 构建模板变量字典
- 应用模板并添加后缀
- 处理源目录映射逻辑
- 处理目标目录映射逻辑
- 处理无映射情况
"""

import os
import re
from typing import Any, Dict

import stashapi.log as log


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

    # 如果文件数量不大于 1，不需要添加后缀
    if len(all_files) <= 1:
        return filename

    # 优化：创建文件 ID 到索引的映射，避免重复遍历
    file_id_to_index = {f.get("id"): idx for idx, f in enumerate(all_files)}

    # 获取当前文件在场景中的索引
    current_file_id = file_obj.get("id")
    file_index = file_id_to_index.get(current_file_id, 0)

    # 为所有文件添加后缀，包括第一个文件
    # 在文件名主体和扩展名之间添加 -cdN 后缀
    name_without_ext, file_ext = os.path.splitext(filename)
    filename = f"{name_without_ext}-cd{file_index + 1}{file_ext}"

    return filename


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

    performer_names: list[str] = []
    for p in scene.get("performers", []):
        if isinstance(p, dict) and p.get("name"):
            performer_names.append(p["name"])

    performers_str = "-".join(performer_names)
    first_performer = performer_names[0] if performer_names else ""
    performer_count = len(performer_names)

    # tags
    tag_names: list[str] = []
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

    # 评分（转换为 0-10 分制，保留 1 位小数，如 85 → 8.5）
    rating100 = scene.get("rating100")
    rating = "" if rating100 is None else str(round(rating100 / 10, 1))

    # 可能的外部 ID（供 Emby StashBox 插件使用）
    # 格式：scenes/{uuid}（与 ThePornDB 插件保持一致）
    # 支持多个 stash_ids，按 endpoint 分类
    external_ids = {}  # {identifier: "scenes\\{uuid}", ...}
    stash_ids = scene.get("stash_ids") or []
    if stash_ids and isinstance(stash_ids, list):
        for s in stash_ids:
            if not isinstance(s, dict):
                continue
            endpoint = s.get("endpoint", "")
            stash_id = s.get("stash_id", "")
            if not endpoint or not stash_id:
                continue

            # 从 endpoint 提取简短标识符（小写）
            # https://stashdb.org/graphql -> stashdb
            # https://theporndb.net/graphql -> theporndb
            # https://fansdb.cc/graphql -> fansdb
            # https://javstash.org/graphql -> javstash
            # https://pmvstash.org/graphql -> pmvstash
            base_url = endpoint.replace("/graphql", "")
            domain = base_url.replace("https://", "").replace("http://", "")
            identifier = domain.split('.')[0].lower()

            # 存 scenes\{uuid} 格式（Emby 需要使用反斜杠避免被当作分隔符）
            external_ids[identifier] = f"scenes\\{stash_id}"

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
        "external_ids": external_ids,  # 支持多个外部 ID
        "width": width,
        "height": height,
        "resolution": resolution,
        "quality": quality,
    }


def _apply_template_and_suffix(template: str, scene: Dict[str, Any], file_path: str, file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    应用模板并添加后缀的辅助函数
    """
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
        raise RuntimeError(f"命名模板解析失败：{e}")

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

    return filename_clean


def _parse_source_target_mapping(source_target_mapping: str) -> tuple[str, str] | None:
    """
    解析源目录到目标目录的映射设置
    """
    if '->' in source_target_mapping:
        parts = source_target_mapping.split('->', 1)
        if len(parts) == 2:
            source_base_dir = parts[0].strip()
            target_base_dir = parts[1].strip()
            if source_base_dir and target_base_dir:
                return source_base_dir, target_base_dir
    return None


def _handle_source_mapping_logic(file_path: str, source_base_dir: str, target_base_dir: str,
                               scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    处理源目录映射逻辑
    """
    # 计算相对于源基础目录的路径（使用 / 格式）
    # Stash 路径永远是 / 格式，直接字符串操作
    if file_path.startswith(source_base_dir + '/'):
        rel_path_from_base = file_path[len(source_base_dir):].lstrip('/')
    elif file_path == source_base_dir:
        rel_path_from_base = ''
    else:
        # 理论上不应该到这里，因为调用前已经检查过
        rel_path_from_base = file_path

    # 获取第一级子目录（如果存在）
    rel_parts = rel_path_from_base.split('/')
    first_level_dir = rel_parts[0] if rel_parts and rel_parts[0] else ""

    # 使用模板生成文件名部分
    template = settings["filename_template"].strip()

    # 应用模板并添加后缀
    filename_clean = _apply_template_and_suffix(template, scene, file_path, file_obj, settings)

    # 组合最终路径：直接使用 / 拼接
    abs_target = f"{target_base_dir}/{first_level_dir}/{filename_clean}" if first_level_dir else f"{target_base_dir}/{filename_clean}"
    return abs_target


def _handle_target_mapping_logic(file_path: str, target_base_dir: str,
                              scene: Dict[str, Any], file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    处理目标目录映射逻辑
    """
    # 计算相对于目标基础目录的路径（使用 / 格式）
    if file_path.startswith(target_base_dir + '/'):
        rel_path_from_base = file_path[len(target_base_dir):].lstrip('/')
    elif file_path == target_base_dir:
        rel_path_from_base = ''
    else:
        rel_path_from_base = file_path

    rel_parts = rel_path_from_base.split('/')
    first_level_dir = rel_parts[0] if rel_parts and rel_parts[0] else ""

    # 使用模板生成文件名部分
    template = settings["filename_template"].strip()

    # 应用模板并添加后缀
    filename_clean = _apply_template_and_suffix(template, scene, file_path, file_obj, settings)

    # 组合最终路径：直接使用 / 拼接
    abs_target = f"{target_base_dir}/{first_level_dir}/{filename_clean}" if first_level_dir else f"{target_base_dir}/{filename_clean}"
    return abs_target


def _handle_no_mapping_case(scene: Dict[str, Any], file_path: str, file_obj: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    处理没有映射的情况
    """
    target_root = settings["target_root"].strip()
    if not target_root:
        raise RuntimeError("目标目录 (target_root) 未配置")

    # 使用模板生成路径
    template = settings["filename_template"].strip()

    # 应用模板并添加后缀
    rel_path_clean = _apply_template_and_suffix(template, scene, file_path, file_obj, settings)

    abs_target = os.path.join(target_root, rel_path_clean)
    return abs_target


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
      {performers}            -> 演员列表（用 - 连接）
      {first_performer}       -> 第一个演员
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
        # 解析映射设置，格式为 "源目录->目标目录"
        mapping_result = _parse_source_target_mapping(source_target_mapping)
        if mapping_result:
            source_base_dir, target_base_dir = mapping_result

            # 使用正则表达式匹配（与 scene_fetcher.py 一致）
            # Stash 返回的路径永远是 / 格式，直接用 / 匹配
            escaped_source = re.escape(source_base_dir)
            escaped_target = re.escape(target_base_dir)

            # 检查文件路径是否在源目录下（源目录文件）
            if re.match(f"^({escaped_source})(/.*|$)", file_path):
                return _handle_source_mapping_logic(file_path, source_base_dir, target_base_dir, scene, file_obj, settings)
            # 检查文件路径是否在目标目录下（目标目录文件）
            elif re.match(f"^({escaped_target})(/.*|$)", file_path):
                return _handle_target_mapping_logic(file_path, target_base_dir, scene, file_obj, settings)
            else:
                # 文件既不在源目录也不在目标目录，使用标准路径构建逻辑
                # 这种情况可能发生在文件已被移动到其他位置或路径配置变更
                log.warning(f"文件路径 '{file_path}' 既不在源基础目录 '{source_base_dir}' 也不在目标目录 '{target_base_dir}' 下，使用标准路径构建逻辑")
                return _handle_no_mapping_case(scene, file_path, file_obj, settings)
        else:
            # 如果格式不正确，抛出错误
            raise RuntimeError("源目录到目标目录的映射格式错误，应为 '源目录->目标目录'")
    else:
        # 如果没有设置映射，使用原有逻辑
        return _handle_no_mapping_case(scene, file_path, file_obj, settings)


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
                    # 使用正则表达式匹配（Stash 路径永远是 / 格式）
                    escaped_target = re.escape(target_base_dir)

                    # 检查文件是否在目标目录下
                    if re.match(f"^({escaped_target})(/.*|$)", file_path):
                        # 计算相对于目标基础目录的路径，获取第一级子目录
                        # 直接使用 / 分割（Stash 路径格式）
                        rel_path_from_base = file_path[len(target_base_dir):].lstrip('/')
                        rel_parts = rel_path_from_base.split('/')
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
                            raise RuntimeError(f"命名模板解析失败：{e}")

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
                        # 直接使用 / 拼接（Stash 路径格式）
                        abs_target = f"{target_base_dir}/{first_level_dir}/{filename_clean}"
                        return abs_target
                    else:
                        # 如果文件不在目标目录下，这可能是因为：
                        # 1. 这是同一场景的另一个文件，位于源目录
                        # 2. 我们需要使用标准的路径构建逻辑来处理这种情况
                        # 使用 build_target_path 函数来处理这种情况
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
            raise RuntimeError(f"命名模板解析失败：{e}")

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
        raise RuntimeError(f"计算目标路径失败：{e}")
