"""
演员同步插件 - 将 Stash 演员信息同步到本地和 Emby

版本：1.1.2
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



def load_settings(stash: StashInterface, for_hook: bool = False, for_task: bool = False, task_mode: str = "task_local", stash_api_key: str = "") -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings，并根据模式导入对应模块。

    Args:
        stash: Stash 接口
        for_hook: 是否为 Hook 模式加载（只根据 hook_mode 判断）
        for_task: 是否为 Task 模式加载（只根据 task_mode 判断）
        task_mode: Task 模式标识（task_local/task_emby）
        stash_api_key: Stash API 密钥（可选）
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
    enable_worker_log = bool(_get_val("enableWorkerLog", True))
    worker_delays = _get_val("workerDelays", "35,70")

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
        # ========== Task 模式：根据传入的 task_mode 决定加载哪个模块 ==========
        # task_local: 只加载 local_exporter（如果 export_mode != 0）
        # task_emby: 只加载 emby_uploader（如果 upload_mode != 0）
        if task_mode in ("task_local", "local"):
            # 只加载本地导出模块（如果 export_mode != 0）
            if export_mode != 0:
                try:
                    from local_exporter import export_actor_to_local as local_export
                    local_exporter = {"export_actor_to_local": local_export}
                except Exception as e:
                    log.error(f"加载 local_exporter 失败：{e}")
            else:
                log.info(f"[{PLUGIN_ID}] export_mode=0，不加载 local_exporter")
        
        elif task_mode in ("task_emby", "emby"):
            # 只加载 Emby 上传模块（如果 upload_mode != 0）
            if upload_mode != 0:
                try:
                    from emby_uploader import upload_actor_to_emby as emby_upload
                    emby_uploader = {"upload_actor_to_emby": emby_upload}
                except Exception as e:
                    log.error(f"加载 emby_uploader 失败：{e}")
            else:
                log.info(f"[{PLUGIN_ID}] upload_mode=0，不加载 emby_uploader")

    # 日志：模块加载情况
    # hook_mode=0 时不警告（用户故意关闭 Hook）
    if for_hook and hook_mode == 0:
        pass  # 正常关闭，不警告
    elif local_exporter is None and emby_uploader is None:
        log.warning(f"[{PLUGIN_ID}] 警告：没有加载任何模块（export_mode={export_mode}, upload_mode={upload_mode}, hook_mode={hook_mode}）")

    return {
        "actor_output_dir": actor_output_dir,
        "export_mode": export_mode,
        "upload_mode": upload_mode,
        "hook_mode": hook_mode,
        "emby_server": emby_server,
        "emby_api_key": emby_api_key,
        "enableWorkerLog": enable_worker_log,
        "workerDelays": worker_delays,
        "local_exporter": local_exporter,
        "emby_uploader": emby_uploader,
        "stash_api_key": stash_api_key,  # 添加 stash_api_key
    }


def start_async_worker(performer: Dict[str, Any], settings: Dict[str, Any]) -> None:
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
        "performer": performer  # 直接传递演员数据，避免 Worker 重新获取
    }

    config_json = json.dumps(config, ensure_ascii=False)
    config_b64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')

    cmd = [sys.executable, worker_script, config_b64]
    log.info(f"[{PLUGIN_ID}] 启动后台工作脚本")

    try:
        # 必须重定向 stdout/stderr，否则子进程继承句柄会导致主脚本无法退出
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

    # 没有 API key 直接拒绝执行
    if not stash_api_key:
        out = {"error": "未获取到 Stash API key，请检查 Stash 配置"}
        print(json.dumps(out) + "\n")
        return

    # 判断运行模式：直接从 Task 或 Hook 触发
    args = json_input.get("args") or {}
    hook_ctx = args.get("hookContext")

    try:
        if hook_ctx:
            # ========== Hook 模式：演员创建/更新事件 ==========
            from hook_handler import handle_create_hook, handle_update_hook

            performer_id = int(hook_ctx.get("id", 0))
            hook_type = hook_ctx.get("type", "")

            # 为 Hook 加载模块（只看 hook_mode）
            settings = load_settings(stash, for_hook=True, stash_api_key=stash_api_key)
            settings["server_connection"] = server_conn

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
            from task_handler import task_local, task_emby

            # 根据 mode 参数决定执行哪个 Task（由 YML 的 defaultArgs 决定）
            mode = args.get("mode", "task_local")

            # 为 Task 加载模块（只加载对应模块）
            settings = load_settings(stash, for_task=True, task_mode=mode, stash_api_key=stash_api_key)
            settings["server_connection"] = server_conn

            if mode == "task_local":
                msg = task_local(stash, settings, task_log)
            elif mode == "task_emby":
                msg = task_emby(stash, settings, task_log)
        
        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"[{PLUGIN_ID}] 执行失败：{e}")
        out = {"error": str(e)}

    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
