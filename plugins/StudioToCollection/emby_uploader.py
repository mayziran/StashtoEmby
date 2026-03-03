"""
Emby 上传模块 - 纯上传工具

职责:
    1. 接收已构建好的 emby_data，调用 Emby API 上传
    2. 下载并上传工作室图片 (Primary + Logo)
    3. 不负责数据构建，只负责上传

参考:
    - actorSyncEmby 插件：图片上传逻辑（Base64 编码）
"""

import base64
from typing import Any, Dict, Optional, Tuple

import requests
import stashapi.log as log

PLUGIN_ID = "StudioToCollection"


# =============================================================================
# 工具函数（参考 actorSyncEmby）
# =============================================================================

def build_absolute_url(url: str, server_conn: Dict[str, Any]) -> str:
    """构建绝对 URL（参考 actorSyncEmby）"""
    if not url:
        return url
    
    # 如果已经是完整 URL，直接返回
    if url.startswith("http://") or url.startswith("https://"):
        return url
    
    # 构建基础 URL
    scheme = server_conn.get("Scheme", "http")
    host = server_conn.get("Host", "localhost")
    port = server_conn.get("Port")
    
    base = f"{scheme}://{host}"
    if port:
        base = f"{base}:{port}"
    
    # 确保路径以 / 开头
    if not url.startswith("/"):
        url = "/" + url
    
    return base + url


def build_requests_session(server_conn: Dict[str, Any], stash_api_key: str = "") -> requests.Session:
    """
    基于 server_conn 构建一个带 SessionCookie 的 requests 会话（参考 actorSyncEmby）
    
    Args:
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
    
    Returns:
        requests.Session 对象
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


# =============================================================================
# 图片下载（参考 actorSyncEmby）
# =============================================================================

def download_image(
    image_url: str,
    server_conn: Dict[str, Any],
    stash_api_key: str = ""
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    下载图片，返回图片数据和 Content-Type
    
    参考 actorSyncEmby 插件：
    - 使用 build_absolute_url 构建完整 URL
    - 使用 build_requests_session 创建带认证的 session
    - 下载图片到内存（不保存文件）
    
    Args:
        image_url: 图片路径（如 /studio/3/image?t=123）
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
    
    Returns:
        (image_bytes, content_type) 成功时返回元组，失败返回 (None, None)
    """
    try:
        # 构建完整 URL（参考 actorSyncEmby）
        abs_url = build_absolute_url(image_url, server_conn)
        
        # 创建带认证的 session（参考 actorSyncEmby）
        session = build_requests_session(server_conn, stash_api_key)
        
        # 下载图片（参考 actorSyncEmby）
        response = session.get(abs_url, timeout=30)
        
        if response.status_code == 200:
            # 从响应头获取 Content-Type（参考 actorSyncEmby）
            content_type = response.headers.get("Content-Type", "image/jpeg")
            return response.content, content_type
        
        return None, None
    
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 下载图片失败：{e}")
        return None, None


# =============================================================================
# 图片上传（参考 actorSyncEmby）
# =============================================================================

def _upload_image_to_emby(
    emby_server: str,
    emby_api_key: str,
    collection_id: str,
    image_type: str,
    image_data: bytes,
    content_type: str = "image/jpeg"
) -> bool:
    """
    上传图片到 Emby（内部函数，参考 actorSyncEmby 的 _upload_image_to_emby）

    Args:
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        collection_id: Emby 合集 ID
        image_type: 图片类型（Primary 或 Logo）
        image_data: 图片二进制数据
        content_type: 图片 Content-Type

    Returns:
        上传是否成功
    """
    try:
        # Base64 编码（参考 actorSyncEmby）
        b64_image = base64.b64encode(image_data)
        
        # 构建上传 URL（参考 actorSyncEmby：api_key 在 URL 中）
        upload_url = f'{emby_server}/emby/Items/{collection_id}/Images/{image_type}?api_key={emby_api_key}'
        headers = {'Content-Type': content_type}
        
        # 发送 Base64 编码的数据（参考 actorSyncEmby）
        response = requests.post(
            url=upload_url,
            data=b64_image,
            headers=headers,
            timeout=60
        )
        
        if response.status_code in [200, 204]:
            log.info(f"[{PLUGIN_ID}] ✓ {image_type}图片已上传")
            return True
        
        log.error(
            f"[{PLUGIN_ID}] 上传{image_type}图片失败："
            f"{response.status_code} - {response.text[:500] if response.text else ''}"
        )
        return False

    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 上传{image_type}图片失败：{e}")
        return False


