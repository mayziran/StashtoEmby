"""
演员同步插件 - Stash插件，用于同步演员信息到Emby

将Stash中的演员信息（图片和NFO文件）导出到指定目录，
并可选择性地将这些信息上传到Emby服务器。

版本: 1.0.0
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from urllib.parse import urlparse, quote

import requests
import stashapi.log as log
from stashapi.stashapp import StashInterface

# 必须和 YAML 文件名（不含扩展名）对应
PLUGIN_ID = "actorSyncEmby"

# 常见图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


def task_log(message: str, progress: float | None = None) -> None:
    """
    向 Stash Task 界面输出一行 JSON 日志，可选带 progress（0~1）。
    """
    try:
        payload: Dict[str, Any] = {"output": str(message)}
        if progress is not None:
            try:
                p = float(progress)
                if p < 0:
                    p = 0.0
                if p > 1:
                    p = 1.0
                payload["progress"] = p
            except Exception:
                pass
        print(json.dumps(payload), flush=True)
    except Exception as e:
        # 不能因为日志输出失败导致任务崩溃
        log.error(f"[{PLUGIN_ID}] Failed to write task log: {e}")


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
    """
    return StashInterface(server_connection)


def load_settings(stash: StashInterface) -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings。
    """
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "actor_output_dir": "",
            "export_actor_nfo": True,
            "download_actor_images": True,
            "sync_to_emby": False,
            "sync_mode": 1,
            "emby_server": "",
            "emby_api_key": "",
            "dry_run": False,
        }

    plugins_settings = cfg.get("plugins", {}).get(PLUGIN_ID, {})

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    # 基本选项
    actor_output_dir = _get_val("actorOutputDir", "")
    export_actor_nfo = bool(_get_val("exportActorNfo", True))
    download_actor_images = bool(_get_val("downloadActorImages", True))
    sync_to_emby = bool(_get_val("syncToEmby", False))
    sync_mode = int(_get_val("syncMode", 1))  # 默认模式1
    emby_server = _get_val("embyServer", "")
    emby_api_key = _get_val("embyApiKey", "")
    dry_run = bool(_get_val("dryRun", False))

    log.info(
        f"Loaded settings: actor_output_dir='{actor_output_dir}', "
        f"export_actor_nfo={export_actor_nfo}, download_actor_images={download_actor_images}, "
        f"sync_to_emby={sync_to_emby}, sync_mode={sync_mode}, emby_server='{emby_server}', "
        f"dry_run={dry_run}"
    )

    return {
        "actor_output_dir": actor_output_dir,
        "export_actor_nfo": export_actor_nfo,
        "download_actor_images": download_actor_images,
        "sync_to_emby": sync_to_emby,
        "sync_mode": sync_mode,
        "emby_server": emby_server,
        "emby_api_key": emby_api_key,
        "dry_run": dry_run,
    }


def safe_segment(segment: str) -> str:
    """
    简单清理路径段，避免出现奇怪字符。
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



