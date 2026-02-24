"""
本地导出模块 - 负责将演员数据导出到本地（图片和 NFO）

导出模式 (exportMode):
    0 = 不导出本地
    1 = 只导出 NFO（元数据）
    2 = 只导出封面（图片）
    3 = 都导出（NFO + 封面）
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

import requests
import stashapi.log as log

# 常见图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


def safe_segment(segment: str) -> str:
    """
    简单清理路径段，避免出现奇怪字符。
    """
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    return segment or "_"


def build_absolute_url(url: str, server_conn: Dict[str, Any]) -> str:
    """
    把相对路径补全为带协议/主机的绝对 URL，方便下载图片。
    """
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url

    scheme = server_conn.get("Scheme", "http")
    host = server_conn.get("Host", "localhost")
    port = server_conn.get("Port")

    base = f"{scheme}://{host}"
    if port:
        base = f"{base}:{port}"

    if not url.startswith("/"):
        url = "/" + url

    return base + url


def _build_requests_session(server_conn: Dict[str, Any], stash_api_key: str = "") -> requests.Session:
    """
    基于 server_connection 构建一个带 SessionCookie 的 requests 会话，
    用于从 Stash 下载演员图片。
    """
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

    if stash_api_key:
        session.headers["ApiKey"] = stash_api_key

    return session


def _download_binary(url: str, dst_path: str, server_conn: Dict[str, Any], stash_api_key: str = "", detect_ext: bool = False) -> bool:
    """
    从 Stash（或其它 HTTP 源）下载二进制文件到指定路径。
    """
    if not url:
        return False

    url = build_absolute_url(url, server_conn)
    session = _build_requests_session(server_conn, stash_api_key)

    max_attempts = 3
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.get(url, timeout=30, stream=True)

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                log.warning(f"下载失败 '{url}' -> '{dst_path}': {last_error} (尝试 {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    time.sleep(2 * attempt)
                continue

            if detect_ext:
                content_type = resp.headers.get("Content-Type", "")
                ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
                ext = ext_map.get(content_type.split(";")[0].strip())

                if ext and dst_path:
                    base, old_ext = os.path.splitext(dst_path)
                    if old_ext.lower() not in IMAGE_EXTS and ext.lower() in IMAGE_EXTS:
                        dst_path = base + ext
                        log.info(f"根据 Content-Type 调整扩展名：'{dst_path}'")

            with open(dst_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            log.info(f"Downloaded: '{url}' -> '{dst_path}'")
            return True

        except Exception as e:
            last_error = str(e)
            log.warning(f"下载异常 '{url}' -> '{dst_path}': {last_error} (尝试 {attempt}/{max_attempts})")
            if attempt < max_attempts:
                time.sleep(2 * attempt)

    log.error(f"下载失败，已重试 {max_attempts} 次仍失败 '{url}' -> '{dst_path}': {last_error}")
    return False


def write_actor_nfo(actor_dir: str, performer: Dict[str, Any], export_nfo: bool = True) -> Optional[str]:
    """
    生成演员 NFO 文件。
    
    Args:
        actor_dir: 演员目录
        performer: 演员信息字典
        export_nfo: 是否导出 NFO
        
    Returns:
        NFO 文件路径，如果未导出则返回 None
    """
    if not export_nfo:
        return None

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，无法生成 NFO")
        return None

    root = ET.Element("person")

    def _set(tag: str, value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        el = ET.SubElement(root, tag)
        el.text = text

    # 基本信息
    _set("name", name)
    _set("gender", performer.get("gender"))
    _set("country", performer.get("country"))
    _set("birthdate", performer.get("birthdate"))
    _set("height_cm", performer.get("height_cm"))
    _set("measurements", performer.get("measurements"))
    _set("fake_tits", performer.get("fake_tits"))
    _set("disambiguation", performer.get("disambiguation"))

    # 扩展信息
    _set("ethnicity", performer.get("ethnicity"))
    _set("eye_color", performer.get("eye_color"))
    _set("hair_color", performer.get("hair_color"))
    _set("career_length", performer.get("career_length"))
    _set("tattoos", performer.get("tattoos"))
    _set("piercings", performer.get("piercings"))
    _set("weight", performer.get("weight"))
    _set("penis_length", performer.get("penis_length"))
    _set("death_date", performer.get("death_date"))
    _set("circumcised", performer.get("circumcised"))

    # 别名信息
    alias_list = performer.get("alias_list", [])
    if alias_list and isinstance(alias_list, list) and len(alias_list) > 0:
        aliases_str = " / ".join([alias for alias in alias_list if alias])
        if aliases_str:
            _set("aliases", aliases_str)

    # 链接信息
    urls = performer.get("urls", [])
    if urls and isinstance(urls, list) and len(urls) > 0:
        valid_urls = [url for url in urls if url and isinstance(url, str) and url.strip()]
        if valid_urls:
            urls_str = "\n".join(valid_urls)
            _set("urls", urls_str)

    # 添加 Stash ID 作为外部标识符
    stash_id = performer.get("id")
    if stash_id:
        _set("stash_id", stash_id)

    nfo_path = os.path.join(actor_dir, "actor.nfo")

    try:
        os.makedirs(actor_dir, exist_ok=True)
        tree = ET.ElementTree(root)
        tree.write(nfo_path, encoding="utf-8", xml_declaration=True)
        log.info(f"已生成演员 NFO: '{name}' -> {nfo_path}")
        return nfo_path
    except Exception as e:
        log.error(f"生成演员 NFO 失败 '{nfo_path}': {e}")
        return None


def download_actor_image(actor_dir: str, performer: Dict[str, Any], 
                         server_conn: Dict[str, Any], stash_api_key: str,
                         download_images: bool = True) -> Optional[str]:
    """
    下载演员图片到本地。
    
    Args:
        actor_dir: 演员目录
        performer: 演员信息字典
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
        download_images: 是否下载图片
        
    Returns:
        图片文件路径，如果未下载则返回 None
    """
    if not download_images:
        return None

    image_url = performer.get("image_path")
    if not image_url:
        log.info("演员没有图片 URL，跳过下载")
        return None

    name = performer.get("name")
    dst_path = os.path.join(actor_dir, "folder.jpg")
    abs_url = build_absolute_url(image_url, server_conn)

    success = _download_binary(abs_url, dst_path, server_conn, stash_api_key, detect_ext=False)
    if success:
        log.info(f"已下载演员图片：'{name}' -> {dst_path}")
        return dst_path
    else:
        log.error(f"下载演员图片失败：'{name}' -> {dst_path}")
        return None


def export_actor_to_local(performer: Dict[str, Any],
                          actor_output_dir: str,
                          export_mode: int = 1,
                          server_conn: Optional[Dict[str, Any]] = None,
                          stash_api_key: str = "",
                          dry_run: bool = False,
                          need_nfo: bool = True,
                          need_image: bool = True) -> Dict[str, Optional[str]]:
    """
    导出演员数据到本地（根据导出模式）。

    Args:
        performer: 演员信息字典
        actor_output_dir: 演员数据输出根目录
        export_mode: 导出模式
            0 = 不导出本地
            1 = 强制覆盖 (图片 + NFO)
            2 = 只导出 NFO (覆盖)
            3 = 只导出图片 (覆盖)
            4 = 补缺本地 (只导出缺失的图片 + NFO)
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
        dry_run: 是否仅模拟
        need_nfo: 是否需要导出 NFO（补缺模式时使用）
        need_image: 是否需要导出图片（补缺模式时使用）

    Returns:
        包含生成文件路径的字典：{"nfo": nfo_path, "image": image_path}
    """
    result = {"nfo": None, "image": None}

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过导出")
        return result

    # 模式 0：不导出本地
    if export_mode == 0:
        log.info(f"导出模式 0：不导出演员 {name} 到本地")
        return result

    # 检查输出目录
    if not actor_output_dir:
        log.error("未配置演员输出目录，无法导出到本地")
        return result

    # 准备目录
    safe_name = safe_segment(name)
    actor_dir = os.path.join(actor_output_dir, safe_name)

    if not dry_run:
        os.makedirs(actor_dir, exist_ok=True)

    image_url = performer.get("image_path")

    # 模式 1：强制覆盖 (图片 + NFO)
    if export_mode == 1:
        nfo_path = write_actor_nfo(actor_dir, performer, export_nfo=True)
        result["nfo"] = nfo_path
        if image_url:
            image_path = download_actor_image(actor_dir, performer, server_conn, stash_api_key, download_images=True)
            result["image"] = image_path
        else:
            log.warning(f"演员 {name} 没有图片 URL，无法下载图片")
        return result

    # 模式 2：只导出 NFO (覆盖)
    if export_mode == 2:
        log.info(f"导出模式 2：只导出演员 {name} 的 NFO")
        nfo_path = write_actor_nfo(actor_dir, performer, export_nfo=True)
        result["nfo"] = nfo_path
        return result

    # 模式 3：只导出图片 (覆盖)
    if export_mode == 3:
        log.info(f"导出模式 3：只导出演员 {name} 的图片")
        if image_url:
            image_path = download_actor_image(actor_dir, performer, server_conn, stash_api_key, download_images=True)
            result["image"] = image_path
        else:
            log.info(f"演员 {name} 没有图片 URL，跳过图片下载")
        return result

    # 模式 4：补缺本地 (只导出缺失的，使用传入的 need_nfo/need_image 参数)
    if export_mode == 4:
        nfo_path = os.path.join(actor_dir, "actor.nfo")
        image_path = os.path.join(actor_dir, "folder.jpg")

        # 只补缺缺失的
        if need_nfo:
            nfo_path = write_actor_nfo(actor_dir, performer, export_nfo=True)
            result["nfo"] = nfo_path

        if need_image and image_url:
            image_path = download_actor_image(actor_dir, performer, server_conn, stash_api_key, download_images=True)
            result["image"] = image_path

        return result

    log.warning(f"未知的导出模式：{export_mode}")
    return result
