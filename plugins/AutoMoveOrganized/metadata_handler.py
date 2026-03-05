# -*- coding: utf-8 -*-
"""
metadata_handler.py - 元数据处理模块

负责生成和下载元数据
- 生成 NFO 文件（Emby/Kodi 兼容）
- 下载场景封面图
- 叠加厂商 Logo 到封面
"""

import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
import stashapi.log as log

from ai_translate import translate_title_and_plot
from path_builder import build_template_vars, build_absolute_url, safe_segment


_AUTO_INSTALL_ATTEMPTED: set[str] = set()


def _ensure_python_package(package: str) -> bool:
    """
    尝试在容器内自动安装第三方库。
    """
    if package in _AUTO_INSTALL_ATTEMPTED:
        return False
    _AUTO_INSTALL_ATTEMPTED.add(package)

    try:
        log.info(
            f"{package} 未安装，尝试自动安装：python -m pip install {package} --break-system-packages"
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
        log.error(f"自动安装 {package} 失败：{e}")
        return False


def _ensure_pillow() -> bool:
    return _ensure_python_package("Pillow")


def _ensure_cairosvg() -> bool:
    return _ensure_python_package("cairosvg")


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

                # 这里只负责"补上扩展名"，不再从 dst_path 中拆分文件名/扩展名，避免截断演员名等信息
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
            log.error(f"下载失败 (第{attempt}次) '{url}' -> '{dst_path}': {e}")
            if attempt < max_attempts:
                # 简单退避：2s, 4s
                time.sleep(2 * attempt)

    log.error(f"下载失败，已重试 {max_attempts} 次仍失败 '{url}' -> '{dst_path}': {last_error}")
    return False


def _find_file_with_extensions(base_path: str, extensions: tuple) -> str | None:
    """
    根据基本路径和扩展名列表查找存在的文件
    """
    for ext in extensions:
        candidate = base_path + ext
        if os.path.exists(candidate):
            return candidate

    # 兼容没有扩展名的文件
    if os.path.exists(base_path):
        return base_path

    return None


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
    external_ids = vars_map.get("external_ids") or {}  # 支持多个外部 ID
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

    # 获取演员名列表，用于翻译时告诉 AI 不要翻译这些名字
    performer_names: List[str] = []
    for p in scene.get("performers") or []:
        if isinstance(p, dict) and p.get("name"):
            performer_names.append(p["name"])

    # AI 翻译（可选）
    translated_title = None
    translated_plot = None
    log.info("Start translating scene title and plot, It will take a long time")
    try:
        translated_title, translated_plot = translate_title_and_plot(
            title=title,
            plot=plot,
            settings=settings,
            performers=performer_names if performer_names else None,
        )
    except Exception as e:
        log.error(f"[translator] 调用翻译失败：{e}")

    # 根据配置决定最终写入 NFO 的简介；标题使用自定义格式
    final_plot = plot
    original_title_for_nfo = title
    original_plot_for_nfo = plot

    if translated_plot:
        final_plot = translated_plot

    # 构造 NFO <title>:
    # 未翻译：{scene_title}
    # 翻译成功：{scene_title}.{chinese_title}
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
    _set_text("originaltitle", original_title_for_nfo)
    # tagline（宣传语）：写入 code
    _set_text("tagline", code)
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

    # uniqueid：根据 Stash-Box 实例类型写入对应的 type（支持多个）
    # 注意：不设置 default 属性，遵循 Emby 规范（default="false" 或省略）
    for identifier, ext_id in external_ids.items():
        uid_el = ET.SubElement(root, "uniqueid", {"type": identifier})
        uid_el.text = ext_id

    # 本地 Stash ID
    if vars_map.get("id"):
        uid_local = ET.SubElement(root, "uniqueid", {"type": "stash"})
        uid_local.text = str(vars_map.get("id"))

    # 源链接：写入 scene_source_url 类型的 uniqueid
    if url0:
        # 去掉协议前缀，使用反斜杠替代正斜杠
        url_without_scheme = url0.replace("https://", "").replace("http://", "")
        encoded_url = url_without_scheme.replace("/", "\\")
        uid_url = ET.SubElement(root, "uniqueid", {"type": "scene_source_url"})
        uid_url.text = encoded_url

    # 演员列表
    performers = scene.get("performers") or []
    for p in performers:
        if not isinstance(p, dict):
            continue
        # 构建完整姓名（包含消歧义）
        name = p.get("name", "")
        disambiguation = p.get("disambiguation", "")
        if name and disambiguation:
            name = f"{name} ({disambiguation})"
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
        log.error(f"叠加厂商 logo 到 poster 时出错：{e}")


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
    poster_path = _find_file_with_extensions(poster_base, exts)

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
        log.error(f"打开 poster 图片失败：{e}")
        return

    poster_dir = os.path.dirname(poster_path)

    # 在与 poster 相同目录下缓存厂商 logo，文件名中带上清洗后的厂商名
    safe_name = safe_segment(studio_name)
    logo_base = os.path.join(poster_dir, f"{safe_name}-logo")

    logo_path = _find_file_with_extensions(logo_base, exts)

    if not logo_path:
        abs_logo_url = build_absolute_url(studio_image_url, settings)
        log.info(f"Downloading studio logo from URL: {abs_logo_url}")

        ok = _download_binary(abs_logo_url, logo_base, settings, detect_ext=True)
        if not ok:
            log.error("Failed to download studio logo, skip overlay")
            return

        logo_path = _find_file_with_extensions(logo_base, exts)

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
            log.error(f"将 SVG logo 转换为 PNG 失败，跳过叠加：{e}")
            return

    try:
        logo_img = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        log.error(f"打开 poster 或 logo 图片失败：{e}")
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
        log.error(f"保存叠加 logo 后的 poster 失败：{e}")
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
            if os.path.exists(candidate) and candidate != logo_path:
                try:
                    os.remove(candidate)
                except Exception as e_remove:
                    log.error(f"删除厂商 logo 缓存文件失败 '{candidate}': {e_remove}")
    except Exception as e:
        log.error(f"清理厂商 logo 缓存文件时出错：{e}")
