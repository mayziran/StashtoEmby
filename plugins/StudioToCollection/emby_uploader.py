"""
Emby 上传模块 - 纯上传工具

只负责调用 Emby API 上传数据，不负责数据构建。
"""

from typing import Optional

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
