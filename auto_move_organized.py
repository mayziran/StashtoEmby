#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

import requests
import stashapi.log as log
from stashapi.stashapp import StashInterface
from ai_translate import translate_title_and_plot

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
    download_actor_images = bool(_get_val("download_actor_images", True))

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
        f"download_poster={download_poster}, download_actor_images={download_actor_images}"
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
        "download_actor_images": download_actor_images,
        # AI / 翻译
        "translate_enable": translate_enable,
        "translate_api_base": translate_api_base,
        "translate_api_key": translate_api_key,
        "translate_model": translate_model,
        "translate_plot": translate_plot,
        "translate_title": translate_title,
        "translate_temperature": translate_temperature,
        "translate_prompt": translate_prompt,
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


def build_template_vars(scene: Dict[str, Any], file_path: str) -> Dict[str, Any]:
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
    }


def build_target_path(
        scene: Dict[str, Any],
        file_path: str,
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
      {original_basename}
      {original_name}
      {ext}
    """

    target_root = settings["target_root"].strip()
    template = settings["filename_template"].strip()

    if not target_root:
        raise RuntimeError("目标目录(target_root)未配置")

    vars_map = build_template_vars(scene, file_path)
    original_basename = vars_map["original_basename"]
    ext = vars_map["ext"]

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

    # if src == dst:
    #     log.info(f"源路径和目标路径相同，跳过: {src}")
    #     return False
    #
    # if not os.path.exists(src):
    #     log.warning(f"源文件不存在，跳过: {src}")
    #     return False
    #
    # if os.path.exists(dst):
    #     log.warning(f"目标文件已存在，跳过: {dst}")
    #     return False

    dst_dir = os.path.dirname(dst)
    try:
        if not settings.get("dry_run"):
            os.makedirs(dst_dir, exist_ok=True)
            # 使用 move 确保跨设备也能工作（Python 会自动选择 copy+remove）
            shutil.move(src, dst)
        try:
            post_process_moved_file(dst, scene, settings)
        except Exception as post_e:
            log.error(f"移动后处理失败 '{dst}': {post_e}")
        log.info(f"Moved file: '{src}' -> '{dst}' (dry_run={settings.get('dry_run')})")
        return True
    except Exception as e:
        log.error(f"移动文件失败 '{src}' -> '{dst}': {e}")
        return False


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

    moved_count = 0

    def _is_file_organized(file_obj: Dict[str, Any]) -> bool:
        if not settings.get("move_only_organized"):
            return True
        # 如果文件上没有，则退回到 scene 级别
        if "organized" in scene:
            return bool(scene.get("organized"))
        return False

    for f in files:
        if not _is_file_organized(f):
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


def _build_requests_session(settings: Dict[str, Any]) -> requests.Session:
    """
    基于 server_connection 构建一个带 SessionCookie 的 requests 会话，
    用于从 Stash 下载截图和演员图片。
    """
    server_conn = settings.get("server_connection") or {}
    session = requests.Session()

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

    return session


def _download_binary(url: str, dst_path: str, settings: Dict[str, Any]) -> bool:
    """
    从 Stash（或其它 HTTP 源）下载二进制文件到指定路径。
    """
    if not url:
        return False

    url = build_absolute_url(url, settings)
    session = _build_requests_session(settings)

    try:
        resp = session.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        log.info(f"Downloaded '{url}' -> '{dst_path}'")
        return True
    except Exception as e:
        log.error(f"下载失败 '{url}' -> '{dst_path}': {e}")
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
    try:
        translated_title, translated_plot = translate_title_and_plot(
            title=title,
            plot=plot,
            settings=settings,
        )
    except Exception as e:
        log.error(f"[translator] 调用翻译失败: {e}")

    # 根据配置决定最终写入 NFO 的标题/简介
    final_title = title
    final_plot = plot
    original_title_for_nfo = title
    original_plot_for_nfo = plot

    if translated_title:
        final_title = translated_title

    if translated_plot:
        final_plot = translated_plot

    root = ET.Element("movie")

    def _set_text(tag: str, value: str) -> None:
        if value is None:
            return
        value = str(value).strip()
        if not value:
            return
        el = ET.SubElement(root, tag)
        el.text = value

    _set_text("title", final_title)
    # 原始标题：可以加上番号以便在 Emby 中区分（保留未翻译的标题）
    original_for_field = original_title_for_nfo
    if code:
        original_for_field = f"{code} {original_for_field}"
    _set_text("originaltitle", original_for_field)
    _set_text("sorttitle", final_title)
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
    下载场景封面图到视频所在目录，命名成 Emby 常见格式（folder.jpg）。
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
    dst_poster = os.path.join(video_dir, f"{base_name}-poster.jpg")

    abs_url = build_absolute_url(poster_url, settings)

    if settings.get("dry_run"):
        log.info(f"[dry_run] Would download poster: '{abs_url}' -> '{dst_poster}'")
        return

    if os.path.exists(dst_poster):
        log.info(f"Poster already exists, skip: {dst_poster}")
        return

    _download_binary(abs_url, dst_poster, settings)


def download_actor_images(scene: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    把演员图片下载到 {target_root}/actors/ 目录下，文件名为演员名（清洗过）。
    """
    if not settings.get("download_actor_images", True):
        return

    performers = scene.get("performers") or []
    if not performers:
        return

    target_root = settings.get("target_root", "").strip()
    if not target_root:
        log.warning("target_root 未配置，无法保存演员图片")
        return

    actors_root = os.path.join(target_root, "actors")
    if not settings.get("dry_run"):
        os.makedirs(actors_root, exist_ok=True)

    for p in performers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        image_url = p.get("image_path")
        if not name or not image_url:
            continue

        filename = f"{safe_segment(name)}.jpg"
        dst_path = os.path.join(actors_root, filename)
        abs_url = build_absolute_url(image_url, settings)

        if settings.get("dry_run"):
            log.info(f"[dry_run] Would download actor image: '{abs_url}' -> '{dst_path}'")
            continue

        if os.path.exists(dst_path):
            log.info(f"Actor image already exists, skip: {dst_path}")
            continue

        _download_binary(abs_url, dst_path, settings)


def post_process_moved_file(dst_video_path: str, scene: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    文件移动之后的后续处理：
    1. 写 NFO
    2. 下载场景封面图到视频目录（folder.jpg）
    3. 下载演员头像到 {target_root}/actors/
    """
    write_nfo_for_scene(dst_video_path, scene, settings)
    download_scene_art(dst_video_path, scene, settings)
    download_actor_images(scene, settings)


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

        moved = process_scene(scene, settings)
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
        # with open(f'scene-{sid}.json', 'w', encoding='utf-8') as f:
        #     json.dump(scene, f, indent=2, ensure_ascii=False)

        if not scene.get("organized"):
            continue

        organized_scenes += 1
        log.info(f"Processing organized scene id={sid} title={scene.get('title')!r}")
        moved = process_scene(scene, settings)
        total_moved += moved
        # break  # 单个完成后打断, 方便调试

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
        out = {"output": msg}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    # 输出必须是单行 JSON
    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