def _build_requests_session(settings: Dict[str, Any]) -> requests.Session:
    """
    基于 server_connection 构建一个带 SessionCookie 的 requests 会话，
    用于从 Stash 下载演员图片。
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

                # 根据AutoMoveOrganized的做法，固定使用传入的路径，不添加扩展名
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
            log.error(f"下载失败(第{attempt}次) '{url}' -> '{dst_path}': {e}")
            if attempt < max_attempts:
                # 简单退避
                time.sleep(2 * attempt)

    log.error(f"下载失败，已重试 {max_attempts} 次仍失败 '{url}' -> '{dst_path}': {last_error}")
    return False


def write_actor_nfo(actor_dir: str, performer: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    为单个演员生成/覆盖 actor.nfo 文件，写入所有可用信息。
    结构示例：
      <person>
        <name>Actor Name</name>
        <gender>female</gender>
        <country>US</country>
        <birthdate>1990-01-01</birthdate>
        <height_cm>170</height_cm>
        <measurements>90-60-90</measurements>
        <fake_tits>true</fake_tits>
        <disambiguation>...</disambiguation>
        <ethnicity>Caucasian</ethnicity>
        <eye_color>Blue</eye_color>
        <hair_color>Brunette</hair_color>
        <career_length>2010-</career_length>
        <tattoos>Left arm</tattoos>
        <piercings>Navel</piercings>
        <weight>55</weight>
        <penis_length>15</penis_length>
        <death_date>2020-01-01</death_date>
        <aliases>Alias1 / Alias2 / Alias3</aliases>
        <urls>url1\nurl2\nurl3</urls>
      </person>
    """
    if not settings.get("export_actor_nfo", True):
        return

    name = performer.get("name")
    if not name:
        return

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
        # 只保留非空的URL
        valid_urls = [url for url in urls if url and isinstance(url, str) and url.strip()]
        if valid_urls:
            urls_str = "\n".join(valid_urls)
            _set("urls", urls_str)

    # 添加Stash ID作为外部标识符
    stash_id = performer.get("id")
    if stash_id:
        _set("stash_id", stash_id)

    nfo_path = os.path.join(actor_dir, "actor.nfo")

    if settings.get("dry_run"):
        try:
            xml_str = ET.tostring(root, encoding="unicode")
        except Exception:
            xml_str = "<person>...</person>"
        log.info(f"[dry_run] Would write actor NFO for '{name}' -> {nfo_path}")
        log.info(xml_str)
        return

    # 由于NFO文件是上传到Emby的中间步骤，不跳过已存在的NFO文件
    # 根据同步模式，可能需要重新生成NFO以上传到Emby

    try:
        os.makedirs(actor_dir, exist_ok=True)
        tree = ET.ElementTree(root)
        tree.write(nfo_path, encoding="utf-8", xml_declaration=True)
        log.info(f"Wrote actor NFO for '{name}' -> {nfo_path}")
    except Exception as e:
        log.error(f"写入演员 NFO 失败 '{nfo_path}': {e}")


