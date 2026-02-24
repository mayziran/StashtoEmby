"""
本地导出模块 - 负责将演员数据导出到本地（图片和 NFO）

导出模式 (export_mode):
    1 = 都导出 (NFO + 图片)
    2 = 只导出 NFO
    3 = 只导出图片
"""

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

import requests
import stashapi.log as log

from utils import safe_segment, build_absolute_url, build_requests_session


def write_actor_nfo(actor_dir: str, performer: Dict[str, Any]) -> Optional[str]:
    """
    生成演员 NFO 文件。

    Args:
        actor_dir: 演员目录
        performer: 演员信息字典

    Returns:
        NFO 文件路径，如果未导出则返回 None
    """
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
                         server_conn: Dict[str, Any], stash_api_key: str) -> Optional[str]:
    """
    下载演员图片到本地。

    Args:
        actor_dir: 演员目录
        performer: 演员信息字典
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥

    Returns:
        图片文件路径，如果未下载则返回 None
    """
    image_url = performer.get("image_path")
    if not image_url:
        log.info("演员没有图片 URL，跳过下载")
        return None

    name = performer.get("name")
    dst_path = os.path.join(actor_dir, "folder.jpg")
    abs_url = build_absolute_url(image_url, server_conn)
    session = build_requests_session(server_conn, stash_api_key)

    try:
        resp = session.get(abs_url, timeout=30)
        if resp.status_code == 200:
            with open(dst_path, "wb") as f:
                f.write(resp.content)
            log.info(f"已下载演员图片：'{name}' -> {dst_path}")
            return dst_path
        else:
            log.error(f"下载演员图片失败：'{name}'，状态码：{resp.status_code}")
            return None
    except Exception as e:
        log.error(f"下载演员图片异常：'{name}': {e}")
        return None


def export_actor_to_local(
    performer: Dict[str, Any],
    actor_output_dir: str,
    export_mode: int = 1,
    server_conn: Optional[Dict[str, Any]] = None,
    stash_api_key: str = "",
    dry_run: bool = False
) -> Dict[str, Optional[str]]:
    """
    导出演员数据到本地（简化版）。

    Args:
        performer: 演员信息字典
        actor_output_dir: 演员数据输出根目录
        export_mode: 导出模式
            1 = 都导出 (NFO + 图片)
            2 = 只导出 NFO
            3 = 只导出图片
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
        dry_run: 是否仅模拟

    Returns:
        包含生成文件路径的字典：{"nfo": nfo_path, "image": image_path}
    """
    result = {"nfo": None, "image": None}

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过导出")
        return result

    if not actor_output_dir:
        log.error("未配置演员输出目录，无法导出到本地")
        return result

    # 准备目录
    safe_name = safe_segment(name)
    actor_dir = os.path.join(actor_output_dir, safe_name)

    if not dry_run:
        os.makedirs(actor_dir, exist_ok=True)

    image_url = performer.get("image_path")

    # 模式 2 或 1：导出 NFO
    if export_mode in [1, 2]:
        nfo_path = write_actor_nfo(actor_dir, performer)
        result["nfo"] = nfo_path

    # 模式 1 或 3：导出图片
    if export_mode in [1, 3]:
        if image_url:
            image_path = download_actor_image(actor_dir, performer, server_conn, stash_api_key)
            result["image"] = image_path
        else:
            log.warning(f"演员 {name} 没有图片 URL，无法下载图片")

    return result
