"""
Emby 上传模块 - 将演员信息上传到 Emby 服务器

提供演员图片和元数据的上传功能。
"""

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, quote

import requests
import stashapi.log as log

# 常见图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


def safe_segment(segment: str) -> str:
    """
    简单清理路径段，避免出现奇怪字符。
    """
    segment = segment.strip().replace("\\", "_").replace("/", "_")
    # 去掉常见非法字符
    segment = re.sub(r'[<>:"|?*]', "_", segment)
    # 防止空字符串
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

    # 最多重试 3 次
    max_attempts = 3
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.get(url, timeout=30, stream=True)
            resp.raise_for_status()

            # 默认直接使用调用方给的目标路径
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

                # 根据 AutoMoveOrganized 的做法，固定使用传入的路径，不添加扩展名
                final_path = dst_path

            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            log.info(f"下载完成 '{url}' -> '{final_path}'")
            return True
        except Exception as e:
            last_error = e
            log.error(f"下载失败 (第{attempt}次) '{url}' -> '{dst_path}': {e}")
            if attempt < max_attempts:
                # 简单退避
                time.sleep(2 * attempt)

    log.error(f"下载失败，已重试 {max_attempts} 次仍失败 '{url}' -> '{dst_path}': {last_error}")
    return False


def _upload_image_to_emby(emby_server: str, emby_api_key: str, actor_id: str, img_path: str, name: str, user_id: Optional[str] = None, sync_mode: int = 1) -> bool:
    """
    通用的图片上传函数，供所有同步模式使用
    """
    with open(img_path, 'rb') as f:
        b6_pic = base64.b64encode(f.read())

    # 根据是否有 user_id 决定使用哪个端点
    if user_id:
        upload_url = f'{emby_server}/emby/Users/{user_id}/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'
    else:
        upload_url = f'{emby_server}/emby/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'

    headers = {'Content-Type': 'image/jpg'}

    try:
        r_upload = requests.post(url=upload_url, data=b6_pic, headers=headers)
    except requests.exceptions.RequestException as e:
        log.error(f"上传演员 {name} 头像到 Emby 时发生网络错误：{e}")
        return False

    # 如果用户特定端点失败，尝试直接 Items 端点
    if r_upload.status_code not in [200, 204] and user_id:
        log.info(f"用户特定端点上传图片失败，状态码：{r_upload.status_code}，尝试直接 Items 端点")
        upload_url = f'{emby_server}/emby/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'
        try:
            r_upload = requests.post(url=upload_url, data=b6_pic, headers=headers)
        except requests.exceptions.RequestException as e:
            log.error(f"上传演员 {name} 头像到 Emby 时发生网络错误：{e}")
            return False

    if r_upload.status_code in [200, 204]:
        log.info(f"成功上传演员 {name} 的头像到 Emby (模式{sync_mode})")
        return True
    else:
        log.error(f"上传演员 {name} 头像到 Emby 失败，状态码：{r_upload.status_code}")
        return False


