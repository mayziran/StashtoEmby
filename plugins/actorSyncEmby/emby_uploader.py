"""
Emby 上传模块 - 将演员信息上传到 Emby 服务器

提供演员图片和元数据的上传功能。

上传模式 (upload_mode):
    1 = 都上传 (图片 + 元数据)
    2 = 只上传元数据
    3 = 只上传图片
"""

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
import stashapi.log as log

from utils import safe_segment, build_absolute_url, build_requests_session


# Emby 用户 ID 缓存（避免重复获取）
_emby_user_cache = {}  # {cache_key: user_id}


def _get_emby_user_id(emby_server: str, emby_api_key: str) -> Optional[str]:
    """
    获取 Emby 用户 ID（带缓存）

    Args:
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥

    Returns:
        用户 ID，获取失败返回 None
    """
    cache_key = f"{emby_server}_{emby_api_key}"
    if cache_key in _emby_user_cache:
        return _emby_user_cache[cache_key]

    users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
    try:
        users_response = requests.get(users_url, timeout=10)
        if users_response.status_code == 200:
            users_data = users_response.json()
            if users_data:
                user_id = users_data[0]['Id']
                _emby_user_cache[cache_key] = user_id
                return user_id
    except Exception as e:
        log.error(f"获取 Emby 用户 ID 失败：{e}")
    return None


def _upload_image_to_emby(emby_server: str, emby_api_key: str, actor_id: str, name: str, image_data: bytes, content_type: str = "image/jpeg") -> bool:
    """上传图片到 Emby"""
    # Base64 编码
    b6_pic = base64.b64encode(image_data)

    # Persons（演员）使用直接 Items 端点
    upload_url = f'{emby_server}/emby/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'
    headers = {'Content-Type': content_type}

    try:
        r_upload = requests.post(url=upload_url, data=b6_pic, headers=headers, timeout=60)
    except requests.exceptions.Timeout:
        log.error(f"上传演员 {name} 头像到 Emby 超时（60 秒）")
        raise
    except requests.exceptions.RequestException as e:
        log.error(f"上传演员 {name} 头像到 Emby 时发生网络错误：{e}")
        raise

    if r_upload.status_code in [200, 204]:
        log.info(f"成功上传演员 {name} 的头像到 Emby")
        return True
    else:
        log.error(f"上传演员 {name} 头像到 Emby 失败，状态码：{r_upload.status_code}")
        return False


def update_actor_metadata_in_emby(performer: Dict[str, Any], actor_id: str, emby_server: str, emby_api_key: str) -> None:
    """
    更新 Emby 中演员的元数据。
    """
    if not emby_server or not emby_api_key:
        log.error("Emby 服务器地址或 API 密钥未配置")
        raise

    name = performer.get("name", "")
    if not name:
        log.error("演员名称为空，无法更新元数据")
        return

    # 获取 Emby 用户 ID（使用缓存）
    user_id = _get_emby_user_id(emby_server, emby_api_key)
    if not user_id:
        log.error("无法获取 Emby 用户 ID，无法更新元数据")
        raise

    # 直接使用传入的 actor_id，不再重新搜索
    found_actor_id = actor_id
    log.info(f"使用传入的 ID 更新演员 {name} 的元数据，ID: {found_actor_id}")

    # 获取演员完整信息 - 使用传入的 ID
    get_url = f"{emby_server}/emby/Users/{user_id}/Items/{found_actor_id}?api_key={emby_api_key}"
    try:
        r_get = requests.get(get_url, timeout=30)
    except requests.exceptions.Timeout:
        log.error(f"获取演员 {performer.get('name')} 完整信息超时（30 秒）")
        raise
    except requests.exceptions.RequestException as e:
        log.error(f"获取演员 {performer.get('name')} 完整信息时发生网络错误：{e}")
        raise
    if r_get.status_code != 200:
        log.error(f"无法获取演员 {performer.get('name')} 的完整信息，状态码：{r_get.status_code}")
        log.info(f"响应内容：{r_get.text}")
        raise
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
        r2 = requests.post(update_url, json=person_data, headers={"Content-Type": "application/json"}, timeout=30)
        if r2.status_code in [200, 204]:
            log.info(f"成功更新演员 {performer.get('name')} 的元数据")
        else:
            log.error(f"更新演员 {performer.get('name')} 元数据失败，状态码：{r2.status_code}")
            log.info(f"响应内容：{r2.text}")
            raise
    except requests.exceptions.Timeout:
        log.error(f"更新演员 {performer.get('name')} 元数据超时（30 秒）")
        raise
    except requests.exceptions.RequestException as e:
        log.error(f"更新演员 {performer.get('name')} 元数据失败：{e}")
        raise


def upload_actor_to_emby(
    performer: Dict[str, Any],
    emby_server: str,
    emby_api_key: str,
    server_conn: Dict[str, Any],
    stash_api_key: str,
    upload_mode: int = 1
) -> None:
    """
    将演员信息上传到 Emby 服务器（简化版）。

    Args:
        performer: 演员信息字典
        emby_server: Emby 服务器地址
        emby_api_key: Emby API 密钥
        server_conn: Stash 服务器连接信息
        stash_api_key: Stash API 密钥
        upload_mode: 上传模式
            1 = 都上传 (图片 + 元数据)
            2 = 只上传元数据
            3 = 只上传图片
    """
    if not emby_server or not emby_api_key:
        log.error("Emby 服务器地址或 API 密钥未配置")
        raise

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过上传到 Emby")
        return

    try:
        # 获取演员在 Emby 中的 ID
        encoded_name = quote(name)
        persons_url = f'{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}'

        try:
            r = requests.get(persons_url, timeout=30)
        except requests.exceptions.Timeout:
            log.error(f"查找演员 {name} 超时（30 秒）")
            raise
        except requests.exceptions.RequestException as e:
            log.error(f"获取演员 {name} 信息时发生网络错误：{e}")
            raise

        if r.status_code == 404:
            log.info(f"演员 {name} 在 Emby Persons 中不存在，跳过上传")
            return
        elif r.status_code != 200:
            log.error(f"获取演员 {name} 信息失败，状态码：{r.status_code}")
            raise

        data = r.json()
        actor_id = data['Id']

        # 模式 1 或 2：上传元数据
        if upload_mode in [1, 2]:
            update_actor_metadata_in_emby(performer, actor_id, emby_server, emby_api_key)

        # 模式 1 或 3：上传图片
        if upload_mode in [1, 3]:
            image_url = performer.get("image_path")
            if image_url:
                abs_url = build_absolute_url(image_url, server_conn)
                session = build_requests_session(server_conn, stash_api_key)
                try:
                    resp = session.get(abs_url, timeout=30)
                    if resp.status_code == 200:
                        # 使用 Stash 返回的 Content-Type
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
                        _upload_image_to_emby(emby_server, emby_api_key, actor_id, name, resp.content, content_type)
                    else:
                        log.error(f"从 Stash 获取演员 {name} 图片失败，状态码：{resp.status_code}")
                except Exception as e:
                    log.error(f"获取或上传演员 {name} 图片失败：{e}")
            else:
                log.warning(f"演员 {name} 没有图片 URL，无法上传图片")

    except Exception as e:
        log.error(f"上传演员 {name} 到 Emby 失败：{e}")
