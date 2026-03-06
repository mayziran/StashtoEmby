#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_move_organized.py - Auto Move Organized 主入口

在场景更新后，把已整理 (organized) 的文件移动到指定目录，并按模板重命名。
支持 Hook 模式（自动响应场景更新）和 Task 模式（手动批量处理）。

模块结构：
- scene_fetcher.py: 场景获取
- path_builder.py: 路径构建
- file_mover.py: 文件移动
- metadata_handler.py: 元数据处理
- hook_handler.py: Hook 模式处理
- task_handler.py: Task 模式处理
"""

import json
import sys
from typing import Any, Dict

import stashapi.log as log
from stashapi.stashapp import StashInterface

# 必须和 YAML 里的 id 对应
PLUGIN_ID = "auto-move-organized"


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

    server_connection 就是 docs 里给的结构：
    {
        "Scheme": "...",
        "Port": ...,
        "SessionCookie": {...},
        "Dir": "...",
        "PluginDir": "..."
    }
    """
    return StashInterface(server_connection)


def load_settings(stash: StashInterface) -> Dict[str, Any]:
    """
    从 Stash 配置里读取本插件的 settings，并把常用的 AI 翻译配置也一并返回。
    """
    try:
        cfg = stash.get_configuration()
    except Exception as e:
        log.error(f"get_configuration failed: {e}")
        return {
            "target_root": "",
            "filename_template": "{original_basename}",
            "move_only_organized": True,
            "dry_run": False,
        }

    plugins_settings = cfg.get("plugins", {}).get("auto_move_organized", {})

    def _get_val(key: str, default):
        v = plugins_settings.get(key, default)
        if isinstance(v, dict) and "value" in v:
            return v.get("value", default)
        return v

    # 基本选项
    target_root = _get_val("target_root", "")
    filename_template = _get_val("filename_template", "{original_basename}")
    move_only_org = bool(_get_val("move_only_organized", True))
    dry_run = bool(_get_val("dry_run", False))
    write_nfo = bool(_get_val("write_nfo", True))
    download_poster = bool(_get_val("download_poster", True))
    overlay_studio_logo_on_poster = bool(_get_val("overlay_studio_logo_on_poster", False))

    # AI / 翻译 相关配置
    translate_enable = bool(_get_val("translate_enable", False))
    translate_api_base = _get_val("translate_api_base", "") or ""
    translate_api_key = _get_val("translate_api_key", "") or ""
    translate_model = _get_val("translate_model", "") or ""
    # 有些配置界面可能把布尔值和字符串混用，兼容处理
    translate_plot = bool(_get_val("translate_plot", False))
    translate_title = bool(_get_val("translate_title", False))
    # temperature 可能是字符串或数字，尝试转为 float，如果失败则保留原样
    translate_temperature = _get_val("translate_temperature", "")
    translate_prompt = _get_val("translate_prompt", "")

    # 从全局配置中获取 Stash API Key（对应 stash_configuration.json.general.apiKey）
    stash_api_key = ""
    try:
        stash_api_key = cfg.get("general", {}).get("apiKey") or ""
    except Exception:
        stash_api_key = ""

    # 新增：启用 Hook 模式设置
    enable_hook_mode = bool(_get_val("enable_hook_mode", True))
    # 新增：源目录到目标目录的映射设置
    source_target_mapping = _get_val("source_target_mapping", "")
    # 多文件模式设置
    multi_file_mode = _get_val("multi_file_mode", "all")

    return {
        "target_root": target_root,
        "filename_template": filename_template,
        "move_only_organized": move_only_org,
        "dry_run": dry_run,
        "write_nfo": write_nfo,
        "download_poster": download_poster,
        "overlay_studio_logo_on_poster": overlay_studio_logo_on_poster,
        # AI / 翻译
        "translate_enable": translate_enable,
        "translate_api_base": translate_api_base,
        "translate_api_key": translate_api_key,
        "translate_model": translate_model,
        "translate_plot": translate_plot,
        "translate_title": translate_title,
        "translate_temperature": translate_temperature,
        "translate_prompt": translate_prompt,
        # Stash 全局 API Key，用于下载图片时避免 Session 失效问题
        "stash_api_key": stash_api_key,
        # 新增：源目录到目标目录的映射
        "source_target_mapping": source_target_mapping,
        # 新增：启用 Hook 模式
        "enable_hook_mode": enable_hook_mode,
        # 多文件模式
        "multi_file_mode": multi_file_mode,
        # 插件 ID
        "PLUGIN_ID": PLUGIN_ID,
    }


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


def main():
    """插件主入口"""
    json_input = read_input()  # 插件运行时从 stdin 读
    # 不输出完整输入（可能包含敏感信息），只记录启动日志
    log.info(f"[{PLUGIN_ID}] Plugin started")
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
    # 把 stash 对象也放入 settings，方便 file_mover.py 使用 GraphQL API
    settings["stash_interface"] = stash

    # 导入 Hook 和 Task 处理器
    from hook_handler import handle_hook
    from task_handler import handle_task

    try:
        # 判断是 Hook 模式还是 Task 模式
        hook_ctx = (args or {}).get("hookContext") or {}
        scene_id = hook_ctx.get("id") or hook_ctx.get("scene_id")

        if scene_id is not None:
            # Hook 模式：处理单个场景
            msg = handle_hook(stash, int(scene_id), settings)
        else:
            # Task 模式：批量处理所有场景
            msg = handle_task(stash, settings)

        out = {"output": msg, "progress": 1.0}
    except Exception as e:
        log.error(f"Plugin execution failed: {e}")
        out = {"error": str(e)}

    # 输出必须是单行 JSON
    print(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
