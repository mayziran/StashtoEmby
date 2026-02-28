"""
StudioToCollection 插件主入口

架构:
    1. 判断模式（Hook / Task）
    2. 加载配置
    3. 调用 task_handler 或 hook_handler
"""

import json
import os
import subprocess
import sys
import base64
from typing import Any, Dict

import stashapi.log as log
from stashapi.stashapp import StashInterface

PLUGIN_ID = "StudioToCollection"


def task_log(message: str, progress: float | None = None) -> None:
    """向 Stash Task 界面输出日志"""
    try:
        payload: Dict[str, Any] = {"output": str(message)}
        if progress is not None:
            p = float(progress)
            payload["progress"] = max(0.0, min(1.0, p))
        print(json.dumps(payload), flush=True)
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] Task log 失败：{e}")


def read_input() -> Dict[str, Any]:
    """从 stdin 读取 Stash 插件输入"""
    raw = sys.stdin.read()
    return json.loads(raw) if raw else {}


def connect_stash(server_conn: Dict[str, Any]) -> StashInterface:
    """连接 Stash"""
    return StashInterface(server_conn)


def load_settings(stash: StashInterface) -> Dict[str, Any]:
    """从 Stash 配置读取插件设置"""
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "enable_hook": False,
            "emby_server": "",
            "emby_api_key": "",
            "dry_run": False,
            "worker_delays": "35,70",
            "scheduled_task_id": "",
            "enable_worker_log": True,
            "stash_api_key": "",
            "server_connection": {},
        }

    plugins_settings = cfg.get("plugins", {}).get(PLUGIN_ID, {})

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    settings = {
        "enable_hook": bool(_get_val("enableHook", False)),
        "emby_server": _get_val("embyServer", ""),
        "emby_api_key": _get_val("embyApiKey", ""),
        "dry_run": bool(_get_val("dryRun", False)),
        "worker_delays": _get_val("workerDelays", "35,70"),
        "scheduled_task_id": _get_val("scheduledTaskId", ""),
        "enable_worker_log": bool(_get_val("enableWorkerLog", True)),
        "stash_api_key": cfg.get("general", {}).get("apiKey") or "",
        "server_connection": {},
    }

    log.info(
        f"[{PLUGIN_ID}] 加载配置：enable_hook={settings['enable_hook']}, "
        f"emby_server='{settings['emby_server']}', dry_run={settings['dry_run']}, "
        f"worker_delays='{settings['worker_delays']}', enable_worker_log={settings['enable_worker_log']}"
    )

    return settings


def start_worker(studio_id: int, studio_name: str, emby_data: Dict[str, Any], collection_id: str, user_id: str, settings: Dict[str, Any]) -> None:
    """启动 worker 异步执行（Create Hook 专用）"""
    worker_script = os.path.join(os.path.dirname(__file__), "studio_sync_worker.py")
    
    # 构建 Stash URL
    server_conn = settings.get("server_connection", {})
    scheme = server_conn.get("Scheme", "http")
    host = server_conn.get("Host", "localhost")
    port = server_conn.get("Port", "9999")
    stash_url = f"{scheme}://{host}:{port}"
    
    # 解析延迟配置（格式："35,70"）
    worker_delays_str = settings.get("worker_delays", "35,70")
    try:
        delays_parts = worker_delays_str.split(",")
        stash_wait = int(delays_parts[0].strip()) if len(delays_parts) > 0 else 35
        emby_wait = int(delays_parts[1].strip()) if len(delays_parts) > 1 else 70
    except Exception:
        stash_wait, emby_wait = 35, 70
    
    config = {
        "emby_server": settings["emby_server"],
        "emby_api_key": settings["emby_api_key"],
        "stash_url": stash_url,
        "stash_api_key": settings["stash_api_key"],
        "studio_id": studio_id,
        "studio_name": studio_name,
        "emby_data": emby_data,  # 已构建好的数据
        "collection_id": collection_id,  # 合集 ID
        "user_id": user_id,  # Emby 用户 ID（hook 已获取）
        "dry_run": settings["dry_run"],
        "stash_wait": stash_wait,  # 等待 Stash 创建影片时间
        "emby_wait": emby_wait,  # 等待 Emby 扫描时间
        "scheduled_task_id": settings.get("scheduled_task_id"),  # 计划任务 ID
        "enable_worker_log": settings.get("enable_worker_log", True),  # 是否启用 worker 日志
    }
    
    config_b64 = base64.b64encode(json.dumps(config, ensure_ascii=False).encode('utf-8')).decode('ascii')
    cmd = [sys.executable, worker_script, config_b64]
    
    log.info(f"[{PLUGIN_ID}] 启动 worker: {studio_name} (延迟：{stash_wait}+{emby_wait}秒)")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    """主入口"""
    json_input = read_input()
    log.info(f"[{PLUGIN_ID}] 插件启动")

    server_conn = json_input.get("server_connection") or {}
    if not server_conn:
        print(json.dumps({"error": "Missing server_connection"}))
        return

    if server_conn.get("Host") == '0.0.0.0':
        server_conn["Host"] = "localhost"

    stash = connect_stash(server_conn)
    settings = load_settings(stash)
    settings["server_connection"] = server_conn

    # 导入处理器
    from hook_handler import handle_create_hook, handle_update_hook
    from task_handler import handle_task

    args = json_input.get("args") or {}
    hook_ctx = args.get("hookContext")

    try:
        if hook_ctx:
            # ========== Hook 模式 ==========
            studio_id = int(hook_ctx.get("id", 0))
            hook_type = hook_ctx.get("type", "")

            if not settings["enable_hook"]:
                log.info(f"[{PLUGIN_ID}] Hook 已关闭")
                msg = "Hook 响应已关闭"
            elif hook_type == "Studio.Create.Post":
                log.info(f"[{PLUGIN_ID}] Create Hook: id={studio_id}")
                msg = handle_create_hook(stash, studio_id, settings, start_worker)
            elif hook_type == "Studio.Update.Post":
                log.info(f"[{PLUGIN_ID}] Update Hook: id={studio_id}")
                msg = handle_update_hook(stash, studio_id, settings)
            else:
                msg = f"未知 Hook 类型：{hook_type}"
        else:
            # ========== Task 模式 ==========
            log.info(f"[{PLUGIN_ID}] Task 模式")
            msg = handle_task(stash, settings, task_log)

        print(json.dumps({"output": msg, "progress": 1.0}) + "\n")
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 执行失败：{e}")
        print(json.dumps({"error": str(e)}) + "\n")


if __name__ == "__main__":
    main()
