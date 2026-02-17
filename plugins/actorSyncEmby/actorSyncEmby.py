"""
演员同步插件 - Stash插件，用于同步演员信息到Emby

将Stash中的演员信息（图片和NFO文件）导出到指定目录，
并可选择性地将这些信息上传到Emby服务器。

版本: 1.0.0
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import stashapi.log as log
from stashapi.stashapp import StashInterface

# 必须和 YAML 文件名（不含扩展名）对应
PLUGIN_ID = "actorSyncEmby"

# 导入 Emby 上传模块
from emby_uploader import upload_actor_to_emby as upload_to_emby, safe_segment, build_absolute_url, _download_binary


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
            abs_url = build_absolute_url(image_url, settings.get("server_connection", {}))

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
                    success = _download_binary(abs_url, dst_path, settings.get("server_connection", {}), settings.get("stash_api_key", ""), detect_ext=False)
                    if success:
                        log.info(f"Downloaded actor image: '{abs_url}' -> '{dst_path}'")
                    else:
                        log.error(f"Failed to download actor image: '{abs_url}' -> '{dst_path}'")

        # 2) 生成演员 NFO
        write_actor_nfo(actor_dir, performer, settings)





def upload_actor_to_emby(performer: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """
    将演员信息上传到 Emby 服务器（调用 emby_uploader 模块）。
    """
    emby_server = settings.get("emby_server", "").strip()
    emby_api_key = settings.get("emby_api_key", "").strip()
    server_conn = settings.get("server_connection", {})
    stash_api_key = settings.get("stash_api_key", "")
    actor_output_dir = settings.get("actor_output_dir", "").strip()
    sync_mode = settings.get("sync_mode", 1)
    download_images = settings.get("download_actor_images", True)

    upload_to_emby(
        performer=performer,
        emby_server=emby_server,
        emby_api_key=emby_api_key,
        server_conn=server_conn,
        stash_api_key=stash_api_key,
        actor_output_dir=actor_output_dir,
        sync_mode=sync_mode,
        download_images=download_images
    )


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