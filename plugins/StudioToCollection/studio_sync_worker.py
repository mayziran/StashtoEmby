"""
studio_sync_worker.py - Create Hook 异步执行

职责:
    1. 接收 hook 传递的配置（studio 原始数据、emby_data、collection_id 等）
    2. 延迟等待 + 触发 Emby 计划任务
    3. 搜索合集确认存在（三次重试机制）
    4. 调用 emby_uploader.upload_studio_to_emby 上传

注意:
    - 本模块自包含，不依赖 utils.py
    - 使用 worker 自己的日志系统（写入文件）
"""

import base64
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import requests

# 导入 emby_uploader 用于上传
sys.path.insert(0, os.path.dirname(__file__))
from emby_uploader import upload_studio_to_emby

LOG_FILE = os.path.join(os.path.dirname(__file__), "studio_sync_worker.log")
_enable_worker_log = False  # 默认关闭


def log_info(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [INFO] {message}"
    if _enable_worker_log:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass


def log_error(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [ERROR] {message}"
    if _enable_worker_log:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass


def load_config() -> Dict[str, Any]:
    """从命令行参数加载配置（Base64 编码）"""
    if len(sys.argv) < 2:
        raise ValueError("缺少配置参数")

    config_b64 = sys.argv[1]
    config_json = base64.b64decode(config_b64).decode('utf-8')
    return json.loads(config_json)


def find_collection_by_name(
    emby_server: str,
    emby_api_key: str,
    user_id: str,
    studio_name: str
) -> Optional[Dict[str, Any]]:
    """
    按名称搜索合集（精确匹配）- worker 内部实现

    使用 worker 自己的日志系统，不依赖 utils.py
    """
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "Recursive": "true",      # 关键：递归获取所有媒体库
            "SearchTerm": studio_name,
            "Limit": 20
        }
        response = requests.get(url, params=params, timeout=30)
        items = response.json().get("Items", [])

        log_info(f"搜索合集 '{studio_name}'，返回 {len(items)} 个结果")
        
        # 本地精确匹配（因为 SearchTerm 是模糊搜索）
        for item in items:
            item_name = item.get("Name", "")
            log_info(f"检查合集：{item_name}")
            if item_name.lower() == studio_name.lower():
                log_info(f"✓ 找到匹配：{item_name}")
                return item
        
        log_info("✗ 未找到匹配")
        return None
    except Exception as e:
        log_error(f"搜索合集失败：{e}")
        return None


def trigger_emby_library_refresh(emby_server: str, emby_api_key: str) -> bool:
    """触发 Emby 媒体库刷新"""
    try:
        url = f"{emby_server}/emby/Library/Media/Updated?api_key={emby_api_key}"
        response = requests.post(url, timeout=10)
        if response.status_code in [200, 204]:
            log_info("✓ 已触发 Emby 媒体库刷新")
            return True
        log_error(f"触发 Emby 媒体库刷新失败：{response.status_code}")
        return False
    except Exception as e:
        log_error(f"触发 Emby 媒体库刷新失败：{e}")
        return False


def trigger_emby_scheduled_task(emby_server: str, emby_api_key: str, task_id: str) -> bool:
    """触发 Emby 计划任务"""
    try:
        trigger_url = f"{emby_server}/emby/ScheduledTasks/Running/{task_id}"
        params = {"api_key": emby_api_key}
        response = requests.post(trigger_url, params=params, timeout=30)

        if response.status_code == 204:
            log_info(f"✓ 已触发计划任务 (ID: {task_id})")
            return True
        log_error(f"触发计划任务失败：{response.status_code}")
        return False
    except Exception as e:
        log_error(f"触发计划任务失败：{e}")
        return False


def sync_studio_to_collection(config: Dict[str, Any]) -> str:
    """
    同步工作室到 Emby

    运行逻辑:
        1. 等待 delay_seconds → 触发计划任务 → 等待 30 秒 → 第 1 次搜索
        2. 未找到 → 等待 60 秒 → 触发计划任务 → 第 2 次搜索
        3. 未找到 → 等待 90 秒 → 触发计划任务 → 第 3 次搜索 → 放弃
    
    注意：本函数只负责延迟等待和搜索合集，上传由 emby_uploader.upload_studio_to_emby 完成
    """
    studio_name = config["studio_name"]
    collection_id = config.get("collection_id")
    task_id = config.get("scheduled_task_id")
    user_id = config.get("user_id")

    # 解析延迟配置
    stash_wait = config.get("stash_wait", 35)
    emby_wait = config.get("emby_wait", 70)

    if not collection_id:
        return f"缺少 collection_id"

    # ========== 阶段 1：初始等待 ==========
    log_info(f"[{studio_name}] 等待 {stash_wait} 秒，等待 Stash 创建影片...")
    time.sleep(stash_wait)

    # ========== 触发 Emby 媒体库刷新 ==========
    log_info(f"[{studio_name}] 触发 Emby 媒体库刷新...")
    trigger_emby_library_refresh(config["emby_server"], config["emby_api_key"])

    # ========== 等待 Emby 扫描 ==========
    log_info(f"[{studio_name}] 等待 {emby_wait} 秒，等待 Emby 扫描完成...")
    time.sleep(emby_wait)

    # ========== 重试配置：3 次搜索，每次等待时间不同 ==========
    retry_delays = [30, 60, 90]  # 第 1/2/3 次搜索前的等待时间
    
    for attempt, delay in enumerate(retry_delays, 1):
        # 触发计划任务
        if task_id:
            log_info(f"[{studio_name}] 触发 Emby 计划任务（第 {attempt} 次）...")
            trigger_emby_scheduled_task(config["emby_server"], config["emby_api_key"], task_id)

        # 等待任务执行
        log_info(f"[{studio_name}] 等待 30 秒，等待计划任务执行...")
        time.sleep(30)

        # 搜索合集
        log_info(f"[{studio_name}] 第 {attempt} 次搜索合集...")
        collection = find_collection_by_name(
            config["emby_server"],
            config["emby_api_key"],
            user_id,
            studio_name
        )

        if collection:
            log_info(f"[{studio_name}] ✓ 找到合集，开始上传...")
            if upload_studio_to_emby(
                emby_data=config["emby_data"],
                collection_id=collection["Id"],
                emby_server=config["emby_server"],
                emby_api_key=config["emby_api_key"],
                user_id=user_id,
                server_conn=config.get("server_conn", {}),
                stash_api_key=config.get("stash_api_key", ""),
                dry_run=config.get("dry_run", False)
            ):
                return f"工作室 {studio_name} 同步完成"
            else:
                return f"工作室 {studio_name} 上传失败"
        
        # 未找到，等待下一次重试（最后一次不等待）
        if attempt < len(retry_delays):
            log_info(f"[{studio_name}] 未找到合集，等待 {delay} 秒...")
            time.sleep(delay)

    # ========== 放弃 ==========
    log_info(f"[{studio_name}] ✗ 三次尝试后仍未找到合集，放弃")
    return f"工作室 {studio_name}：三次尝试后仍未找到合集，放弃同步"


def main():
    """Worker 入口"""
    global _enable_worker_log

    try:
        config = load_config()

        # 从配置读取日志开关（默认关闭）
        _enable_worker_log = config.get("enable_worker_log", False)

        log_info(f"=== Worker 启动 ===")
        log_info(f"工作室：{config['studio_name']}")
        log_info(f"合集 ID: {config.get('collection_id')}")
        log_info(f"启用日志：{_enable_worker_log}")

        result = sync_studio_to_collection(config)
        log_info(result)
    except Exception as e:
        log_error(f"Worker 执行失败：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
