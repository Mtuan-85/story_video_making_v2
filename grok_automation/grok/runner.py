"""Universal flow runner — executes declarative flows from flows.py."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger
from patchright.async_api import Page

from grok import actions
from grok.flows import FLOWS


class StopRequested(Exception):
    pass


class FlowRunner:
    def __init__(
        self,
        page: Page,
        config: dict[str, Any],
        prompts: list[dict[str, Any]],
        output_dir: Path,
        log_cb: Callable[[str], None] | None = None,
    ) -> None:
        self.page = page
        self.config = config
        self.prompts = prompts
        self.output_dir = output_dir
        self.log_cb = log_cb or (lambda m: logger.info(m))
        self.state: dict[str, Any] = {
            "counter": 0,
            "current_prompt": None,
            "vars": {},
            "errors": [],
            "downloaded_count": 0,
        }
        self._stop = asyncio.Event()

    # ---------- Public control ----------

    def request_stop(self) -> None:
        self._stop.set()

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise StopRequested()

    def log(self, msg: str) -> None:
        logger.info(msg)
        try:
            self.log_cb(msg)
        except Exception:
            pass

    # ---------- Param resolution ----------

    def _resolve(self, step: dict[str, Any], key: str) -> Any:
        if key in step:
            return step[key]
        # from_prompt / from_config / from_var indirection
        from_prompt = step.get("from_prompt")
        if from_prompt and key == "value":
            cp = self.state.get("current_prompt") or {}
            return cp.get(from_prompt)
        from_config = step.get("from_config")
        if from_config and key == "value":
            return self.config.get(from_config)
        from_var = step.get("from_var")
        if from_var and key == "value":
            return self.state["vars"].get(from_var)
        return None

    def _resolved_value(self, step: dict[str, Any]) -> Any:
        if "from_prompt" in step:
            return (self.state.get("current_prompt") or {}).get(step["from_prompt"])
        if "from_config" in step:
            return self.config.get(step["from_config"])
        if "from_var" in step:
            return self._resolve_var(step["from_var"])
        return step.get("value")

    def _resolve_var(self, key: str) -> Any:
        """Support 'foo.bar' nested dict access."""
        if "." in key:
            parts = key.split(".")
            val: Any = self.state["vars"].get(parts[0])
            for p in parts[1:]:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    return None
            return val
        return self.state["vars"].get(key)

    # ---------- Step dispatch ----------

    async def _exec_step(self, step: dict[str, Any]) -> dict[str, Any]:
        action = step["action"]
        page = self.page

        if action == "ensure_at":
            return await actions.ensure_at(page, step["url"])

        if action == "set_mode":
            return await actions.set_mode(page, self._resolved_value(step))

        if action == "set_quality":
            return await actions.set_quality(page, self._resolved_value(step))

        if action == "set_aspect":
            return await actions.set_aspect(page, self._resolved_value(step))

        if action == "verify_input_empty":
            return await actions.verify_input_empty(page)

        if action == "fill_prompt":
            speed = self.config.get("typing_speed", "human")
            return await actions.fill_prompt(page, self._resolved_value(step), speed=speed)

        if action == "click_submit":
            return await actions.click_submit(page)

        if action == "wait_image_ready":
            target_count = self.config.get("target_count", 4)
            timeout_ms = int(self.config.get("wait_timeout_s", 60)) * 1000
            return await actions.wait_image_ready(
                page, target_count=target_count, timeout_ms=timeout_ms
            )

        if action == "submit_and_wait_ready":
            tc_key = step.get("target_count_from_config", "target_count")
            target_count = int(self.config.get(tc_key, 4))
            timeout_ms = int(self.config.get("wait_timeout_s", 60)) * 1000
            res = await actions.submit_and_wait_ready(
                page, target_count=target_count, timeout_ms=timeout_ms
            )
            if "save_to" in step and res.get("ok"):
                self.state["vars"][step["save_to"]] = {
                    "ready_count": res.get("ready_count"),
                    "masonry_index": res.get("masonry_index"),
                }
            return res

        if action == "save_candidates_log":
            tc_key = step.get("target_count_from_config", "target_count")
            target_count = int(self.config.get(tc_key, 4))
            counter = self.state["counter"]
            project = self.config.get("project_name", "project")
            cp = self.state.get("current_prompt") or {}
            ready = self.state["vars"].get("ready_result") or {}
            masonry_index = ready.get("masonry_index", 0) if isinstance(ready, dict) else 0
            return await actions.save_candidates_log(
                page,
                output_dir=self.output_dir,
                project=project,
                counter=counter,
                prompt_text=cp.get("text", ""),
                masonry_index=int(masonry_index),
                target_count=target_count,
                pick_mode=self.config.get("pick_mode", "auto"),
            )

        if action == "pick_image":
            counter = self.state["counter"]
            project = self.config.get("project_name", "project")
            idx = await actions.pick_image(
                self.config,
                output_dir=self.output_dir,
                project=project,
                counter=counter,
            )
            if "save_to" in step:
                self.state["vars"][step["save_to"]] = idx
            return {"ok": True, "value": idx}

        if action == "upload_ref_if_present":
            value = self._resolved_value(step)
            return await actions.upload_ref_if_present(
                page, value, ref_cache=self.config.get("ref_cache") or {}
            )

        if action == "set_video_resolution":
            return await actions.set_video_resolution(page, self._resolved_value(step))

        if action == "set_video_duration":
            return await actions.set_video_duration(page, self._resolved_value(step))

        if action == "wait_video_ready":
            timeout_ms = int(self.config.get("wait_timeout_s", 600)) * 1000
            return await actions.wait_video_ready(page, timeout_ms=timeout_ms)

        if action == "click_image":
            idx = self._resolved_value(step)
            masonry_index = None
            if "masonry_from_var" in step:
                masonry_index = self._resolve_var(step["masonry_from_var"])
            elif "masonry_index" in step:
                masonry_index = step["masonry_index"]
            return await actions.click_image(
                page, int(idx), masonry_index=masonry_index
            )

        if action == "wait_url_match":
            return await actions.wait_url_match(page, step["pattern"])

        if action == "click_back":
            return await actions.click_back(page)

        if action == "human_pause":
            await actions.human_pause(step.get("min_ms", 800), step.get("max_ms", 2500))
            return {"ok": True}

        if action == "download":
            prefix = step.get("prefix", "pic")
            project = self.config.get("project_name", "project")
            counter = self.state["counter"]
            res = await actions.download(
                page, self.output_dir, project, prefix, counter
            )
            if res.get("ok"):
                self.state["downloaded_count"] += 1
            return res

        return {"ok": False, "reason": f"unknown action: {action}"}

    # ---------- Run loops ----------

    async def run(self, flow_key: str) -> dict[str, Any]:
        flow = FLOWS.get(flow_key)
        if not flow:
            return {"ok": False, "reason": f"unknown flow: {flow_key}"}

        self.log(f"Bắt đầu flow: {flow['name']}")
        try:
            if flow.get("loop_per_prompt"):
                await self._run_per_prompt(flow)
            else:
                await self._run_steps(flow["steps"])
        except StopRequested:
            self.log("Đã dừng theo yêu cầu người dùng")
            return {"ok": False, "reason": "stopped", "state": self.state}

        self.log(
            f"Hoàn tất: {self.state['downloaded_count']}/{len(self.prompts)} prompt thành công"
        )
        return {"ok": True, "state": self.state}

    async def _run_per_prompt(self, flow: dict[str, Any]) -> None:
        total = len(self.prompts)
        for i, prompt in enumerate(self.prompts, start=1):
            self._check_stop()
            self.state["counter"] = i
            self.state["current_prompt"] = prompt
            self.state["vars"].clear()
            self.log(f"[{i}/{total}] Prompt: {prompt.get('text', '')[:80]}...")
            try:
                await self._run_steps(flow["steps"])
            except StopRequested:
                raise
            except Exception as e:
                self.state["errors"].append({"prompt_id": prompt.get("id"), "type": "exception", "msg": str(e)})
                self.log(f"[{i}/{total}] ❌ exception: {e}")

            if i < total:
                try:
                    if "/post/" in (self.page.url or ""):
                        self.log("Recovery: navigating back to /imagine...")
                        await self.page.goto(
                            "https://grok.com/imagine",
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        await asyncio.sleep(2)
                except Exception as recovery_err:
                    self.log(f"Recovery navigation failed: {recovery_err}")

    async def _run_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            self._check_stop()
            res = await self._exec_step(step)
            if not res.get("ok"):
                reason = res.get("reason") or res.get("type") or "unknown"
                self.log(f"  ⚠ step '{step['action']}' failed: {reason}")
                # Phase 2: skip remaining steps for this prompt, runner moves on
                self.state["errors"].append({
                    "prompt_id": (self.state.get("current_prompt") or {}).get("id"),
                    "step": step["action"],
                    "reason": reason,
                })
                return
