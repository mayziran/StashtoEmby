"""
演员同步插件 - 将 Stash 演员信息同步到本地和 Emby

版本：1.0.8
"""

import json
import os
import subprocess
import sys
import base64
from typing import Any, Dict, List

import stashapi.log as log
from stashapi.stashapp import StashInterface

# 必须和 YAML 文件名（不含扩展名）对应
PLUGIN_ID = "actorSyncEmby"


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
    """用 stashapi 的 StashInterface 建立连接。"""
    return StashInterface(server_connection)


def load_settings(stash: StashInterface, for_hook: bool = False, for_task: bool = False) -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings，并根据模式导入对应模块。
    
    Args:
        stash: Stash 接口
        for_hook: 是否为 Hook 模式加载（只根据 hook_mode 判断）
        for_task: 是否为 Task 模式加载（只根据 export_mode/upload_mode 判断）
    """
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "actor_output_dir": "",
            "export_mode": 0,
            "upload_mode": 0,
            "hook_mode": 0,
            "emby_server": "",
            "emby_api_key": "",
            "dry_run": False,
            "enable_worker_log": True,
            "local_exporter": None,
            "emby_uploader": None,
        }

    plugins_settings = cfg.get("plugins", {}).get(PLUGIN_ID, {})

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    actor_output_dir = _get_val("actorOutputDir", "")
    export_mode = int(_get_val("exportMode", 0))
    upload_mode = int(_get_val("uploadMode", 0))
    hook_mode = int(_get_val("hookMode", 0))
    emby_server = _get_val("embyServer", "")
    emby_api_key = _get_val("embyApiKey", "")
    dry_run = bool(_get_val("dryRun", False))
    enable_worker_log = bool(_get_val("enableWorkerLog", True))
    worker_delays = _get_val("workerDelays", "35,70")

    log.info(
        f"Loaded settings: actor_output_dir='{actor_output_dir}', "
        f"export_mode={export_mode} (Task), upload_mode={upload_mode} (Task), "
        f"hook_mode={hook_mode} (Hook), "
        f"emby_server='{emby_server}', dry_run={dry_run}"
    )

    # 根据调用目的决定加载哪些模块
    local_exporter = None
    emby_uploader = None

    if for_hook:
        # ========== Hook 模式：只看 hook_mode ==========
        # hook_mode: 0=关闭，1=只本地，2=只 Emby，3=同时
        need_local = (hook_mode in (1, 3))
        need_emby = (hook_mode in (2, 3))

        if need_local:
            try:
                from local_exporter import export_actor_to_local as local_export
                local_exporter = {"export_actor_to_local": local_export}
                log.info(f"[{PLUGIN_ID}] 已加载 local_exporter (Hook)")
            except Exception as e:
                log.error(f"加载 local_exporter 失败：{e}")

        if need_emby:
            try:
                from emby_uploader import upload_actor_to_emby as emby_upload
                emby_uploader = {"upload_actor_to_emby": emby_upload}
                log.info(f"[{PLUGIN_ID}] 已加载 emby_uploader (Hook)")
            except Exception as e:
                log.error(f"加载 emby_uploader 失败：{e}")

    elif for_task:
        # ========== Task 模式：只看 export_mode/upload_mode ==========
        # export_mode/upload_mode: 0=不执行，1-3=覆盖/只 NFO/只图片，4=补缺
        need_local = (export_mode != 0)
        need_emby = (upload_mode != 0)

        if need_local:
            try:
                from local_exporter import export_actor_to_local as local_export
                local_exporter = {"export_actor_to_local": local_export}
                log.info(f"[{PLUGIN_ID}] 已加载 local_exporter (Task)")
            except Exception as e:
                log.error(f"加载 local_exporter 失败：{e}")

        if need_emby:
            try:
                from emby_uploader import upload_actor_to_emby as emby_upload
                emby_uploader = {"upload_actor_to_emby": emby_upload}
                log.info(f"[{PLUGIN_ID}] 已加载 emby_uploader (Task)")
            except Exception as e:
                log.error(f"加载 emby_uploader 失败：{e}")

    # 日志：模块加载情况
    if local_exporter is None and emby_uploader is None:
        log.warning(f"[{PLUGIN_ID}] 警告：没有加载任何模块（export_mode={export_mode}, upload_mode={upload_mode}, hook_mode={hook_mode}）")

    return {
        "actor_output_dir": actor_output_dir,
        "export_mode": export_mode,
        "upload_mode": upload_mode,
        "hook_mode": hook_mode,
        "emby_server": emby_server,
        "emby_api_key": emby_api_key,
        "dry_run": dry_run,
        "enableWorkerLog": enable_worker_log,
        "workerDelays": worker_delays,
        "local_exporter": local_exporter,
        "emby_uploader": emby_uploader,
    }


def start_async_worker(performer_id: int, settings: Dict[str, Any]) -> None:
    """启动后台 worker，异步上传演员到 Emby（Create Hook 专用）"""
    worker_script = os.path.join(os.path.dirname(__file__), "actor_sync_worker.py")

    config = {
        "emby_server": settings.get("emby_server", ""),
        "emby_api_key": settings.get("emby_api_key", ""),
        "stash_api_key": settings.get("stash_api_key", ""),
        "server_connection": settings.get("server_connection", {}),
        "upload_mode": 1,
        "enable_worker_log": settings.get("enableWorkerLog", True),
        "worker_delays": settings.get("workerDelays", "35,70"),
        "stash_url": f"http://{settings.get('server_connection', {}).get('Host', 'localhost')}:{settings.get('server_connection', {}).get('Port', '9999')}"
    }

    config_json = json.dumps(config, ensure_ascii=False)
    config_b64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')

    cmd = [sys.executable, worker_script, str(performer_id), config_b64]
    log.info(f"[{PLUGIN_ID}] 启动后台工作脚本")

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True)
        log.info(f"[{PLUGIN_ID}] 后台工作脚本已启动 (独立进程)")
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 启动后台工作脚本失败：{e}")


def main():
    """插件主入口：Hook 模式（演员事件）或 Task 模式（批量同步）"""
    json_input = read_input()
    log.info(f"[{PLUGIN_ID}] 插件启动")
    
    server_conn = json_input.get("server_connection") or {}
    if not server_conn:
        out = {"error": "Missing server_connection in input"}
        print(json.dumps(out))
        return

    if server_conn.get("Host") == '0.0.0.0':
        server_conn["Host"] = "localhost"

    # 连接 Stash
    stash = connect_stash(server_conn)

    # 获取 Stash API Key
    try:
        cfg = stash.get_configuration()
        stash_api_key = cfg.get("general", {}).get("apiKey") or ""
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 获取 stash 配置失败：{e}")
        stash_api_key = ""

    # 判断运行模式：直接从 Task 或 Hook 触发
    args = json_input.get("args") or {}
    hook_ctx = args.get("hookContext")

    # 导入处理器模块
    from hook_handler import handle_create_hook, handle_update_hook
    from task_handler import handle_task

    try:
        if hook_ctx:
            # ========== Hook 模式：演员创建/更新事件 ==========
            performer_id = int(hook_ctx.get("id", 0))
            hook_type = hook_ctx.get("type", "")

            # 为 Hook 加载模块（只看 hook_mode）
            settings = load_settings(stash, for_hook=True)
            settings["server_connection"] = server_conn
            settings["stash_api_key"] = stash_api_key

            hook_mode = settings.get("hook_mode", 0)

            if hook_mode == 0:
                log.info(f"[{PLUGIN_ID}] hook_mode=0，跳过 Hook 响应")
                msg = "Hook 响应已关闭"
            elif hook_type == "Performer.Create.Post":
                log.info(f"[{PLUGIN_ID}] Hook 模式：演员创建 (id={performer_id})")
                msg = handle_create_hook(stash, performer_id, settings)
            elif hook_type == "Performer.Update.Post":
                log.info(f"[{PLUGIN_ID}] Hook 模式：演员更新 (id={performer_id})")
                msg = handle_update_hook(stash, performer_id, settings, task_log)
            else:
                log.warning(f"[{PLUGIN_ID}] 未知的 Hook 类型：{hook_type}")
                msg = f"未知的 Hook 类型：{hook_type}"
        else:
            # ========== Task 模式：手动执行批量任务 ==========
            log.info(f"[{PLUGIN_ID}] Task 模式：同步所有演员")
            
            # 为 Task 加载模块（只看 export_mode/upload_mode）
            settings = load_settings(stash, for_task=True)
            settings["server_connection"] = server_conn
            settings["stash_api_key"] = stash_api_key
            
            msg = handle_task(stash, settings, task_log)
        
        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 执行失败：{e}")
        out = {"error": str(e)}

    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