# =============================================================================
# 元数据上传（参考 actorSyncEmby）
# =============================================================================

def upload_metadata(
    collection_id: str,
    emby_data: dict,
    emby_server: str,
    emby_api_key: str,
    user_id: str
) -> bool:
    """
    上传合集元数据到 Emby

    参考 actorSyncEmby 插件：
    - 先获取 Emby 现有数据
    - 在现有数据基础上更新（保留原有数据）
    - POST 完整数据回去

    Args:
        collection_id: Emby 合集 ID
        emby_data: 要更新的元数据
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        user_id: Emby 用户 ID（用于获取现有数据）

    Returns:
        上传是否成功
    """
    try:
        # 第 1 步：获取合集现有数据（参考 actorSyncEmby）
        get_url = f"{emby_server}/emby/Users/{user_id}/Items/{collection_id}?api_key={emby_api_key}"
        get_response = requests.get(get_url, timeout=30)
        
        if get_response.status_code != 200:
            log.error(f"[{PLUGIN_ID}] 获取合集现有数据失败：{get_response.status_code}")
            return False
        
        # 获取现有数据
        existing_data = get_response.json()

        # 第 2 步：在现有数据基础上，直接覆盖所有我们有能力写入的字段
        existing_data["Overview"] = emby_data.get("Overview", "")
        existing_data["TagItems"] = emby_data.get("TagItems", [])
        existing_data["CommunityRating"] = emby_data.get("CommunityRating")

        # 只更新 ProviderIds 中的 Stash 相关字段，不覆盖整个 ProviderIds
        # 这样保留原有的 themoviedb、tvdb、imdb 等其他提供者 ID
        if "ProviderIds" not in existing_data:
            existing_data["ProviderIds"] = {}

        provider_ids_to_update = emby_data.get("ProviderIds", {})
        for key, value in provider_ids_to_update.items():
            existing_data["ProviderIds"][key] = value

        # 第 3 步：POST 完整数据回去（参考 actorSyncEmby）
        update_url = f"{emby_server}/emby/Items/{collection_id}?api_key={emby_api_key}"
        response = requests.post(
            update_url,
            json=existing_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code in [200, 204]:
            log.info(f"[{PLUGIN_ID}] ✓ 元数据已更新")
            return True
        
        log.error(
            f"[{PLUGIN_ID}] 更新元数据失败："
            f"{response.status_code} - {response.text[:200] if response.text else ''}"
        )
        return False
    
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 更新元数据失败：{e}")
        return False


# =============================================================================
# 统一上传入口（对外接口）
# =============================================================================

def upload_studio_to_emby(
    emby_data: Dict[str, Any],
    collection_id: str,
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    server_conn: Dict[str, Any],
    stash_api_key: str = ""
) -> bool:
    """
    上传工作室到 Emby（统一上传入口）

    职责：接收已构建好的 emby_data，负责上传元数据和图片

    参考 actorSyncEmby 插件：
    - 先上传元数据
    - 再下载并上传图片

    Args:
        emby_data: 已构建好的 Emby 数据（由 utils.build_emby_data 构建）
        collection_id: Emby 合集 ID
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        user_id: Emby 用户 ID（用于获取现有数据）
        server_conn: Stash 服务器连接信息（用于下载图片）
        stash_api_key: Stash API 密钥（用于下载图片）

    Returns:
        上传是否成功
    """
    # 上传元数据
    if not upload_metadata(
        collection_id=collection_id,
        emby_data=emby_data,
        emby_server=emby_server,
        emby_api_key=emby_api_key,
        user_id=user_id
    ):
        return False

    # 上传图片
    if emby_data.get("_image_path"):
        image_url = emby_data["_image_path"]

        # 下载图片，获取图片数据和 Content-Type（参考 actorSyncEmby）
        image_bytes, content_type = download_image(image_url, server_conn, stash_api_key)

        if not image_bytes:
            log.error(f"[{PLUGIN_ID}] 下载图片失败：{image_url}")
            return False

        # 使用从 Stash 获取的 Content-Type 上传图片（参考 actorSyncEmby）
        if not _upload_image_to_emby(
            emby_server=emby_server,
            emby_api_key=emby_api_key,
            collection_id=collection_id,
            image_type="Primary",
            image_data=image_bytes,
            content_type=content_type
        ):
            return False

        if not _upload_image_to_emby(
            emby_server=emby_server,
            emby_api_key=emby_api_key,
            collection_id=collection_id,
            image_type="Logo",
            image_data=image_bytes,
            content_type=content_type
        ):
            return False

    return True
