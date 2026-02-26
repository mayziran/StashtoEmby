"""
Hook 处理器 - 处理演员创建/更新事件

架构原则:
    - 本地导出 → 同步执行
    - Emby 上传 → Create 异步延迟，Update 同步

Hook 模式 (hook_mode):
    0=关闭，1=只本地，2=只 Emby，3=本地+Emby
"""

from typing import Any, Dict, Optional

from utils import PERFORMER_FRAGMENT_FOR_API


def _export_local(performer: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    执行本地导出（同步直接执行，无延迟）

    Returns:
        是否成功
    """
    import stashapi.log as log

    local_exporter = settings.get("local_exporter")
    if not local_exporter:
        return False

    export_func = local_exporter.get("export_actor_to_local")
    if not export_func:
        return False

    try:
        export_func(
            performer=performer,
            actor_output_dir=settings.get("actor_output_dir", ""),
            export_mode=1,  # 覆盖模式：都导出（NFO+ 图片）
            server_conn=settings.get("server_connection", {}),
            stash_api_key=settings.get("stash_api_key", ""),
            dry_run=settings.get("dry_run", False)
        )
        return True
    except Exception as e:
        log.error(f"本地导出失败：{e}")
        return False


def _start_emby_async(performer_id: int, settings: Dict[str, Any]) -> bool:
    """
    启动 Emby 异步上传（通过 worker 延迟执行）

    Returns:
        是否成功启动
    """
    import stashapi.log as log
    from actorSyncEmby import start_async_worker

    emby_uploader = settings.get("emby_uploader")
    if not emby_uploader:
        return False

    try:
        upload_settings = dict(settings)
        upload_settings["upload_mode"] = 1  # 覆盖模式：都上传（图片 + 元数据）
        start_async_worker(performer_id, upload_settings)
        return True
    except Exception as e:
        log.error(f"启动 Emby 异步上传失败：{e}")
        return False


def _upload_emby_sync(performer: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    """
    同步上传 Emby（用于 Update Hook，无延迟）

    Returns:
        是否成功
    """
    import stashapi.log as log

    emby_uploader = settings.get("emby_uploader")
    if not emby_uploader:
        return False

    upload_func = emby_uploader.get("upload_actor_to_emby")
    if not upload_func:
        return False

    try:
        upload_func(
            performer=performer,
            emby_server=settings.get("emby_server", ""),
            emby_api_key=settings.get("emby_api_key", ""),
            server_conn=settings.get("server_connection", {}),
            stash_api_key=settings.get("stash_api_key", ""),
            upload_mode=1  # 覆盖模式：都上传（图片 + 元数据）
        )
        return True
    except Exception as e:
        log.error(f"Emby 同步上传失败：{e}")
        return False


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
    from actorSyncEmby import PLUGIN_ID

    # 获取演员完整数据（使用自定义 fragment，只获取需要的 24 个字段）
    performer = stash.find_performer(performer_id, fragment=PERFORMER_FRAGMENT_FOR_API)
    if not performer:
        msg = f"找不到演员 ID: {performer_id}"
        log.error(msg)
        return msg

    performer_name = performer.get("name", "Unknown")
    hook_mode = settings.get("hook_mode", 3)

    # hook_mode=0：关闭
    if hook_mode == 0:
        return "Hook 响应已关闭"

    # 执行操作
    is_create = (hook_type == "创建")
    local_ok = False
    emby_ok = False

    # hook_mode=1：只本地
    if hook_mode == 1:
        local_ok = _export_local(performer, settings)
        msg = f"演员 {performer_name} {hook_type}成功，已导出本地"

    # hook_mode=2：只 Emby
    elif hook_mode == 2:
        if is_create:
            emby_ok = _start_emby_async(performer_id, settings)
            msg = f"演员 {performer_name} {hook_type}成功，已启动异步上传 Emby"
        else:
            emby_ok = _upload_emby_sync(performer, settings)
            msg = f"演员 {performer_name} {hook_type}成功，已上传 Emby"

    # hook_mode=3：本地 + Emby
    elif hook_mode == 3:
        local_ok = _export_local(performer, settings)
        if is_create:
            emby_ok = _start_emby_async(performer_id, settings)
            msg = f"演员 {performer_name} {hook_type}成功，已导出本地并启动异步上传 Emby"
        else:
            emby_ok = _upload_emby_sync(performer, settings)
            msg = f"演员 {performer_name} {hook_type}成功，已同步到本地和 Emby"

    else:
        msg = f"未知的 hook_mode={hook_mode}"
        log.error(msg)
        return msg

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

    log.info(f"[{PLUGIN_ID}] 检测到演员创建 Hook")
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

    log.info(f"[{PLUGIN_ID}] Hook 模式，处理演员更新 (id={performer_id})")

    msg = _process_hook_performer(stash, performer_id, settings, "更新")

    if task_log_func:
        task_log_func(msg, progress=1.0)

    return msg
