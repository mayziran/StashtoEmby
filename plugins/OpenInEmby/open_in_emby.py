#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
open_in_emby.py - Open in Emby 后端代理

通过 Stash 后端代理 Emby API 请求，绕过浏览器 CSP 限制。
前端读取配置并传递给后端。
"""

import json
import sys
import urllib.request
import urllib.parse
import urllib.error


def query_emby(emby_server: str, emby_internal_server: str, emby_api_key: str, stash_id: str, include_item_types: str = "Movie") -> dict:
    """通过 Stash 本地 ID 匹配 Emby 视频"""
    formatted_id = f"stash.{stash_id}"
    params = urllib.parse.urlencode({
        "IncludeItemTypes": include_item_types,
        "AnyProviderIdEquals": formatted_id,
        "Recursive": "True",
        "api_key": emby_api_key,
    })

    # ⭐ 使用内网地址搜索
    emby_url = f"{emby_internal_server}/emby/Items?{params}"

    try:
        req = urllib.request.Request(emby_url)
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            items = data.get("Items", [])

            if items:
                item = items[0]
                item_id = item.get("Id")
                server_id = item.get("ServerId", "")
                # ⭐ 使用外网地址构建跳转 URL
                if server_id:
                    detail_url = f"{emby_server}/web/index.html#!/item?id={item_id}&serverId={server_id}"
                else:
                    detail_url = f"{emby_server}/web/index.html#!/item?id={item_id}"
                return {
                    "success": True,
                    "error": None,
                    "url": detail_url,
                    "item": {"id": item_id, "name": item.get("Name")},
                }
            else:
                return {"success": True, "error": "未找到匹配", "url": None, "item": None}

    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"HTTP 错误 {e.code}", "url": None, "item": None}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"网络错误：{e.reason}", "url": None, "item": None}
    except Exception as e:
        return {"success": False, "error": f"未知错误：{str(e)}", "url": None, "item": None}


def main():
    """主函数"""
    # 读取 stdin 的 JSON 输入
    try:
        input_json = sys.stdin.read()

        if not input_json:
            print(json.dumps({"output": {"success": False, "error": "输入为空"}}))
            return

        input_data = json.loads(input_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"output": {"success": False, "error": f"JSON 解析失败：{e}"}}))
        return
    except Exception as e:
        print(json.dumps({"output": {"success": False, "error": f"读取失败：{e}"}}))
        return

    # 从 args 获取所有参数（前端传递）
    args = input_data.get("args", {})

    emby_server = args.get("embyServer", "")
    emby_internal_server = args.get("embyInternalServer", "")
    emby_api_key = args.get("embyApiKey", "")
    stash_id = args.get("stash_id")
    include_item_types = args.get("includeItemTypes", "Movie")

    # 验证参数
    if not stash_id:
        print(json.dumps({"output": {"success": False, "error": "缺少参数：stash_id"}}))
        return

    if not emby_server or not emby_internal_server or not emby_api_key:
        print(json.dumps({"output": {"success": False, "error": "缺少配置：Emby 服务器地址、内网地址、API Key"}}))
        return

    # 查询 Emby
    result = query_emby(emby_server, emby_internal_server, emby_api_key, str(stash_id), include_item_types)

    # 输出结果
    print(json.dumps({"output": result}))


if __name__ == "__main__":
    main()
