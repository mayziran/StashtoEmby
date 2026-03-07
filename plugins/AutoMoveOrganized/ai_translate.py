#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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


def _call_openai_compatible_api_for_text(
    text: str,
    cfg: Dict[str, Any],
    field: str,
    performers: Optional[List[str]] = None,
) -> Optional[str]:
    """
    调用 OpenAI 兼容的 chat/completions 接口，翻译单段文本。
    期望返回内容为「仅包含译文」的一段字符串。
    
    重试机制：最多重试 3 次，每次等待 5 秒
    如果 3 次都失败，返回 None（由调用方使用原文）
    """
    api_url = _build_chat_completions_url(cfg["base_url"])
    if not api_url or not cfg["api_key"] or not cfg["model"]:
        log.error("[translator] 缺少翻译 API 配置（base_url/api_key/model），跳过翻译")
        return None

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    # 构建 system prompt，将演员列表追加到提示词末尾
    system_prompt = cfg["prompt"]
    if performers:
        performers_str = ", ".join(performers)
        system_prompt = f"{system_prompt}{performers_str}"

    body = {
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text or ""},
        ],
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
                return result
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
                return None

    return None


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

    translated_title: Optional[str] = None
    translated_plot: Optional[str] = None

    if cfg["translate_title"] and title:
        translated_title = _call_openai_compatible_api_for_text(
            title, cfg, field="title", performers=performers
        )

    if cfg["translate_plot"] and plot:
        translated_plot = _call_openai_compatible_api_for_text(
            plot, cfg, field="plot", performers=performers
        )

    return translated_title, translated_plot