def update_actor_metadata_in_emby(performer: Dict[str, Any], actor_id: str, emby_server: str, emby_api_key: str) -> None:
    """
    更新 Emby 中演员的元数据。
    """
    if not emby_server or not emby_api_key:
        return

    name = performer.get("name", "")
    if not name:
        log.error("演员名称为空，无法更新元数据")
        return

    # 获取 Emby 用户 ID，用于后续 API 调用
    users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
    try:
        users_response = requests.get(users_url)
    except requests.exceptions.RequestException as e:
        log.error(f"获取 Emby 用户列表时发生网络错误：{e}")
        return
    if users_response.status_code != 200:
        log.error(f"无法获取 Emby 用户列表，状态码：{users_response.status_code}")
        return

    try:
        users_data = users_response.json()
    except ValueError as e:
        log.error(f"解析 Emby 用户列表 JSON 时发生错误：{e}")
        return
    if not users_data:
        log.error("Emby 中没有找到任何用户")
        return

    user_id = users_data[0]['Id']

    # 直接使用传入的 actor_id，不再重新搜索
    found_actor_id = actor_id
    log.info(f"使用传入的 ID 更新演员 {name} 的元数据，ID: {found_actor_id}")

    # 获取演员完整信息 - 使用传入的 ID
    get_url = f"{emby_server}/emby/Users/{user_id}/Items/{found_actor_id}?api_key={emby_api_key}"
    try:
        r_get = requests.get(get_url)
    except requests.exceptions.RequestException as e:
        log.error(f"获取演员 {performer.get('name')} 完整信息时发生网络错误：{e}")
        return
    if r_get.status_code != 200:
        log.error(f"无法获取演员 {performer.get('name')} 的完整信息，状态码：{r_get.status_code}")
        log.info(f"响应内容：{r_get.text}")
        return
    try:
        person_data = r_get.json()
    except ValueError as e:
        log.error(f"解析演员 {performer.get('name')} 完整信息 JSON 时发生错误：{e}")
        return

    # 整理元数据
    lines = []
    # 最优先的信息
    if performer.get('disambiguation'):
        lines.append("消歧义：" + performer['disambiguation'])

    # 优先级较高的信息
    if performer.get('gender'):
        # 将英文性别转换为中文
        gender_map_cn = {
            'MALE': '男性',
            'FEMALE': '女性',
            'TRANSGENDER_MALE': '跨性别男性',
            'TRANSGENDER_FEMALE': '跨性别女性',
            'INTERSEX': '间性人',
            'NON_BINARY': '非二元性别'
        }
        gender_cn = gender_map_cn.get(performer['gender'], performer['gender'])
        lines.append("性别：" + gender_cn)
    if performer.get('country'):
        lines.append("国家：" + performer["country"])
    if performer.get('ethnicity'):
        lines.append("人种：" + performer["ethnicity"])
    if performer.get('birthdate'):
        lines.append("出生日期：" + performer["birthdate"])
    if performer.get('death_date') and performer.get('death_date').strip():
        lines.append("去世日期：" + performer["death_date"])
    if performer.get('career_length'):
        lines.append("职业生涯：" + performer["career_length"])
    if performer.get('height_cm'):
        lines.append("身高：" + str(performer["height_cm"]) + " cm")
    if performer.get('weight'):
        lines.append("体重：" + str(performer["weight"]) + " kg")
    if performer.get('measurements'):
        lines.append("三围尺寸：" + performer["measurements"])
    if performer.get('fake_tits'):
        lines.append("假奶：" + performer["fake_tits"])
    if performer.get('penis_length'):
        lines.append("阴茎长度：" + str(performer["penis_length"]) + " cm")
    if performer.get('circumcised'):
        lines.append("割包皮：" + performer["circumcised"])

    # 其他信息
    if performer.get('eye_color'):
        lines.append("瞳孔颜色：" + performer["eye_color"])
    if performer.get('hair_color'):
        lines.append("头发颜色：" + performer["hair_color"])
    if performer.get('tattoos'):
        lines.append("纹身：" + performer["tattoos"])
    if performer.get('piercings'):
        lines.append("穿孔：" + performer["piercings"])

    # 添加别名信息
    alias_list = performer.get('alias_list', [])
    if alias_list and isinstance(alias_list, list) and len(alias_list) > 0:
        aliases_str = " / ".join([alias for alias in alias_list if alias])
        if aliases_str:
            lines.append("别名：" + aliases_str)

    # 添加 Urls 信息
    urls = performer.get('urls', [])
    if urls and isinstance(urls, list) and len(urls) > 0:
        valid_urls = [url for url in urls if url and isinstance(url, str) and url.strip()]
        if valid_urls:
            urls_str = "\n".join(valid_urls)
            lines.append("相关链接:\n" + urls_str)

    if lines:
        overview = '\n'.join(lines)
        person_data['Overview'] = overview

    # 更新生日信息
    if performer.get('birthdate'):
        birthdate = performer.get("birthdate")
        if birthdate:
            try:
                dt = datetime.strptime(birthdate, "%Y-%m-%d").replace(
                    hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
                )
                person_data["PremiereDate"] = dt.isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z")
            except Exception:
                person_data["PremiereDate"] = None

    # 更新死亡日期信息
    if performer.get('death_date') and performer.get('death_date').strip():
        deathdate = performer.get("death_date")
        if deathdate:
            try:
                dt = datetime.strptime(deathdate, "%Y-%m-%d").replace(
                    hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
                )
                person_data["EndDate"] = dt.isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z")
            except Exception:
                person_data["EndDate"] = None

    country = performer.get("country")
    if country:
        person_data["ProductionLocations"] = [country]

    # 添加标签（Tags）
    tag_items = []

    if performer.get('gender'):
        gender_map_cn = {
            'MALE': '男性',
            'FEMALE': '女性',
            'TRANSGENDER_MALE': '跨性别男性',
            'TRANSGENDER_FEMALE': '跨性别女性',
            'INTERSEX': '间性人',
            'NON_BINARY': '非二元性别'
        }
        gender_cn = gender_map_cn.get(performer['gender'], performer['gender'])
        tag_items.append({"Name": f"性别:{gender_cn}", "Id": None})
    if performer.get('country'):
        tag_items.append({"Name": f"国家:{performer['country']}", "Id": None})
    if performer.get('ethnicity'):
        tag_items.append({"Name": f"人种:{performer['ethnicity']}", "Id": None})
    if performer.get('fake_tits'):
        tag_items.append({"Name": f"假奶:{performer['fake_tits']}", "Id": None})
    if performer.get('circumcised'):
        tag_items.append({"Name": f"割包皮:{performer['circumcised']}", "Id": None})
    if performer.get('hair_color'):
        tag_items.append({"Name": f"头发颜色:{performer['hair_color']}", "Id": None})
    if performer.get('height_cm'):
        tag_items.append({"Name": f"身高:{performer['height_cm']}cm", "Id": None})
    if performer.get('weight'):
        tag_items.append({"Name": f"体重:{performer['weight']}kg", "Id": None})
    if performer.get('penis_length'):
        tag_items.append({"Name": f"阴茎长度:{performer['penis_length']}cm", "Id": None})

    if tag_items:
        person_data['TagItems'] = tag_items

    # 添加 Stash ID 作为外部标识符
    stash_id = performer.get("id")
    if stash_id:
        if 'ProviderIds' not in person_data:
            person_data['ProviderIds'] = {}
        person_data['ProviderIds']['Stash'] = str(stash_id)

    # 使用 POST 方法更新到 Items 端点
    update_url = f"{emby_server}/emby/Items/{found_actor_id}?api_key={emby_api_key}"
    try:
        r2 = requests.post(update_url, json=person_data, headers={"Content-Type": "application/json"})
        if r2.status_code in [200, 204]:
            log.info(f"成功更新演员 {performer.get('name')} 的元数据")
        else:
            log.error(f"更新演员 {performer.get('name')} 元数据失败，状态码：{r2.status_code}")
            log.info(f"响应内容：{r2.text}")
    except requests.exceptions.RequestException as e:
        log.error(f"更新演员 {performer.get('name')} 元数据失败：{e}")


