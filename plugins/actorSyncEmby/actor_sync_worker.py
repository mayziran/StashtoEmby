"""
演员同步后台工作脚本 - 异步执行演员同步到 Emby

工作流程:
1. 等待 40 秒（让 Stash 完成后续操作）
2. 调用 Emby API 刷新媒体库
3. 等待 60 秒（让 Emby 完成扫描）
4. 执行演员上传（图片 + 元数据）
5. 失败时按指数退避重试（30s → 60s → 90s）
"""

import json
import os
import sys
import time
from typing import Any, Dict, Optional

import requests

LOG_FILE = os.path.join(os.path.dirname(__file__), "actor_sync_worker.log")
_enable_worker_log = True  # 在 main() 中从配置设置


def log_info(message: str) -> None:
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
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [ERROR] {message}"
    print(log_line, flush=True)
    if _enable_worker_log:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass


def refresh_emby_library(emby_server: str, emby_api_key: str) -> bool:
    """调用 Emby API 刷新演员库"""
    log_info(f"开始刷新 Emby 演员库：{emby_server}")

    try:
        # 触发媒体库扫描
        scan_url = f"{emby_server}/emby/Library/Media/Updated?api_key={emby_api_key}"
        resp = requests.post(scan_url, timeout=10)
        if resp.status_code in [200, 204]:
            log_info("已触发 Emby 媒体库扫描")
            return True
        else:
            log_info(f"触发扫描返回状态码：{resp.status_code}")
            return False
    except Exception as e:
        log_error(f"刷新 Emby 库失败：{e}")
        return False


def check_actor_exists_in_emby(emby_server: str, emby_api_key: str, actor_name: str) -> bool:
    """检查演员是否存在于 Emby 中"""
    from urllib.parse import quote
    
    encoded_name = quote(actor_name)
    persons_url = f"{emby_server}/emby/Persons/{encoded_name}?api_key={emby_api_key}"
    
    try:
        resp = requests.get(persons_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('Id'):
                log_info(f"演员 {actor_name} 在 Emby 中存在，ID: {data['Id']}")
                return True
        elif resp.status_code == 404:
            log_info(f"演员 {actor_name} 在 Emby 中不存在")
            return False
        else:
            log_info(f"检查演员 {actor_name} 状态失败，状态码：{resp.status_code}")
            return False
    except Exception as e:
        log_error(f"检查演员 {actor_name} 时发生错误：{e}")
        return False


def get_performer_from_stash(stash_url: str, stash_api_key: str, performer_id: str) -> Optional[Dict[str, Any]]:
    """从 Stash API 获取演员信息"""
    query = """
    query FindPerformer($id: ID!) {
        findPerformer(id: $id) {
            id
            name
            image_path
            gender
            country
            ethnicity
            birthdate
            death_date
            career_length
            height_cm
            weight
            measurements
            fake_tits
            penis_length
            circumcised
            eye_color
            hair_color
            tattoos
            piercings
            disambiguation
            alias_list
            urls
        }
    }
    """
    
    headers = {"Content-Type": "application/json"}
    if stash_api_key:
        headers["ApiKey"] = stash_api_key
    
    try:
        resp = requests.post(
            f"{stash_url}/graphql",
            json={"query": query, "variables": {"id": performer_id}},
            headers=headers,
            timeout=30
        )
        
        if resp.status_code != 200:
            log_error(f"从 Stash 获取演员信息失败，状态码：{resp.status_code}")
            return None
        
        result = resp.json()
        performer = result.get("data", {}).get("findPerformer")
        
        if not performer:
            log_error(f"未找到演员 ID: {performer_id}")
            return None
        
        return performer
    except Exception as e:
        log_error(f"从 Stash 获取演员信息失败：{e}")
        return None


def main():
    import base64
    
    if len(sys.argv) < 3:
        log_error("用法：python actor_sync_worker.py <performer_id> <config_base64>")
        sys.exit(1)
    
    performer_id = sys.argv[1]
    config_b64 = sys.argv[2]
    
    log_info(f"=== 演员同步工作脚本启动 ===")
    log_info(f"演员 ID: {performer_id}")
    
    # 解码 base64 配置
    try:
        config_json = base64.b64decode(config_b64).decode('utf-8')
        config = json.loads(config_json)
    except Exception as e:
        log_error(f"解析配置失败：{e}")
        sys.exit(1)
    
    emby_server = config.get("emby_server", "").strip()
    emby_api_key = config.get("emby_api_key", "").strip()
    stash_api_key = config.get("stash_api_key", "")
    server_conn = config.get("server_connection", {})
    actor_output_dir = config.get("actor_output_dir", "").strip()
    download_images = config.get("download_actor_images", True)
    stash_url = config.get("stash_url", "http://localhost:9999")
    
    # 是否启用日志文件（默认启用）
    global _enable_worker_log
    _enable_worker_log = config.get("enable_worker_log", True)
    
    # 新建演员强制使用模式 1（覆盖）
    sync_mode = 1
    
    if not emby_server or not emby_api_key:
        log_error("Emby 服务器地址或 API 密钥未配置")
        sys.exit(1)
    
    # 从 Stash 获取演员信息
    performer = get_performer_from_stash(stash_url, stash_api_key, performer_id)
    if not performer:
        sys.exit(1)
    
    actor_name = performer.get("name", "")
    log_info(f"获取到演员信息：{actor_name}")
    
    # 阶段 1: 等待
    log_info("【阶段 1/4】等待 Stash 完成后续操作...")
    time.sleep(40)
    
    # 阶段 2: 刷新 Emby
    log_info("【阶段 2/4】刷新 Emby 演员库...")
    refresh_emby_library(emby_server, emby_api_key)
    
    # 阶段 3: 等待 Emby 刷新完成
    log_info("【阶段 3/4】等待 Emby 刷新完成...")
    time.sleep(60)
    
    # 阶段 4: 上传演员信息（带重试）
    log_info("【阶段 4/4】上传演员信息到 Emby...")
    
    retry_delays = [30, 60, 90]
    max_attempts = len(retry_delays) + 1
    
    for attempt in range(max_attempts):
        log_info(f"尝试上传 (第 {attempt + 1}/{max_attempts} 次)...")
        
        # 检查演员是否存在于 Emby
        if not check_actor_exists_in_emby(emby_server, emby_api_key, actor_name):
            log_info(f"演员 {actor_name} 在 Emby 中不存在")
            if attempt < max_attempts - 1:
                wait_time = retry_delays[attempt]
                log_info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            else:
                log_error(f"已达到最大重试次数，演员 {actor_name} 仍未在 Emby 中出现")
                sys.exit(1)
        
        # 执行上传（使用 emby_uploader 模块）
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from emby_uploader import upload_actor_to_emby
            
            upload_actor_to_emby(
                performer=performer,
                emby_server=emby_server,
                emby_api_key=emby_api_key,
                server_conn=server_conn,
                stash_api_key=stash_api_key,
                actor_output_dir=actor_output_dir,
                sync_mode=sync_mode,
                download_images=download_images
            )
            log_info(f"✓ 演员 {actor_name} 同步完成!")
            sys.exit(0)
        except Exception as e:
            log_error(f"上传失败：{e}")
            if attempt < max_attempts - 1:
                wait_time = retry_delays[attempt]
                log_info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                log_error(f"已达到最大重试次数，上传失败")
                sys.exit(1)


if __name__ == "__main__":
    main()
