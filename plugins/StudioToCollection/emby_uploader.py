"""
Emby 上传模块 - 纯上传工具

职责:
    1. 接收已构建好的 emby_data，调用 Emby API 上传
    2. 下载并上传工作室图片 (Primary + Logo)
    3. 不 responsible for 数据构建，只负责上传
"""

from typing import Any, Dict, Optional

import requests
import stashapi.log as log

PLUGIN_ID = "StudioToCollection"


def download_image(image_url: str, stash_url: str = "") -> Optional[bytes]:
    """下载图片"""
    try:
        if not image_url.startswith("http"):
            image_url = f"{stash_url or 'http://localhost:9999'}{image_url}"

        response = requests.get(image_url, timeout=30)
        return response.content if response.status_code == 200 else None
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 下载图片失败：{e}")
        return None


def upload_metadata(
    collection_id: str,
    emby_data: dict,
    emby_server: str,
    emby_api_key: str,
    dry_run: bool = False
) -> bool:
    """上传元数据"""
    if dry_run:
        log.info(f"[{PLUGIN_ID}] [模拟] 更新元数据：{collection_id}")
        return True

    try:
        url = f"{emby_server}/emby/Items/{collection_id}"
        params = {"api_key": emby_api_key}
        emby_data["Id"] = collection_id

        response = requests.post(url, params=params, json=emby_data, timeout=30)
        if response.status_code == 204:
            log.info(f"[{PLUGIN_ID}] ✓ 元数据已更新")
            return True
        log.error(f"[{PLUGIN_ID}] 更新元数据失败：{response.status_code}")
        return False
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 更新元数据失败：{e}")
        return False


def upload_image(
    collection_id: str,
    image_bytes: bytes,
    image_type: str,
    emby_server: str,
    emby_api_key: str,
    dry_run: bool = False
) -> bool:
    """上传图片（Primary 或 Logo）"""
    if dry_run:
        log.info(f"[{PLUGIN_ID}] [模拟] 上传{image_type}图片：{collection_id}")
        return True

    try:
        url = f"{emby_server}/emby/Items/{collection_id}/Images/{image_type}"
        params = {"api_key": emby_api_key}

        response = requests.post(url, params=params, data=image_bytes, timeout=30)
        if response.status_code == 204:
            log.info(f"[{PLUGIN_ID}] ✓ {image_type}图片已上传")
            return True
        log.error(f"[{PLUGIN_ID}] 上传{image_type}图片失败：{response.status_code}")
        return False
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 上传{image_type}图片失败：{e}")
        return False


def upload_studio_to_emby(
    studio: Dict[str, Any],
    collection_id: str,
    emby_server: str,
    emby_api_key: str,
    emby_data: Dict[str, Any],
    dry_run: bool = False,
    stash_url: str = ""
) -> bool:
    """
    上传工作室到 Emby（统一上传入口）
    
    职责：接收已构建好的 emby_data，负责上传元数据和图片
    
    Args:
        studio: 工作室原始数据（用于获取 image_path）
        collection_id: Emby 合集 ID
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        emby_data: 已构建好的 Emby 数据（由 utils.build_emby_data 构建）
        dry_run: 是否仅模拟
        stash_url: Stash 服务器 URL（用于下载图片）
    
    Returns:
        上传是否成功
    """
    # 上传元数据
    if not upload_metadata(collection_id, emby_data, emby_server, emby_api_key, dry_run):
        return False

    # 上传图片
    if studio.get("image_path"):
        image_url = studio["image_path"]
        if not image_url.startswith("http"):
            image_url = f"{stash_url or 'http://localhost:9999'}{image_url}"

        image_bytes = download_image(image_url, stash_url)
        if image_bytes:
            upload_image(collection_id, image_bytes, "Primary", emby_server, emby_api_key, dry_run)
            upload_image(collection_id, image_bytes, "Logo", emby_server, emby_api_key, dry_run)
        else:
            log.error(f"[{PLUGIN_ID}] 下载图片失败：{image_url}")

    return True
