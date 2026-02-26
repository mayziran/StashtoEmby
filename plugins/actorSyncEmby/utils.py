"""
工具模块 - 提供公共工具函数
"""

import re
from typing import Any, Dict

import requests


# stashapi 使用的 fragment 字符串（用于 find_performer 的 fragment 参数）
# 仅包含 emby_uploader 和 local_exporter 实际使用的字段（共 24 个）
# 避免获取不必要的数据（如 scene_count、关联对象等）
PERFORMER_FRAGMENT_FOR_API = """    id
    name
    disambiguation
    urls
    gender
    birthdate
    ethnicity
    country
    eye_color
    height_cm
    measurements
    fake_tits
    penis_length
    circumcised
    career_length
    tattoos
    piercings
    alias_list
    details
    death_date
    hair_color
    weight
    image_path
    tags {
        id
        name
    }"""


def safe_segment(segment: str) -> str:
    """简单清理路径段，避免出现奇怪字符。"""
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    return segment or "_"


def build_absolute_url(url: str, server_conn: Dict[str, Any]) -> str:
    """把相对路径补全为带协议/主机的绝对 URL，方便下载图片。"""
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


def build_requests_session(server_conn: Dict[str, Any], stash_api_key: str = "") -> requests.Session:
    """基于 server_connection 构建一个带 SessionCookie 的 requests 会话。"""
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
