"""
studio_sync_worker.py - Create Hook 异步执行

职责:
    1. 接收 hook 传递的配置（emby_data、collection_id 等）
    2. 延迟等待 + 触发 Emby 计划任务
    3. 搜索合集确认存在
    4. 调用 upload 上传
"""

import base64
import json
import os
import sys
import time
from typing import Any, Dict

import requests
from emby_uploader import upload_metadata

LOG_FILE = os.path.join(os.path.dirname(__file__), "studio_sync_worker.log")
_enable_worker_log = True  # 在 main() 中从配置设置


def log_info(message: str) -> None:
    """输出日志（同时打印到控制台和写入文件）"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [INFO] {message}"
    print(log_line, flush=True)
    if _enable_worker_log:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass


def log_error(message: str) -> None:
    """输出错误日志"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [ERROR] {message}"
    print(log_line, flush=True)
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
    """按名称搜索合集（精确匹配）"""
    try:
        url = f"{emby_server}/emby/Users/{user_id}/Items"
        params = {
            "api_key": emby_api_key,
            "IncludeItemTypes": "BoxSet",
            "SearchTerm": studio_name,
            "Limit": 10
        }
        response = requests.get(url, params=params, timeout=30)
        items = response.json().get("Items", [])
        
        for item in items:
            if item["Name"].lower() == studio_name.lower():
                return item
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


def upload_to_emby(config: Dict[str, Any], collection_id: str) -> bool:
    """上传数据到 Emby"""
    emby_data = config["emby_data"].copy()
    emby_data["Id"] = collection_id
    
    return upload_metadata(
        collection_id=collection_id,
        emby_data=emby_data,
        emby_server=config["emby_server"],
        emby_api_key=config["emby_api_key"],
        dry_run=config.get("dry_run", False)
    )


def sync_studio_to_collection(config: Dict[str, Any]) -> str:
    """
    同步工作室
    
    运行逻辑:
        1. 等待 delay_seconds → 触发计划任务 → 等待 30 秒 → 第 1 次搜索
        2. 未找到 → 等待 60 秒 → 触发计划任务 → 第 2 次搜索
        3. 未找到 → 等待 90 秒 → 触发计划任务 → 第 3 次搜索 → 放弃
    """
    studio_name = config["studio_name"]
    collection_id = config.get("collection_id")
    task_id = config.get("scheduled_task_id")
    user_id = config.get("user_id")  # hook 已获取，不需要再获取
    
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
    
    # ========== 触发计划任务（第 1 次） ==========
    if task_id:
        log_info(f"[{studio_name}] 触发 Emby 计划任务（第 1 次）...")
        trigger_emby_scheduled_task(config["emby_server"], config["emby_api_key"], task_id)
    
    # ========== 等待任务执行 ==========
    log_info(f"[{studio_name}] 等待 30 秒，等待计划任务执行...")
    time.sleep(30)
    
    # ========== 第 1 次搜索 ==========
    log_info(f"[{studio_name}] 第 1 次搜索合集...")
    
    collection = find_collection_by_name(
        config["emby_server"],
        config["emby_api_key"],
        user_id,
        studio_name
    )
    
    if collection:
        log_info(f"[{studio_name}] ✓ 找到合集，开始上传...")
        if upload_to_emby(config, collection["Id"]):
            return f"工作室 {studio_name} 同步完成"
        else:
            return f"工作室 {studio_name} 上传失败"
    
    # ========== 第 2 次搜索 ==========
    log_info(f"[{studio_name}] 未找到合集，等待 60 秒...")
    time.sleep(60)
    
    if task_id:
        log_info(f"[{studio_name}] 触发 Emby 计划任务（第 2 次）...")
        trigger_emby_scheduled_task(config["emby_server"], config["emby_api_key"], task_id)
    
    log_info(f"[{studio_name}] 第 2 次搜索合集...")
    collection = find_collection_by_name(
        config["emby_server"],
        config["emby_api_key"],
        user_id,
        studio_name
    )
    
    if collection:
        log_info(f"[{studio_name}] ✓ 找到合集，开始上传...")
        if upload_to_emby(config, collection["Id"]):
            return f"工作室 {studio_name} 同步完成"
        else:
            return f"工作室 {studio_name} 上传失败"
    
    # ========== 第 3 次搜索 ==========
    log_info(f"[{studio_name}] 未找到合集，等待 90 秒...")
    time.sleep(90)
    
    if task_id:
        log_info(f"[{studio_name}] 触发 Emby 计划任务（第 3 次）...")
        trigger_emby_scheduled_task(config["emby_server"], config["emby_api_key"], task_id)
    
    log_info(f"[{studio_name}] 第 3 次搜索合集...")
    collection = find_collection_by_name(
        config["emby_server"],
        config["emby_api_key"],
        user_id,
        studio_name
    )
    
    if collection:
        log_info(f"[{studio_name}] ✓ 找到合集，开始上传...")
        if upload_to_emby(config, collection["Id"]):
            return f"工作室 {studio_name} 同步完成"
        else:
            return f"工作室 {studio_name} 上传失败"
    
    # ========== 放弃 ==========
    log_info(f"[{studio_name}] ✗ 三次尝试后仍未找到合集，放弃")
    return f"工作室 {studio_name}：三次尝试后仍未找到合集，放弃同步"


def main():
    """Worker 入口"""
    global _enable_worker_log
    
    try:
        config = load_config()
        
        # 从配置读取日志开关（在使用任何日志之前设置）
        _enable_worker_log = config.get("enable_worker_log", True)
        
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
