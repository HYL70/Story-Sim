"""
LLM 客户端封装 - DeepSeek API 调用
支持同步/异步调用，JSON 输出解析，重试逻辑
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from openai import OpenAI, AsyncOpenAI

import config

logger = logging.getLogger(__name__)


def _build_client(sync: bool = True):
    """创建 OpenAI 客户端（DeepSeek 兼容模式）"""
    api_key = config.DEEPSEEK_API_KEY
    if not api_key:
        raise ValueError("DeepSeek API Key 未配置，请在 .env 文件中设置 DEEPSEEK_API_KEY")
    kwargs = {
        "api_key": api_key,
        "base_url": config.DEEPSEEK_BASE_URL + "/v1" if not config.DEEPSEEK_BASE_URL.endswith("/v1") else config.DEEPSEEK_BASE_URL,
    }
    return OpenAI(**kwargs) if sync else AsyncOpenAI(**kwargs)


# 单例客户端
_client: Optional[OpenAI] = None
_async_client: Optional[AsyncOpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = _build_client(sync=True)
    return _client


def get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = _build_client(sync=False)
    return _async_client


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    max_retries: int = 3,
) -> str:
    """
    同步调用 LLM，返回纯文本响应。

    Args:
        messages: OpenAI 格式的消息列表 [{"role": ..., "content": ...}]
        model: 模型名称，默认使用 config.ACTIVE_MODEL
        temperature: 温度参数
        max_tokens: 最大输出 token
        json_mode: 是否启用 JSON 模式
        max_retries: 最大重试次数
    Returns:
        模型的文本响应
    """
    client = get_client()
    model = model or config.ACTIVE_MODEL
    temperature = temperature if temperature is not None else config.TEMPERATURE
    max_tokens = max_tokens or config.MAX_TOKENS_OUTPUT

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(max_retries):
        try:
            logger.debug(f"LLM 调用 (尝试 {attempt + 1}/{max_retries})")
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            # 记录 token 使用
            usage = response.usage
            if usage:
                logger.debug(f"Token 使用: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")
            return content
        except Exception as e:
            last_error = e
            logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)  # 指数退避

    raise RuntimeError(f"LLM 调用失败，已重试 {max_retries} 次: {last_error}")


async def chat_async(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    max_retries: int = 3,
    timeout: float = 120.0,
) -> str:
    """异步调用 LLM（带超时保护，防止无限等待）"""
    import asyncio as _asyncio
    client = get_async_client()
    model = model or config.ACTIVE_MODEL
    temperature = temperature if temperature is not None else config.TEMPERATURE
    max_tokens = max_tokens or config.MAX_TOKENS_OUTPUT

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(max_retries):
        try:
            response = await _asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=timeout,
            )
            content = response.choices[0].message.content or ""
            return content
        except _asyncio.TimeoutError:
            last_error = _asyncio.TimeoutError(f"LLM 请求超时（{timeout}s）")
            logger.warning(f"LLM 异步调用超时 (尝试 {attempt + 1}/{max_retries})，{timeout}s 无响应")
            if attempt < max_retries - 1:
                await _asyncio.sleep(2 ** attempt)
        except Exception as e:
            last_error = e
            logger.warning(f"LLM 异步调用失败 (尝试 {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await _asyncio.sleep(2 ** attempt)

    raise RuntimeError(f"LLM 异步调用失败，已重试 {max_retries} 次: {last_error}")


def parse_json_response(text: str) -> dict:
    """
    从 LLM 响应中提取 JSON 对象。
    LLM 有时会在 JSON 前后加 markdown 代码块，需要处理。
    """
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 中的内容
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # output-problems #10: 清理常见格式问题后重试
    cleaned = _clean_json_text(text)
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 { } 块
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            # output-problems #10: 尝试清理后再解析
            cleaned = _clean_json_text(brace_match.group(0))
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"无法从 LLM 响应中提取 JSON:\n{text[:500]}")


def _clean_json_text(text: str) -> str:
    """output-problems #10: 清理 JSON 文本中的常见格式问题"""
    import re as _re
    # 移除 BOM
    text = text.lstrip("\ufeff")
    # 移除尾部逗号 (JSON 不允许尾随逗号)
    text = _re.sub(r",\s*([}\]])", r"\1", text)
    # 移除单行注释 // ...
    text = _re.sub(r"//[^\n]*", "", text)
    # 将中文引号替换为英文引号
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


def test_connection() -> dict:
    """测试 API 连通性，返回模型信息"""
    try:
        response = chat(
            messages=[{"role": "user", "content": "请回复'连接成功'四个字"}],
            max_tokens=20,
            temperature=0,
        )
        return {"success": True, "message": response.strip()}
    except Exception as e:
        return {"success": False, "message": str(e)}
