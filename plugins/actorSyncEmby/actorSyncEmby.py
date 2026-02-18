"""
演员同步插件 - Stash 插件，用于同步演员信息到 Emby

将 Stash 中的演员信息（图片和 NFO 文件）导出到指定目录，
并可选择性地将这些信息上传到 Emby 服务器。

版本：1.0.8 - 重构版（Hook 和 Task 逻辑分离到独立模块）
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


def load_settings(stash: StashInterface) -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings，并根据模式导入对应模块。
    """
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "actor_output_dir": "",
            "export_mode": 3,
            "upload_mode": 1,
            "hook_mode": 3,
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
    export_mode = int(_get_val("exportMode", 1))
    upload_mode = int(_get_val("uploadMode", 1))
    hook_mode = int(_get_val("hookMode", 3))
    emby_server = _get_val("embyServer", "")
    emby_api_key = _get_val("embyApiKey", "")
    dry_run = bool(_get_val("dryRun", False))
    enable_worker_log = bool(_get_val("enableWorkerLog", True))

    log.info(
        f"Loaded settings: actor_output_dir='{actor_output_dir}', "
        f"export_mode={export_mode} (Task), upload_mode={upload_mode} (Task), "
        f"hook_mode={hook_mode} (0=关闭，1=只本地，2=只 Emby，3=同时), "
        f"emby_server='{emby_server}', dry_run={dry_run}"
    )

    # 根据模式导入模块
    local_exporter = None
    emby_uploader = None

    # ========== 加载 local_exporter 模块 ==========
    # Task 模式：export_mode != 0 时需要
    # Hook 模式：hook_mode in (1, 3) 时需要
    need_local_for_task = (export_mode != 0)
    need_local_for_hook = (hook_mode in (1, 3))
    
    if need_local_for_task or need_local_for_hook:
        try:
            from local_exporter import export_actor_to_local as local_export
            local_exporter = {"export_actor_to_local": local_export}
            log.info(f"[{PLUGIN_ID}] 已加载 local_exporter.export_actor_to_local")
        except Exception as e:
            log.error(f"加载 local_exporter 模块失败：{e}")
        
        # 补缺模式需要批量检查函数
        if export_mode == 4:
            try:
                from local_exporter import check_local_missing_batch as local_check
                local_exporter["check_local_missing_batch"] = local_check
                log.info(f"[{PLUGIN_ID}] 已加载 local_exporter.check_local_missing_batch")
            except Exception as e:
                log.error(f"加载 check_local_missing_batch 失败：{e}")

    # ========== 加载 emby_uploader 模块 ==========
    # Task 模式：upload_mode != 0 时需要
    # Hook 模式：hook_mode in (2, 3) 时需要
    need_emby_for_task = (upload_mode != 0)
    need_emby_for_hook = (hook_mode in (2, 3))
    
    if need_emby_for_task or need_emby_for_hook:
        try:
            from emby_uploader import upload_actor_to_emby as emby_upload
            emby_uploader = {"upload_actor_to_emby": emby_upload}
            log.info(f"[{PLUGIN_ID}] 已加载 emby_uploader.upload_actor_to_emby")
        except Exception as e:
            log.error(f"加载 emby_uploader 模块失败：{e}")
        
        # 补缺模式需要批量检查函数
        if upload_mode == 4:
            try:
                from emby_uploader import check_emby_missing_batch as emby_check
                emby_uploader["check_emby_missing_batch"] = emby_check
                log.info(f"[{PLUGIN_ID}] 已加载 emby_uploader.check_emby_missing_batch")
            except Exception as e:
                log.error(f"加载 check_emby_missing_batch 失败：{e}")

    # ========== 日志：模块加载情况 ==========
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
        "local_exporter": local_exporter,
        "emby_uploader": emby_uploader,
    }


def start_async_worker(performer_id: int, settings: Dict[str, Any]) -> None:
    """启动后台工作脚本，异步执行演员同步到 Emby"""
    worker_script = os.path.join(os.path.dirname(__file__), "actor_sync_worker.py")

    config = {
        "emby_server": settings.get("emby_server", ""),
        "emby_api_key": settings.get("emby_api_key", ""),
        "stash_api_key": settings.get("stash_api_key", ""),
        "server_connection": settings.get("server_connection", {}),
        "upload_mode": 1,
        "enable_worker_log": settings.get("enableWorkerLog", True),
        "stash_url": f"http://{settings.get('server_connection', {}).get('Host', 'localhost')}:{settings.get('server_connection', {}).get('Port', '9999')}"
    }

    config_json = json.dumps(config, ensure_ascii=False)
    config_b64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')

    cmd = [sys.executable, worker_script, str(performer_id), config_b64]
    log.info(f"启动后台工作脚本")

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True)
        log.info(f"后台工作脚本已启动 (独立进程)")
    except Exception as e:
        log.error(f"启动后台工作脚本失败：{e}")


def sync_performer(performer: Dict[str, Any], settings: Dict[str, Any], stash: StashInterface) -> bool:
    """
    同步单个演员到本地和 Emby（用于 Task 模式 1/2/3）。
    """
    performer_id = performer.get("id")
    log.info(f"正在同步演员 ID: {performer_id}")

    export_mode = settings.get("export_mode", 1)
    upload_mode = settings.get("upload_mode", 1)

    try:
        if export_mode != 0:
            local_exporter = settings.get("local_exporter")
            if local_exporter:
                export_func = local_exporter.get("export_actor_to_local")
                if export_func:
                    export_func(
                        performer=performer,
                        actor_output_dir=settings.get("actor_output_dir", ""),
                        export_mode=export_mode,
                        server_conn=settings.get("server_connection", {}),
                        stash_api_key=settings.get("stash_api_key", ""),
                        dry_run=settings.get("dry_run", False)
                    )

        if upload_mode != 0:
            from emby_uploader import upload_actor_to_emby
            upload_actor_to_emby(
                performer=performer,
                emby_server=settings.get("emby_server", ""),
                emby_api_key=settings.get("emby_api_key", ""),
                server_conn=settings.get("server_connection", {}),
                stash_api_key=settings.get("stash_api_key", ""),
                upload_mode=upload_mode
            )

        log.info(f"成功同步演员 {performer_id}")
        return True
    except Exception as e:
        log.error(f"同步演员 {performer_id} 失败：{e}")
        return False


def handle_hook_or_task(stash: StashInterface, args: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """
    统一入口：
    - Hook：调用 hook_handler 模块
    - Task：调用 task_handler 模块
    """
    from hook_handler import handle_create_hook, handle_update_hook
    from task_handler import handle_task

    hook_ctx = (args or {}).get("hookContext") or {}
    performer_id = hook_ctx.get("id") or hook_ctx.get("performer_id")

    if performer_id is not None:
        performer_id = int(performer_id)
        hook_mode = settings.get("hook_mode", 3)

        if hook_mode == 0:
            log.info(f"[{PLUGIN_ID}] hook_mode=0，跳过 Hook 响应")
            return "Hook 响应已关闭"

        if hook_ctx.get("type") == "Performer.Create.Post":
            return handle_create_hook(stash, performer_id, settings)

        return handle_update_hook(stash, performer_id, settings, task_log)

    return handle_task(stash, settings, task_log)


def main():
    json_input = read_input()
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
    settings["server_connection"] = server_conn

    try:
        cfg = stash.get_configuration()
        stash_api_key = cfg.get("general", {}).get("apiKey") or ""
        settings["stash_api_key"] = stash_api_key
    except Exception as e:
        log.error(f"获取 stash 配置失败：{e}")

    try:
        msg = handle_hook_or_task(stash, args, settings)
        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
