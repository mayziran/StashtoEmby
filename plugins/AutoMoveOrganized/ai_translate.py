#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import stashapi.log as log


DEFAULT_TRANSLATE_PROMPT = (
    "You are a professional translator for adult video metadata. "
    "Translate the given text into natural, fluent Simplified Chinese "
    "suitable for use as a media title or description. "
    "Return ONLY the translated text, without explanations or surrounding quotes. "
    "All names (actors, directors, etc.) must remain in original form, do not translate them. "
    "Actors in this video: "
)


def _get_translate_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    从插件 settings 中抽取翻译相关配置。
    """
    base_url = (settings.get("translate_api_base") or "").strip().rstrip("/")
    api_key = (settings.get("translate_api_key") or "").strip()
    model = (settings.get("translate_model") or "").strip()
    temp_raw = (settings.get("translate_temperature") or "").strip()
    try:
        temperature = float(temp_raw) if temp_raw else 0.3
    except Exception:
        temperature = 0.3

    prompt = (settings.get("translate_prompt") or "").strip() or DEFAULT_TRANSLATE_PROMPT

    return {
        "enabled": bool(settings.get("translate_enable")),
        "translate_title": bool(settings.get("translate_title")),
        "translate_plot": bool(settings.get("translate_plot")),
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "prompt": prompt,
    }


def _build_chat_completions_url(base_url: str) -> str:
    """
    根据 base_url 构造 chat/completions 接口地址。
    例如:
      - https://api.openai.com/v1      -> https://api.openai.com/v1/chat/completions
      - https://api.xxx.com/v1        -> https://api.xxx.com/v1/chat/completions
    """
    if not base_url:
        return ""
    return f"{base_url}/chat/completions"


def _call_openai_compatible_api_for_combined_text(
    title: str,
    plot: str,
    cfg: Dict[str, Any],
    performers: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    调用 OpenAI 兼容的 chat/completions 接口，一次性翻译标题和简介。
    使用 JSON 格式输入和输出，便于 AI 理解和解析。

    输入格式（JSON）：
        {"title": "标题文本", "plot": "简介文本"}

    输出格式（JSON）：
        {"title": "翻译后的标题", "plot": "翻译后的简介"}

    重试机制：最多重试 3 次，每次等待 5 秒
    如果 3 次都失败，返回 (None, None)
    """
    api_url = _build_chat_completions_url(cfg["base_url"])
    if not api_url or not cfg["api_key"] or not cfg["model"]:
        log.error("[translator] 缺少翻译 API 配置（base_url/api_key/model），跳过翻译")
        return None, None

    # 构建输入文本（JSON 格式）
    input_data = {}
    need_title = cfg["translate_title"] and title
    need_plot = cfg["translate_plot"] and plot

    if need_title:
        input_data["title"] = title
    if need_plot:
        input_data["plot"] = plot

    if not input_data:
        return None, None

    input_text = json.dumps(input_data, ensure_ascii=False)

    # 构建 system prompt（使用默认提示词，追加演员列表和 JSON 格式要求）
    system_prompt = cfg["prompt"]
    if performers:
        performers_str = ", ".join(performers)
        system_prompt = f"{system_prompt}{performers_str}"
    # 追加 JSON 格式要求，让 AI 按标准格式返回
    system_prompt += " Return the translation in JSON format: {\"title\": \"...\", \"plot\": \"...\"} with only the translated fields."

    body = {
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
    }

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    # 最多重试 3 次，使用指数退避策略（5s, 10s, 15s）
    # 所有错误都重试：超时、HTTP 错误（429 限流、408 超时等）、网络错误、其他异常
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(api_url, headers=headers, json=body, timeout=40)
            resp.raise_for_status()
            data = resp.json()

            # 解析翻译结果
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                content = str(content)

            result = content.strip()
            if result:
                # 解析 JSON 格式返回结果
                return _parse_json_result(result, need_title, need_plot)
            else:
                # 空内容也视为失败，继续重试
                if attempt < max_attempts:
                    wait_time = 5 * attempt
                    time.sleep(wait_time)
                continue

        except Exception as e:
            if attempt < max_attempts:
                wait_time = 5 * attempt
                time.sleep(wait_time)
            else:
                log.error(f"[translator] Translation failed after {max_attempts} attempts: {e}")
                return None, None

    return None, None


def _parse_json_result(
    result: str,
    need_title: bool,
    need_plot: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 AI 返回的 JSON 格式结果，提取标题和简介。

    期望格式（JSON）：
        {"title": "翻译后的标题", "plot": "翻译后的简介"}

    或单字段：
        {"title": "翻译后的标题"}
    或
        {"plot": "翻译后的简介"}
    """
    translated_title = None
    translated_plot = None

    try:
        # 尝试直接解析 JSON
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            translated_title = parsed.get("title")
            translated_plot = parsed.get("plot")
    except json.JSONDecodeError:
        # JSON 解析失败，尝试兼容处理
        log.warning(f"[translator] JSON parse failed, trying fallback: {result[:100]}")
        # Fallback: 将整个结果作为简介
        if need_plot:
            translated_plot = result
        elif need_title:
            translated_title = result

    return translated_title, translated_plot


def translate_title_and_plot(
    title: str,
    plot: str,
    settings: Dict[str, Any],
    performers: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    根据配置调用翻译服务，返回 (translated_title, translated_plot)。
    如果翻译失败或未启用，则返回 (None, None)，由调用方决定回退逻辑。

    Args:
        title: 标题
        plot: 简介
        settings: 设置字典
        performers: 演员名列表，用于告诉 AI 不要翻译这些名字
    """
    cfg = _get_translate_config(settings)

    if not cfg["enabled"]:
        return None, None

    # 如果两个都不需要翻译，直接返回
    if not cfg["translate_title"] and not cfg["translate_plot"]:
        return None, None

    # 一次 API 调用完成标题和简介翻译
    return _call_openai_compatible_api_for_combined_text(
        title, plot, cfg, performers
    )

