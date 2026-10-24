"""反思飞轮：消费 pending_reflection → Evolution Guidelines 落盘（Phase 4 SPEC A4）。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from cangjie_fos.core import paths as fos_paths
from cangjie_fos.services.evolution_store import EvolutionJsonStore

logger = logging.getLogger(__name__)


class ReflectionService:
    def enqueue_reflection(self, record_id: str, *, tenant_id: str) -> None:
        logger.info(
            "reflection_enqueued record_id=%s tenant_id=%s",
            record_id,
            tenant_id,
        )

    def run_nightly_settle(self, *, tenant_id: str | None = None) -> dict[str, int | str]:
        """处理 pending_reflection；tenant_id 为空则扫描全部租户目录。"""
        store = EvolutionJsonStore()
        paths = store.list_pending_records(tenant_id=tenant_id)
        if not paths:
            return {"processed": 0, "guideline": "", "note": "no pending records"}

        chunks: list[str] = []
        for p in paths[:40]:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                chunks.append(
                    f"tenant={raw.get('tenant_id')}\nAI:{(raw.get('ai_text') or '')[:400]}\nUSER:{(raw.get('user_text') or '')[:400]}\n---\n"
                )
            except (json.JSONDecodeError, OSError):
                continue

        blob = "\n".join(chunks)[:12000]
        guideline = self._distill_guidelines(blob)
        self._append_guideline_line(guideline, tenant_scope=tenant_id or "all")

        n = 0
        for p in paths:
            try:
                store.mark_reflected(p)
                n += 1
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("mark_reflected_failed path=%s err=%s", p, e)

        return {"processed": n, "guideline": guideline[:2000]}

    def _append_guideline_line(self, text: str, *, tenant_scope: str) -> None:
        root = fos_paths.get_backend_root() / "data" / "evolution"
        root.mkdir(parents=True, exist_ok=True)
        line = {
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "tenant_scope": tenant_scope,
            "text": text,
        }
        fp = root / "evolution_guidelines.jsonl"
        with fp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _distill_guidelines(self, blob: str) -> str:
        import os

        key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            return (
                "【离线反思】通用防坑建议："
                "对「产能/交付/客户集中度」等硬问题准备独立数据表；"
                "对红杉类美元基金提前对齐口径与英文材料命名；"
                "避免在 Teaser 与数据室出现互相矛盾的数字。"
            )
        try:
            from openai import OpenAI

            if os.getenv("DEEPSEEK_API_KEY"):
                client = OpenAI(
                    api_key=os.getenv("DEEPSEEK_API_KEY"),
                    base_url="https://api.deepseek.com",
                )
                model = os.getenv("CANGJIE_REFLECTION_MODEL", "deepseek-chat")
            else:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                model = os.getenv("CANGJIE_REFLECTION_MODEL", "gpt-4o-mini")
            r = client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=[
                    {
                        "role": "system",
                        "content": "你是融资材料复盘官。将多条用户纠错样本提炼为3-6条可执行的「Evolution Guidelines」防坑清单，中文要点，不要重复逐条复述。",
                    },
                    {"role": "user", "content": blob},
                ],
                max_tokens=800,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("reflection_llm_failed: %s", e)
            return f"【反思模型失败】{e!s}"