def export_actor_data(performer: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    导出单个演员的数据（图片和NFO）。
    """
    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过")
        return

    # 确定演员数据保存的根目录
    actors_root = settings.get("actor_output_dir", "").strip()

    # 如果既不导出NFO也不下载图片，且不上传到Emby，则无需导出数据
    export_actor_nfo = settings.get("export_actor_nfo", True)
    download_actor_images = settings.get("download_actor_images", True)
    sync_to_emby = settings.get("sync_to_emby", False)

    if not export_actor_nfo and not download_actor_images and not sync_to_emby:
        log.info("无需导出演员数据，跳过")
        return

    if not actors_root:
        log.error("未配置演员输出目录")
        return

    # 以清洗过的名字作为子目录
    safe_name = safe_segment(name)
    actor_dir = os.path.join(actors_root, safe_name)

    dry_run = settings.get("dry_run", False)
    if not dry_run:
        os.makedirs(actor_dir, exist_ok=True)

    sync_mode = settings.get("sync_mode", 1)

    # 模式3：先检查Emby中缺失什么，然后只处理缺失的部分（下载到本地覆盖后再上传到Emby）
    if sync_mode == 3 and settings.get("sync_to_emby", False):
        # 模式3在export_actor_data阶段不生成本地文件，只记录日志
        # 实际的下载和上传在upload_actor_to_emby阶段进行
        log.info(f"模式3：将在上传阶段处理缺失内容 (演员: {name})")
        # 模式3不在此阶段生成任何本地文件
    else:
        # 模式1和模式2：按原有逻辑处理
        # 1) 下载演员图片 -> folder.jpg
        image_url = performer.get("image_path")
        if settings.get("download_actor_images", True) and image_url:
            dst_path = os.path.join(actor_dir, "folder.jpg")
            abs_url = build_absolute_url(image_url, settings)

            if dry_run:
                log.info(f"[dry_run] Would download actor image: '{abs_url}' -> '{dst_path}'")
            else:
                # 根据同步模式决定是否下载
                should_download = False

                if sync_mode == 1:  # 模式1：覆盖 - 总是重新下载
                    should_download = True
                elif sync_mode == 2:  # 模式2：只处理元数据，不处理本地图片
                    should_download = False  # 模式2不下载本地图片
                else:  # 模式其他情况：如果文件已存在则跳过
                    if os.path.exists(dst_path):
                        log.info(f"Actor image already exists, skip: {dst_path}")
                        should_download = False
                    else:
                        should_download = True

                if should_download:
                    success = _download_binary(abs_url, dst_path, settings, detect_ext=False)
                    if success:
                        log.info(f"Downloaded actor image: '{abs_url}' -> '{dst_path}'")
                    else:
                        log.error(f"Failed to download actor image: '{abs_url}' -> '{dst_path}'")

        # 2) 生成演员 NFO
        write_actor_nfo(actor_dir, performer, settings)




def _upload_image_to_emby(emby_server: str, emby_api_key: str, actor_id: str, img_path: str, name: str, user_id: str = None, sync_mode: int = 1) -> bool:
    """
    通用的图片上传函数，供所有同步模式使用
    """
    with open(img_path, 'rb') as f:
        b6_pic = base64.b64encode(f.read())

    # 根据是否有user_id决定使用哪个端点
    if user_id:
        upload_url = f'{emby_server}/emby/Users/{user_id}/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'
    else:
        upload_url = f'{emby_server}/emby/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'

    headers = {'Content-Type': 'image/jpg'}
    
    try:
        r_upload = requests.post(url=upload_url, data=b6_pic, headers=headers)
    except requests.exceptions.RequestException as e:
        log.error(f"上传演员 {name} 头像到Emby时发生网络错误: {e}")
        return False

    # 如果用户特定端点失败，尝试直接Items端点
    if r_upload.status_code not in [200, 204] and user_id:
        log.debug(f"用户特定端点上传图片失败，状态码: {r_upload.status_code}，尝试直接Items端点")
        upload_url = f'{emby_server}/emby/Items/{actor_id}/Images/Primary?api_key={emby_api_key}'
        try:
            r_upload = requests.post(url=upload_url, data=b6_pic, headers=headers)
        except requests.exceptions.RequestException as e:
            log.error(f"上传演员 {name} 头像到Emby时发生网络错误: {e}")
            return False

    if r_upload.status_code in [200, 204]:
        log.info(f"成功上传演员 {name} 的头像到Emby (模式{sync_mode})")
        return True
    else:
        log.error(f"上传演员 {name} 头像到Emby失败，状态码: {r_upload.status_code}")
        return False


def upload_actor_to_emby(performer: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    将演员信息上传到Emby服务器。
    """
    if not settings.get("sync_to_emby", False):
        return

    emby_server = settings.get("emby_server", "").strip()
    emby_api_key = settings.get("emby_api_key", "").strip()

    if not emby_server or not emby_api_key:
        log.error("Emby服务器地址或API密钥未配置，跳过上传")
        return

    name = performer.get("name")
    if not name:
        log.warning("演员没有名称，跳过上传到Emby")
        return

    try:
        # 获取演员在Emby中的ID
        # 首先尝试通过Persons端点获取
        encoded_name = quote(name)
        persons_url = f'{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}'

        # 尝试获取演员信息
        try:
            r = requests.get(persons_url)
        except requests.exceptions.RequestException as e:
            log.error(f"获取演员 {name} 信息时发生网络错误: {e}")
            return

        if r.status_code == 404:
            log.info(f"演员 {name} 在Emby Persons 中不存在，跳过上传")
            return
        elif r.status_code != 200:
            log.error(f"获取演员 {name} 信息失败，状态码: {r.status_code}")
            return

        data = r.json()
        actor_id = data['Id']

        # 根据同步模式处理
        sync_mode = settings.get("sync_mode", 1)

        # 模式3：先检查Emby中缺失什么，然后决定上传什么（新模式）
        if sync_mode == 3:
            # 检查Emby中是否已有图片和元数据
            try:
                # 首先尝试通过Persons端点获取演员信息（这是获取演员信息的标准方法）
                encoded_name = quote(name)
                person_url = f"{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}"
                
                try:
                    person_resp = requests.get(person_url)
                except requests.exceptions.RequestException as e:
                    log.error(f"获取演员 {name} 信息时发生网络错误: {e}")
                    return

                if person_resp.status_code == 200:
                    # 成功获取演员信息，获取ID用于后续操作
                    try:
                        person_data = person_resp.json()
                    except ValueError as e:  # json解析错误
                        log.error(f"解析演员 {name} 信息JSON时发生错误: {e}")
                        return
                    person_id = person_data.get('Id')

                    # 使用Items端点获取更详细的演员信息，包括图片和元数据状态
                    # 参考emby-toolkit，使用Users/{user_id}/Items/{item_id}端点
                    # 首先获取用户ID
                    users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
                    try:
                        users_response = requests.get(users_url)
                    except requests.exceptions.RequestException as e:
                        log.error(f"获取Emby用户列表时发生网络错误: {e}")
                        return
                    user_id = None
                    if users_response.status_code == 200:
                        try:
                            users_data = users_response.json()
                        except ValueError as e:
                            log.error(f"解析Emby用户列表JSON时发生错误: {e}")
                            return
                        if users_data:
                            user_id = users_data[0]['Id']
                    
                    if user_id:
                        item_detail_url = f"{emby_server}/emby/Users/{user_id}/Items/{person_id}"
                    else:
                        # 如果获取不到用户ID，使用通用端点
                        item_detail_url = f"{emby_server}/emby/Items/{person_id}"
                    
                    params = {
                        "api_key": emby_api_key,
                        "Fields": "Name,ImageTags,Overview,ProviderIds"
                    }

                    try:
                        item_resp = requests.get(item_detail_url, params=params)
                    except requests.exceptions.RequestException as e:
                        log.error(f"获取演员 {name} 详细信息时发生网络错误: {e}")
                        return

                    if item_resp.status_code == 200:
                        try:
                            item_data = item_resp.json()
                        except ValueError as e:
                            log.error(f"解析演员 {name} 详细信息JSON时发生错误: {e}")
                            return
                        
                        # 检查图片是否缺失
                        emby_has_image = bool(item_data.get('ImageTags', {}).get('Primary'))

                        # 检查元数据是否缺失（使用Overview作为判断依据）
                        emby_has_overview = bool(item_data.get('Overview'))

                        log.info(f"演员 {name} 在Emby中的状态: 图片{'已存在' if emby_has_image else '缺失'}, 元数据{'已存在' if emby_has_overview else '缺失'}")

                        # 根据Emby中缺失的内容决定是否上传
                        should_upload_image = not emby_has_image
                        should_update_metadata = not emby_has_overview

                        # 处理图片上传
                        if settings.get("download_actor_images", True) and should_upload_image:
                            # 模式3：先从Stash下载图片到本地覆盖，然后再上传到Emby
                            image_url = performer.get("image_path")
                            if image_url:
                                # 使用配置的输出目录（与模式1和2一致）
                                actors_root = settings.get("actor_output_dir", "").strip()
                                if actors_root:
                                    safe_name = safe_segment(name)
                                    img_path = os.path.join(actors_root, safe_name, "folder.jpg")
                                    
                                    # 从Stash下载图片到本地（覆盖已有的文件）
                                    abs_url = build_absolute_url(image_url, settings)
                                    download_success = _download_binary(abs_url, img_path, settings, detect_ext=False)

                                    if download_success:
                                        # 使用公共的图片上传函数
                                        _upload_image_to_emby(emby_server, emby_api_key, person_id, img_path, name, None, sync_mode)
                                    else:
                                        log.error(f"无法下载演员 {name} 的图片用于上传到Emby")
                                else:
                                    log.info(f"演员 {name} 没有配置输出目录，无法上传图片")
                            else:
                                log.info(f"演员 {name} 没有图片URL，无法上传图片")

                        elif not should_upload_image:
                            log.info(f"演员 {name} 的图片在Emby中已存在，跳过上传 (模式{sync_mode})")

                        # 处理元数据更新
                        if should_update_metadata:
                            # 如果导出NFO设置启用，则生成本地NFO文件（覆盖已有的）
                            if settings.get("export_actor_nfo", True):
                                actors_root = settings.get("actor_output_dir", "").strip()
                                if actors_root:
                                    safe_name = safe_segment(name)
                                    actor_dir = os.path.join(actors_root, safe_name)
                                    # 生成NFO文件到本地（覆盖已有的）
                                    write_actor_nfo(actor_dir, performer, settings)
                            # 更新Emby元数据（不受导出NFO设置影响）
                            update_actor_metadata_in_emby(performer, person_id, settings)
                        else:
                            log.info(f"演员 {name} 的元数据在Emby中已存在，跳过更新 (模式{sync_mode})")
                    else:
                        # 如果通过Items端点获取失败，但Persons端点成功，说明演员存在但获取详细信息失败
                        log.warning(f"无法获取演员 {name} 的详细信息，但演员存在于Emby中，跳过操作")
                elif person_resp.status_code == 404:
                    # 演员在Emby中不存在
                    log.info(f"在Emby中未找到演员 {name}，跳过上传（模式3只补齐已存在演员的缺失信息）")
                else:
                    # 其他错误状态
                    log.warning(f"查询演员 {name} 在Emby中的状态时出错，状态码: {person_resp.status_code}")
                    
                    
            except Exception as e:
                log.error(f"检查Emby中演员 {name} 的状态失败: {e}")
                
        else:
            # 模式1和模式2：按原有逻辑处理
            # 获取用户ID用于上传
            users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
            try:
                users_response = requests.get(users_url)
            except requests.exceptions.RequestException as e:
                log.error(f"获取Emby用户列表时发生网络错误: {e}")
                return
            user_id = None
            if users_response.status_code == 200:
                try:
                    users_data = users_response.json()
                except ValueError as e:
                    log.error(f"解析Emby用户列表JSON时发生错误: {e}")
                    return
                if users_data:
                    user_id = users_data[0]['Id']

            # 根据同步模式处理演员图片
            # 模式2不处理图片，只更新元数据
            if sync_mode != 2:
                image_path = performer.get("image_path")
                if image_path and settings.get("download_actor_images", True):
                    # 使用配置的输出目录（统一所有模式的处理方式）
                    actors_root = settings.get("actor_output_dir", "").strip()
                    if actors_root:
                        safe_name = safe_segment(name)
                        img_path = os.path.join(actors_root, safe_name, "folder.jpg")

                        if img_path and os.path.exists(img_path):
                            should_upload_image = False

                            if sync_mode == 1:  # 模式1：覆盖 - 总是上传
                                should_upload_image = True
                            else:  # 模式其他：如果本地文件存在则上传
                                should_upload_image = True

                            if should_upload_image:
                                # 使用公共的图片上传函数
                                _upload_image_to_emby(emby_server, emby_api_key, actor_id, img_path, name, user_id, sync_mode)
                        else:
                            log.warning(f"演员 {name} 的图片文件不存在: {img_path}")

            # 模式1（覆盖）、模式2（元数据覆盖）: 更新演员元数据
            if sync_mode in [1, 2]:
                update_actor_metadata_in_emby(performer, actor_id, settings)

    except Exception as e:
        log.error(f"上传演员 {name} 到Emby失败: {e}")


def update_actor_metadata_in_emby(performer: Dict[str, Any], actor_id: str, settings: Dict[str, Any]) -> None:
    """
    更新Emby中演员的元数据。
    """
    emby_server = settings.get("emby_server", "").strip()
    emby_api_key = settings.get("emby_api_key", "").strip()

    if not emby_server or not emby_api_key:
        return

    name = performer.get("name", "")
    if not name:
        log.error("演员名称为空，无法更新元数据")
        return

    # 获取Emby用户ID，用于后续API调用
    users_url = f"{emby_server}/emby/Users?api_key={emby_api_key}"
    try:
        users_response = requests.get(users_url)
    except requests.exceptions.RequestException as e:
        log.error(f"获取Emby用户列表时发生网络错误: {e}")
        return
    if users_response.status_code != 200:
        log.error(f"无法获取Emby用户列表，状态码: {users_response.status_code}")
        return

    try:
        users_data = users_response.json()
    except ValueError as e:
        log.error(f"解析Emby用户列表JSON时发生错误: {e}")
        return
    if not users_data:
        log.error("Emby中没有找到任何用户")
        return

    user_id = users_data[0]['Id']

    # 直接使用传入的 actor_id，不再重新搜索
    found_actor_id = actor_id
    log.info(f"使用传入的ID更新演员 {name} 的元数据，ID: {found_actor_id}")

    # 获取演员完整信息 - 使用传入的ID
    get_url = f"{emby_server}/emby/Users/{user_id}/Items/{found_actor_id}?api_key={emby_api_key}"
    try:
        r_get = requests.get(get_url)
    except requests.exceptions.RequestException as e:
        log.error(f"获取演员 {performer.get('name')} 完整信息时发生网络错误: {e}")
        return
    if r_get.status_code != 200:
        log.error(f"无法获取演员 {performer.get('name')} 的完整信息，状态码: {r_get.status_code}")
        log.debug(f"响应内容: {r_get.text}")
        return
    try:
        person_data = r_get.json()
    except ValueError as e:
        log.error(f"解析演员 {performer.get('name')} 完整信息JSON时发生错误: {e}")
        return

    # 整理元数据
    from datetime import datetime, timezone
    lines = []
    # 最优先的信息
    if performer.get('disambiguation'):
        lines.append("消歧义: " + performer['disambiguation'])

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
        gender_cn = gender_map_cn.get(performer['gender'], performer['gender'])  # 如果找不到对应中文，使用原文
        lines.append("性别: " + gender_cn)
    if performer.get('country'):
        lines.append("国家: " + performer["country"])
    if performer.get('ethnicity'):
        lines.append("人种: " + performer["ethnicity"])
    if performer.get('birthdate'):
        lines.append("出生日期: " + performer["birthdate"])
    if performer.get('death_date') and performer.get('death_date').strip():
        lines.append("去世日期: " + performer["death_date"])
    if performer.get('career_length'):
        lines.append("职业生涯: " + performer["career_length"])
    if performer.get('height_cm'):
        lines.append("身高: " + str(performer["height_cm"]) + " cm")
    if performer.get('weight'):
        lines.append("体重: " + str(performer["weight"]) + " kg")
    if performer.get('measurements'):
        lines.append("三围尺寸: " + performer["measurements"])
    if performer.get('fake_tits'):
        lines.append("假奶: " + performer["fake_tits"])
    if performer.get('penis_length'):
        lines.append("阴茎长度: " + str(performer["penis_length"]) + " cm")
    if performer.get('circumcised'):
        lines.append("割包皮: " + performer["circumcised"])

    # 其他信息
    if performer.get('eye_color'):
        lines.append("瞳孔颜色: " + performer["eye_color"])
    if performer.get('hair_color'):
        lines.append("头发颜色: " + performer["hair_color"])
    if performer.get('tattoos'):
        lines.append("纹身: " + performer["tattoos"])
    if performer.get('piercings'):
        lines.append("穿孔: " + performer["piercings"])

    # 添加别名信息
    alias_list = performer.get('alias_list', [])
    if alias_list and isinstance(alias_list, list) and len(alias_list) > 0:
        aliases_str = " / ".join([alias for alias in alias_list if alias])
        if aliases_str:
            lines.append("别名: " + aliases_str)

    # 添加Urls信息
    urls = performer.get('urls', [])
    if urls and isinstance(urls, list) and len(urls) > 0:
        # 只保留非空的URL
        valid_urls = [url for url in urls if url and isinstance(url, str) and url.strip()]
        if valid_urls:
            urls_str = "\n".join(valid_urls)  # 直接列出链接，不加"链接:"前缀
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
        # 将英文性别转换为中文
        gender_map_cn = {
            'MALE': '男性',
            'FEMALE': '女性',
            'TRANSGENDER_MALE': '跨性别男性',
            'TRANSGENDER_FEMALE': '跨性别女性',
            'INTERSEX': '间性人',
            'NON_BINARY': '非二元性别'
        }
        gender_cn = gender_map_cn.get(performer['gender'], performer['gender'])  # 如果找不到对应中文，使用原文
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

    # 添加Stash ID作为外部标识符
    stash_id = performer.get("id")
    if stash_id:
        # 确保ProviderIds字段存在
        if 'ProviderIds' not in person_data:
            person_data['ProviderIds'] = {}
        # 添加Stash ID
        person_data['ProviderIds']['Stash'] = str(stash_id)

    # 使用POST方法更新到Items端点
    update_url = f"{emby_server}/emby/Items/{found_actor_id}?api_key={emby_api_key}"
    try:
        r2 = requests.post(update_url, json=person_data, headers={"Content-Type": "application/json"})
        if r2.status_code in [200, 204]:
            log.info(f"成功更新演员 {performer.get('name')} 的元数据")
        else:
            log.error(f"更新演员 {performer.get('name')} 元数据失败，状态码: {r2.status_code}")
            log.debug(f"响应内容: {r2.text}")
    except requests.exceptions.RequestException as e:
        log.error(f"更新演员 {performer.get('name')} 元数据失败: {e}")


def sync_performer(performer_id: str, settings: Dict[str, Any], stash: StashInterface) -> bool:
    """
    同步单个演员到本地和Emby。
    """
    log.info(f"正在同步演员 ID: {performer_id}")

    try:
        # 获取演员详细信息
        performer = stash.find_performer(int(performer_id))
        if not performer:
            log.error(f"找不到ID为 {performer_id} 的演员")
            return False

        # 根据同步模式决定处理方式
        sync_mode = settings.get("sync_mode", 1)
        
        if sync_mode == 3:  # 补齐缺失的数据
            # 在模式3下，我们先检查Emby中缺失什么，然后只处理缺失的部分
            # export_actor_data函数已经处理了模式3的逻辑，只在需要时生成本地文件
            export_actor_data(performer, settings)
            
            # 然后上传到Emby
            upload_actor_to_emby(performer, settings)
        else:
            # 模式1和2：按原有逻辑处理
            # 导出演员数据（图片和NFO）
            export_actor_data(performer, settings)

            # 上传到Emby
            upload_actor_to_emby(performer, settings)

        log.info(f"成功同步演员 {performer_id}")
        return True
    except Exception as e:
        log.error(f"同步演员 {performer_id} 失败: {e}")
        return False


def get_all_performers(stash: StashInterface, per_page: int = 1000) -> List[Dict[str, Any]]:
    """
    分页获取所有演员。
    """
    all_performers: List[Dict[str, Any]] = []
    page = 1

    fragment = """
        id
        name
        image_path
        gender
        country
        birthdate
        height_cm
        measurements
        fake_tits
        disambiguation
    """

    while True:
        log.info(f"[{PLUGIN_ID}] Fetching performers page={page}, per_page={per_page}")
        try:
            page_performers = stash.find_performers(
                f=None,
                filter={"page": page, "per_page": per_page},
                fragment=fragment,
            )
        except Exception as e:
            log.error(f"获取演员列表失败: {e}")
            break

        if not page_performers:
            log.info(f"[{PLUGIN_ID}] No more performers at page={page}, stop paging")
            break

        log.info(f"[{PLUGIN_ID}] Got {len(page_performers)} performers in page={page}")
        all_performers.extend(page_performers)
        page += 1

    log.info(f"[{PLUGIN_ID}] Total performers fetched: {len(all_performers)}")
    return all_performers


def handle_hook_or_task(stash: StashInterface, args: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    统一入口：
    - 如果是 Hook（Performer.Update.Post），处理当前 Performer
    - 如果是 Task（手动在 Tasks 页面点执行），可以根据参数处理
    """
    
    # 1) Hook 模式：只处理单个 performer（通常从 Performer.Update.Post 触发）
    hook_ctx = (args or {}).get("hookContext") or {}
    performer_id = hook_ctx.get("id") or hook_ctx.get("performer_id")

    if performer_id is not None:
        performer_id = int(performer_id)
        log.info(f"[{PLUGIN_ID}] Hook mode, processing single performer id={performer_id}")

        # Hook模式下强制使用覆盖模式（模式1）
        hook_settings = dict(settings)
        hook_settings["sync_mode"] = 1  # 强制覆盖模式

        try:
            success = sync_performer(str(performer_id), hook_settings, stash)
            if success:
                msg = f"已同步演员 {performer_id}"
                log.info(msg)
                task_log(msg, progress=1.0)
                return msg
            else:
                msg = f"同步演员 {performer_id} 失败"
                log.error(msg)
                task_log(msg, progress=1.0)
                return msg
        except Exception as e:
            log.error(f"同步演员 {performer_id} 失败: {e}")
            error_msg = f"同步演员 {performer_id} 失败: {str(e)}"
            task_log(error_msg, progress=1.0)
            return error_msg

    # 2) Task 模式：处理所有演员
    log.info(f"[{PLUGIN_ID}] Task mode: processing all performers")
    task_log(f"[Task] 处理所有演员 (dry_run={settings.get('dry_run', False)})", progress=0.0)

    log.info("开始处理所有演员")
    all_performers = get_all_performers(stash)
    total_performers = len(all_performers)

    if total_performers == 0:
        msg = "没有找到任何演员"
        log.info(msg)
        task_log(msg, progress=1.0)
        return msg

    success_count = 0
    for i, performer in enumerate(all_performers):
        try:
            performer_id = performer.get("id")
            if performer_id:
                success = sync_performer(str(performer_id), settings, stash)
                if success:
                    success_count += 1
            progress = (i + 1) / total_performers
            task_log(f"处理演员 {performer.get('name', 'Unknown')} ({i+1}/{total_performers})", progress=progress)
        except Exception as e:
            log.error(f"处理演员 {performer.get('name', 'Unknown')} 失败: {e}")

    msg = f"处理了 {total_performers} 个演员，成功 {success_count} 个"
    log.info(msg)
    task_log(msg, progress=1.0)
    return msg


def main():
    json_input = read_input()  # 插件运行时从 stdin 读
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

    # 从全局配置获取stash API key
    try:
        cfg = stash.get_configuration()
        stash_api_key = cfg.get("general", {}).get("apiKey") or ""
        settings["stash_api_key"] = stash_api_key
    except Exception as e:
        log.error(f"获取stash配置失败: {e}")

    try:
        msg = handle_hook_or_task(stash, args, settings)
        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    # 输出必须是单行 JSON
    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()