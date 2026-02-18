"""
Task 处理器 - 处理手动执行的任务（同步所有演员）

支持 export_mode 和 upload_mode 的所有模式（0-4）

注意：本模块不从文件导入功能函数，而是从 settings 获取已加载的模块引用。
"""

from typing import Any, Dict, List

import stashapi.log as log


def handle_task(
    stash: Any,
    settings: Dict[str, Any],
    task_log_func: Any
) -> str:
    """
    处理 Task 任务（同步所有演员）
    
    Args:
        stash: Stash 连接
        settings: 配置参数（包含已加载的模块引用）
        task_log_func: Task 日志函数
    
    Returns:
        处理结果消息
    """
    from actorSyncEmby import PLUGIN_ID
    
    export_mode = settings.get("export_mode", 1)
    upload_mode = settings.get("upload_mode", 1)
    
    log.info(f"[{PLUGIN_ID}] Task 模式：export_mode={export_mode}, upload_mode={upload_mode}")
    task_log_func(f"[Task] 处理所有演员 (dry_run={settings.get('dry_run', False)})", progress=0.0)
    
    # 只有纯补缺模式（44、40、04）才使用批量检查
    use_batch_check = (export_mode == 4 and upload_mode == 4) or \
                      (export_mode == 4 and upload_mode == 0) or \
                      (export_mode == 0 and upload_mode == 4)
    
    per_page = 1000  # 每批处理 1000 个演员
    page = 1
    total_processed = 0
    total_success = 0
    total_skip = 0
    
    # 批量检查缓存
    local_missing_cache = {}
    emby_missing_cache = {}
    
    # 从 settings 获取已加载的模块
    local_exporter = settings.get("local_exporter")
    emby_uploader = settings.get("emby_uploader")
    
    while True:
        # 第 1 步：先获取当前页演员的名称（只 id+name，用于检查缺失）
        log.info(f"[{PLUGIN_ID}] Fetching performers page={page}, per_page={per_page}")
        
        try:
            page_performers_basic = stash.find_performers(
                f=None,
                filter={"page": page, "per_page": per_page},
                fragment="id\nname",
            )
        except Exception as e:
            log.error(f"获取演员列表失败：{e}")
            break
        
        if not page_performers_basic:
            log.info(f"[{PLUGIN_ID}] No more performers at page={page}, stop paging")
            break
        
        log.info(f"[{PLUGIN_ID}] Got {len(page_performers_basic)} performers in page={page}")
        
        # 第 2 步：批量检查缺失（只使用名称，不需要完整数据）
        if use_batch_check:
            performer_names = [p.get("name") for p in page_performers_basic if p.get("name")]
            
            # 批量检查本地缺失（只检查一次，缓存复用）
            if export_mode == 4 and local_exporter:
                check_local = local_exporter.get("check_local_missing_batch")
                if check_local and not local_missing_cache:
                    log.info(f"[{PLUGIN_ID}] 批量检查本地缺失...")
                    local_missing_cache = check_local(performer_names, settings.get("actor_output_dir", ""))
                    log.info(f"[{PLUGIN_ID}] 本地缺失检查结果：{sum(1 for v in local_missing_cache.values() if v['need_nfo'] or v['need_image'])} 个演员需要处理")
            
            # 批量检查 Emby 缺失（只检查一次，缓存复用）
            if upload_mode == 4 and emby_uploader:
                check_emby = emby_uploader.get("check_emby_missing_batch")
                if check_emby and not emby_missing_cache:
                    log.info(f"[{PLUGIN_ID}] 批量检查 Emby 缺失...")
                    emby_missing_cache = check_emby(
                        performer_names,
                        settings.get("emby_server", ""),
                        settings.get("emby_api_key", "")
                    )
                    log.info(f"[{PLUGIN_ID}] Emby 缺失检查结果：{sum(1 for v in emby_missing_cache.values() if v['need_image'] or v['need_metadata'])} 个演员需要处理")
            
            # 第 3 步：筛选出当前页需要处理的演员 ID（只存当前页，不累积）
            current_page_missing_ids = []
            for performer in page_performers_basic:
                performer_id = performer.get("id")
                performer_name = performer.get("name")
                
                if not performer_id or not performer_name:
                    continue
                
                need_local = False
                need_emby = False
                
                if export_mode == 4 and performer_name in local_missing_cache:
                    status = local_missing_cache[performer_name]
                    need_local = status["need_nfo"] or status["need_image"]
                
                if upload_mode == 4 and performer_name in emby_missing_cache:
                    status = emby_missing_cache[performer_name]
                    need_emby = status["need_image"] or status["need_metadata"]
                
                if need_local or need_emby:
                    current_page_missing_ids.append(performer_id)
            
            need_process_count = len(current_page_missing_ids)
            log.info(f"[{PLUGIN_ID}] 第{page}批需要处理的演员：{need_process_count}/{len(page_performers_basic)}")
            
            # 第 4 步：获取当前页缺失演员的完整数据并处理（分页获取，避免一次太多）
            if need_process_count > 0:
                full_fragment = """
                    id
                    name
                    image_path
                    gender
                    country
                    birthdate
                    height_cm
                    measurements
                    fake_tits
                    disambiguation
                    details
                    ethnicity
                    eye_color
                    hair_color
                    career_length
                    tattoos
                    piercings
                    weight
                    death_date
                    circumcised
                    penis_length
                    alias_list
                    urls
                """
                
                # 分批获取完整数据（每批 100 个）
                missing_per_page = 100
                for i in range(0, len(current_page_missing_ids), missing_per_page):
                    batch_ids = current_page_missing_ids[i:i+missing_per_page]
                    
                    try:
                        f_filter = {
                            "value": {
                                "value": [str(pid) for pid in batch_ids],
                                "modifier": "INCLUDES_ALL"
                            },
                            "type": "ID"
                        }
                        
                        page_performers = stash.find_performers(
                            f=f_filter,
                            filter={"page": 1, "per_page": missing_per_page},
                            fragment=full_fragment,
                        )
                        
                        if not page_performers:
                            continue
                        
                        # 处理这批演员
                        for performer in page_performers:
                            performer_id = performer.get("id")
                            performer_name = performer.get("name")
                            
                            if not performer_id:
                                continue
                            
                            # 只有缺失才处理
                            # 检查 export_mode：0=不处理，4=补缺
                            if export_mode == 4 and local_exporter:
                                log.info(f"[{PLUGIN_ID}] 演员 {performer_name}：export_mode=4，处理本地补缺")
                                export_func = local_exporter.get("export_actor_to_local")
                                if export_func:
                                    export_func(
                                        performer=performer,
                                        actor_output_dir=settings.get("actor_output_dir", ""),
                                        export_mode=1,
                                        server_conn=settings.get("server_connection", {}),
                                        stash_api_key=settings.get("stash_api_key", ""),
                                        dry_run=settings.get("dry_run", False)
                                    )
                                total_success += 1
                                total_processed += 1
                            elif export_mode == 0:
                                log.debug(f"[{PLUGIN_ID}] 演员 {performer_name}：export_mode=0，跳过本地导出")

                            # 检查 upload_mode：0=不处理，4=补缺
                            if upload_mode == 4 and emby_uploader:
                                log.info(f"[{PLUGIN_ID}] 演员 {performer_name}：upload_mode=4，处理 Emby 补缺")
                                upload_func = emby_uploader.get("upload_actor_to_emby")
                                if upload_func:
                                    upload_func(
                                        performer=performer,
                                        emby_server=settings.get("emby_server", ""),
                                        emby_api_key=settings.get("emby_api_key", ""),
                                        server_conn=settings.get("server_connection", {}),
                                        stash_api_key=settings.get("stash_api_key", ""),
                                        upload_mode=1
                                    )
                                total_success += 1
                                total_processed += 1
                            elif upload_mode == 0:
                                log.debug(f"[{PLUGIN_ID}] 演员 {performer_name}：upload_mode=0，跳过 Emby 上传")
                        
                        del page_performers
                        
                    except Exception as e:
                        log.error(f"获取缺失演员完整数据失败：{e}")
                        continue
            
            # 统计跳过的演员
            total_skip += (len(page_performers_basic) - need_process_count)
            
        else:
            # 非模式 4，使用原有逻辑（获取完整数据后逐个处理）
            full_fragment = """
                id
                name
                image_path
                gender
                country
                birthdate
                height_cm
                measurements
                fake_tits
                disambiguation
                details
                ethnicity
                eye_color
                hair_color
                career_length
                tattoos
                piercings
                weight
                death_date
                circumcised
                penis_length
                alias_list
                urls
            """
            
            try:
                page_performers = stash.find_performers(
                    f=None,
                    filter={"page": page, "per_page": per_page},
                    fragment=full_fragment,
                )
            except Exception as e:
                log.error(f"获取演员完整数据失败：{e}")
                del page_performers_basic
                break
            
            # 处理当前页演员
            page_total = len(page_performers)
            for i, performer in enumerate(page_performers):
                try:
                    performer_id = performer.get("id")
                    if performer_id:
                        # 直接处理（不依赖 sync_performer）
                        if export_mode != 0 and local_exporter:
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
                        
                        if upload_mode != 0 and emby_uploader:
                            upload_func = emby_uploader.get("upload_actor_to_emby")
                            if upload_func:
                                upload_func(
                                    performer=performer,
                                    emby_server=settings.get("emby_server", ""),
                                    emby_api_key=settings.get("emby_api_key", ""),
                                    server_conn=settings.get("server_connection", {}),
                                    stash_api_key=settings.get("stash_api_key", ""),
                                    upload_mode=upload_mode
                                )
                        
                        total_success += 1
                    
                    total_processed += 1
                    progress = total_processed / (page * per_page)
                    task_log_func(f"处理演员 {performer.get('name', 'Unknown')} (第{page}批，{i+1}/{page_total})", 
                                 progress=min(progress, 1.0))
                except Exception as e:
                    log.error(f"处理演员 {performer.get('name', 'Unknown')} 失败：{e}")
                    total_processed += 1
            
            del page_performers
        
        # 释放内存
        page_total = len(page_performers_basic)
        del page_performers_basic
        
        # 如果当前页少于 per_page，说明已经是最后一页
        if page_total < per_page:
            break
        
        page += 1
    
    msg = f"处理了 {total_processed} 个演员，成功 {total_success} 个"
    if total_skip > 0:
        msg += f"，跳过 {total_skip} 个"
    log.info(msg)
    task_log_func(msg, progress=1.0)
    
    return msg