def upload_actor_to_emby(
    performer: Dict[str, Any],
    emby_server: str,
    emby_api_key: str,
    server_conn: Dict[str, Any],
    stash_api_key: str,
    actor_output_dir: str,
    sync_mode: int = 1,
    download_images: bool = True
) -> None:
    """
    将演员信息上传到 Emby 服务器。
    
    Args:
        performer: 演员信息字典
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
        actor_output_dir: 演员数据输出目录
        sync_mode: 同步模式 (1=覆盖，2=只元数据，3=补齐缺失)
        download_images: 是否下载图片
    """
    if not emby_server or not emby_api_key:
        log.error("Emby 服务器地址或 API 密钥未配置，跳过上传")
        return

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过上传到 Emby")
        return

    try:
        # 获取演员在 Emby 中的 ID
        encoded_name = quote(name)
        persons_url = f'{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}'

        try:
            r = requests.get(persons_url)
        except requests.exceptions.RequestException as e:
            log.error(f"获取演员 {name} 信息时发生网络错误：{e}")
            return

        if r.status_code == 404:
            log.info(f"演员 {name} 在 Emby Persons 中不存在，跳过上传")
            return
        elif r.status_code != 200:
            log.error(f"获取演员 {name} 信息失败，状态码：{r.status_code}")
            return

        data = r.json()
        actor_id = data['Id']

        # 模式 3：先检查 Emby 中缺失什么，然后决定上传什么
        if sync_mode == 3:
            try:
                person_url = f"{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}"
                person_resp = requests.get(person_url)

                if person_resp.status_code == 200:
                    person_data = person_resp.json()
                    person_id = person_data.get('Id')

                    # 获取用户 ID
                    users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
                    users_response = requests.get(users_url)
                    user_id = None
                    if users_response.status_code == 200:
                        users_data = users_response.json()
                        if users_data:
                            user_id = users_data[0]['Id']

                    # 获取详细信息
                    if user_id:
                        item_detail_url = f"{emby_server}/emby/Users/{user_id}/Items/{person_id}"
                    else:
                        item_detail_url = f"{emby_server}/emby/Items/{person_id}"

                    params = {
                        "api_key": emby_api_key,
                        "Fields": "Name,ImageTags,Overview,ProviderIds"
                    }

                    item_resp = requests.get(item_detail_url, params=params)

                    if item_resp.status_code == 200:
                        item_data = item_resp.json()

                        # 检查图片和元数据状态
                        emby_has_image = bool(item_data.get('ImageTags', {}).get('Primary'))
                        emby_has_overview = bool(item_data.get('Overview'))

                        log.info(f"演员 {name} 在 Emby 中的状态：图片{'已存在' if emby_has_image else '缺失'}, 元数据{'已存在' if emby_has_overview else '缺失'}")

                        should_upload_image = not emby_has_image
                        should_update_metadata = not emby_has_overview

                        # 处理图片上传
                        if download_images and should_upload_image:
                            image_url = performer.get("image_path")
                            if image_url and actor_output_dir:
                                safe_name = safe_segment(name)
                                img_path = os.path.join(actor_output_dir, safe_name, "folder.jpg")
                                abs_url = build_absolute_url(image_url, server_conn)
                                download_success = _download_binary(abs_url, img_path, server_conn, stash_api_key, detect_ext=False)

                                if download_success:
                                    _upload_image_to_emby(emby_server, emby_api_key, person_id, img_path, name, None, sync_mode)
                                else:
                                    log.error(f"无法下载演员 {name} 的图片用于上传到 Emby")
                            else:
                                if not actor_output_dir:
                                    log.info(f"演员 {name} 没有配置输出目录，无法上传图片")
                                if not image_url:
                                    log.info(f"演员 {name} 没有图片 URL，无法上传图片")
                        elif not should_upload_image:
                            log.info(f"演员 {name} 的图片在 Emby 中已存在，跳过上传 (模式{sync_mode})")

                        # 处理元数据更新
                        if should_update_metadata:
                            update_actor_metadata_in_emby(performer, person_id, emby_server, emby_api_key)
                        else:
                            log.info(f"演员 {name} 的元数据在 Emby 中已存在，跳过更新 (模式{sync_mode})")
                    else:
                        log.warning(f"无法获取演员 {name} 的详细信息，但演员存在于 Emby 中，跳过操作")
                elif person_resp.status_code == 404:
                    log.info(f"在 Emby 中未找到演员 {name}，跳过上传（模式 3 只补齐已存在演员的缺失信息）")
                else:
                    log.warning(f"查询演员 {name} 在 Emby 中的状态时出错，状态码：{person_resp.status_code}")

            except Exception as e:
                log.error(f"检查 Emby 中演员 {name} 的状态失败：{e}")

        else:
            # 模式 1 和模式 2
            # 获取用户 ID 用于上传
            users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
            try:
                users_response = requests.get(users_url)
            except requests.exceptions.RequestException as e:
                log.error(f"获取 Emby 用户列表时发生网络错误：{e}")
                return
            user_id = None
            if users_response.status_code == 200:
                try:
                    users_data = users_response.json()
                except ValueError as e:
                    log.error(f"解析 Emby 用户列表 JSON 时发生错误：{e}")
                    return
                if users_data:
                    user_id = users_data[0]['Id']

            # 模式 2 不处理图片，只更新元数据
            if sync_mode != 2:
                image_path = performer.get("image_path")
                if image_path and download_images:
                    if actor_output_dir:
                        safe_name = safe_segment(name)
                        img_path = os.path.join(actor_output_dir, safe_name, "folder.jpg")

                        if img_path and os.path.exists(img_path):
                            should_upload_image = (sync_mode == 1)

                            if should_upload_image:
                                _upload_image_to_emby(emby_server, emby_api_key, actor_id, img_path, name, user_id, sync_mode)
                        else:
                            log.warning(f"演员 {name} 的图片文件不存在：{img_path}")

            # 模式 1 和 2：更新演员元数据
            if sync_mode in [1, 2]:
                update_actor_metadata_in_emby(performer, actor_id, emby_server, emby_api_key)

    except Exception as e:
        log.error(f"上传演员 {name} 到 Emby 失败：{e}")
