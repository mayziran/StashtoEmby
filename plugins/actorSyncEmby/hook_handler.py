"""
Hook 处理器 - 处理 Performer.Create.Post 和 Performer.Update.Post 事件

所有 Hook 操作都使用覆盖模式（export_mode=1, upload_mode=1）

注意：本模块不从文件导入功能函数，而是从 settings 获取已加载的模块引用。
"""

from typing import Any, Dict


def _process_hook_performer(
    stash: Any,
    performer_id: int,
    settings: Dict[str, Any],
    hook_type: str
) -> str:
    """
    统一处理 Hook 的演员（创建/更新共用）

    Args:
        stash: Stash 接口
        performer_id: 演员 ID
        settings: 配置参数
        hook_type: Hook 类型（"创建" / "更新"）

    Returns:
        处理结果消息
    """
    import stashapi.log as log
    from actorSyncEmby import PLUGIN_ID, start_async_worker

    # 获取演员完整数据
    performer = stash.find_performer(performer_id)
    if not performer:
        msg = f"找不到演员 ID: {performer_id}"
        log.error(msg)
        return msg

    performer_name = performer.get("name", "Unknown")
    local_exporter = settings.get("local_exporter")
    emby_uploader = settings.get("emby_uploader")
    hook_mode = settings.get("hook_mode", 3)

    # hook_mode=0：关闭（应当在调用前判断）
    if hook_mode == 0:
        return "Hook 响应已关闭"

    # hook_mode=1：只输出本地（覆盖模式）
    if hook_mode == 1:
        if local_exporter:
            export_func = local_exporter.get("export_actor_to_local")
            if export_func:
                export_func(
                    performer=performer,
                    actor_output_dir=settings.get("actor_output_dir", ""),
                    export_mode=1,  # 都导出（NFO+ 图片）
                    server_conn=settings.get("server_connection", {}),
                    stash_api_key=settings.get("stash_api_key", ""),
                    dry_run=settings.get("dry_run", False)
                )
        msg = f"演员 {performer_name} {hook_type}成功，已导出本地（覆盖模式）"

    # hook_mode=2：只上传 Emby（覆盖模式）
    elif hook_mode == 2:
        # Create Hook 使用异步 worker，Update Hook 使用同步执行
        if hook_type == "创建":
            upload_settings = dict(settings)
            upload_settings["upload_mode"] = 1
            start_async_worker(performer_id, upload_settings)
            msg = f"演员 {performer_name} {hook_type}成功，已启动异步上传 Emby（覆盖模式）"
        else:
            if emby_uploader:
                upload_func = emby_uploader.get("upload_actor_to_emby")
                if upload_func:
                    upload_func(
                        performer=performer,
                        emby_server=settings.get("emby_server", ""),
                        emby_api_key=settings.get("emby_api_key", ""),
                        server_conn=settings.get("server_connection", {}),
                        stash_api_key=settings.get("stash_api_key", ""),
                        upload_mode=1  # 都上传（图片 + 元数据）
                    )
            msg = f"演员 {performer_name} {hook_type}成功，已上传 Emby（覆盖模式）"

    # hook_mode=3：同时输出本地 + Emby（都是覆盖模式）
    elif hook_mode == 3:
        if local_exporter:
            export_func = local_exporter.get("export_actor_to_local")
            if export_func:
                export_func(
                    performer=performer,
                    actor_output_dir=settings.get("actor_output_dir", ""),
                    export_mode=1,  # 都导出（NFO+ 图片）
                    server_conn=settings.get("server_connection", {}),
                    stash_api_key=settings.get("stash_api_key", ""),
                    dry_run=settings.get("dry_run", False)
                )
        if emby_uploader:
            # Create Hook 使用异步 worker，Update Hook 使用同步执行
            if hook_type == "创建":
                upload_settings = dict(settings)
                upload_settings["upload_mode"] = 1
                start_async_worker(performer_id, upload_settings)
                msg = f"演员 {performer_name} {hook_type}成功，已导出本地并启动异步上传 Emby（覆盖模式）"
            else:
                upload_func = emby_uploader.get("upload_actor_to_emby")
                if upload_func:
                    upload_func(
                        performer=performer,
                        emby_server=settings.get("emby_server", ""),
                        emby_api_key=settings.get("emby_api_key", ""),
                        server_conn=settings.get("server_connection", {}),
                        stash_api_key=settings.get("stash_api_key", ""),
                        upload_mode=1  # 都上传（图片 + 元数据）
                    )
                msg = f"演员 {performer_name} {hook_type}成功，已同步到本地和 Emby（覆盖模式）"
        else:
            msg = f"演员 {performer_name} {hook_type}成功，已导出本地（覆盖模式）"

    else:
        msg = f"未知的 hook_mode={hook_mode}"
        log.error(msg)

    return msg


def handle_create_hook(
    stash: Any,
    performer_id: int,
    settings: Dict[str, Any]
) -> str:
    """
    处理演员创建 Hook（Performer.Create.Post）
    """
    import stashapi.log as log
    from actorSyncEmby import PLUGIN_ID

    log.info(f"[{PLUGIN_ID}] 检测到演员创建 Hook（固定使用覆盖模式）")
    return _process_hook_performer(stash, performer_id, settings, "创建")


def handle_update_hook(
    stash: Any,
    performer_id: int,
    settings: Dict[str, Any],
    task_log_func: Any = None
) -> str:
    """
    处理演员更新 Hook（Performer.Update.Post）
    """
    import stashapi.log as log
    from actorSyncEmby import PLUGIN_ID

    log.info(f"[{PLUGIN_ID}] Hook 模式，处理演员更新 (id={performer_id})（固定使用覆盖模式）")

    msg = _process_hook_performer(stash, performer_id, settings, "更新")

    if task_log_func:
        task_log_func(msg, progress=1.0)

    return msg
