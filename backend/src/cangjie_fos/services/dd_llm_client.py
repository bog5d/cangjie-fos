"""
尽调响应台共享 LLM 客户端工厂。

────────── 为什么需要这个文件 ──────────
v0.7.0 中 dd_match_service / dd_index_service / dd_checklist_parser 三个文件
各自独立创建 OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="...")，
存在两个问题：
  1. 硬编码 DeepSeek —— 换模型要同时改 3 个文件
  2. 没有重试逻辑 —— LLM 网络抖动导致整批 30 条需求项全部「无匹配」

本模块：
  - get_dd_llm_client() → 统一读取 DEEPSEEK_API_KEY / OPENAI_API_KEY（与
    institution_intel_extract.py / reflection_service.py 保持一致）
  - call_with_retry(fn, max_retries=3) → LLM 调用 3 次重试，指数退避

使用方式（各服务文件统一改为）：
  from cangjie_fos.services.dd_llm_client import get_dd_llm_client
  client = get_dd_llm_client()
  resp = call_with_retry(
      lambda: client.chat.completions.create(model="deepseek-chat", ...)
  )
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, TypeVar

from openai import OpenAI

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ═══════════════════════════════════════════════════════════════
# 配置常量（可在此修改默认值，无需改各服务文件）
# ═══════════════════════════════════════════════════════════════
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_RETRY_MAX = 3          # 最大重试次数
_RETRY_BASE_DELAY = 2.0  # 首次重试等待秒数（指数退避：2s → 4s → 8s）


def get_dd_llm_client() -> OpenAI:
    """
    获取尽调响应台专用 LLM 客户端。

    密钥优先级：DEEPSEEK_API_KEY > OPENAI_API_KEY
    （与其他服务文件 institution_intel_extract.py / reflection_service.py 一致）

    返回：
        OpenAI 客户端实例（同步）。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    # 用 DeepSeek key → DeepSeek API；用 OpenAI key → OpenAI API
    if os.getenv("DEEPSEEK_API_KEY"):
        base_url = "https://api.deepseek.com"
    else:
        base_url = None  # OpenAI Python SDK 默认 base_url

    return OpenAI(api_key=api_key, base_url=base_url)


def call_with_retry(fn: Callable[[], T], max_retries: int = _RETRY_MAX) -> T:
    """
    带指数退避的重试包装器。

    场景：LLM API 偶发网络超时/429限流/服务暂时不可用。
    一次 batch 失败 → 等 2s 重试 → 再失败 → 等 4s → 第 3 次仍失败才抛异常。

    这替代了 v0.7.0 中 `except Exception: batch_results = {}` 的粗暴处理
    （一次网络抖动就丢掉整批 30 条需求项的结果）。

    参数：
        fn：要重试的可调用对象（lambda 或函数引用）
        max_retries：最大尝试次数（含首次），默认 3

    返回：
        fn() 的返回值（首次成功即返回）

    异常：
        重试 max_retries 次全部失败后，抛出最后一次异常
    """
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM调用失败（第%d/%d次），%ss后重试: %s",
                    attempt, max_retries, delay, e,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "LLM调用失败（%d次全部失败）: %s", max_retries, e,
                )

    # 所有重试耗尽
    raise last_exception  # type: ignore[misc]
