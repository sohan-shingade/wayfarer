"""Agent runtime: invoke Claude Code headless (`claude -p`) as a subprocess.

The whole point of this module: run the LLM agents on your Claude Max/Pro
*subscription*, not on per-token API billing. Two facts drive the design.

1. If ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL) is present
   in the environment, the `claude` CLI silently prefers it and bills your API
   account. So we run the child process with those vars stripped.

2. KNOWN ISSUE (see README "Billing"): there are open reports that `claude -p`
   bills as API usage even with no key set. Scrubbing is necessary but maybe not
   sufficient. So we read `total_cost_usd` from the JSON result and refuse to
   continue if it is positive on a run we expected to be subscription-covered.

`AgentRuntime` is an interface so you can swap `ClaudeCLIRuntime` (subscription,
local dev) for an API-key runtime when/if this is productized (required by ToS).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from typing import Any

# Vars that, if present, route auth onto API/gateway billing instead of the sub.
_BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


class AgentRuntimeError(RuntimeError):
    pass


def subscription_env() -> dict[str, str]:
    """A copy of the current environment with billing-forcing vars removed.

    Exposed (and unit-tested) so you can assert the scrub actually happens.
    """
    env = dict(os.environ)
    for var in _BILLING_ENV_VARS:
        env.pop(var, None)
    return env


@dataclass
class AgentResult:
    text: str
    raw: dict[str, Any]
    cost_usd: float | None  # should be 0/None for a subscription run
    session_id: str | None


class AgentRuntime:
    """Swap target. Today: Claude Code CLI on subscription. Later: Anthropic API."""

    async def run(self, prompt: str, *, system: str | None = None) -> AgentResult:
        raise NotImplementedError


class ClaudeCLIRuntime(AgentRuntime):
    def __init__(
        self,
        model: str = "sonnet",
        max_turns: int = 4,  # >1: a single turn can hit error_max_turns if the model
                             # takes an intermediate step before emitting the JSON.
        bare: bool = True,
        timeout_s: float = 300.0,  # the brainstormer emits ~40 detailed candidates.
        fail_on_api_billing: bool = True,
        use_system_flag: bool = False,  # if your CLI lacks --append-system-prompt, leave False
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self.bare = bare
        self.timeout_s = timeout_s
        self.fail_on_api_billing = fail_on_api_billing
        self.use_system_flag = use_system_flag
        if shutil.which("claude") is None:
            raise AgentRuntimeError(
                "`claude` CLI not found on PATH. Install Claude Code and run `claude login` "
                "with your Pro/Max account first."
            )

    def _cmd(self, prompt: str, system: str | None) -> list[str]:
        # Default: fold the system instructions into the prompt (works on every CLI version).
        if system and not self.use_system_flag:
            prompt = f"{system}\n\n{prompt}"
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--model", self.model,
            "--max-turns", str(self.max_turns),
        ]
        if self.bare:
            # Isolate from local settings/hooks/plugins/CLAUDE.md/MCP for deterministic
            # agent output. NOTE: we do NOT use `--bare` -- on current CLI versions
            # (verified 2.1.183) it disables credential loading and breaks subscription
            # auth ("Not logged in"). Empty setting-sources + strict MCP gives the same
            # isolation while keeping the keychain/OAuth login working.
            cmd += ["--setting-sources", "", "--strict-mcp-config"]
        if system and self.use_system_flag:
            cmd += ["--append-system-prompt", system]
        return cmd

    async def run(self, prompt: str, *, system: str | None = None) -> AgentResult:
        env = subscription_env()
        proc = await asyncio.create_subprocess_exec(
            *self._cmd(prompt, system),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            raise AgentRuntimeError(f"claude -p timed out after {self.timeout_s}s")

        if proc.returncode != 0:
            raise AgentRuntimeError(
                f"claude -p exited {proc.returncode}: {err.decode(errors='replace')[:500]}"
            )

        try:
            data = json.loads(out.decode())
        except json.JSONDecodeError as exc:
            raise AgentRuntimeError(
                f"could not parse claude -p JSON envelope: {exc}; raw={out[:500]!r}"
            )

        if data.get("is_error"):
            raise AgentRuntimeError(f"claude -p returned an error: {data.get('result')}")

        cost = data.get("total_cost_usd")
        if self.fail_on_api_billing and cost not in (None, 0, 0.0):
            raise AgentRuntimeError(
                f"Refusing to continue: claude -p reported total_cost_usd={cost}. That means "
                f"this run billed your API account, not your subscription. Check `/status` and "
                f"the README 'Billing' note before retrying."
            )

        return AgentResult(
            text=data.get("result", ""),
            raw=data,
            cost_usd=cost,
            session_id=data.get("session_id"),
        )


def run_sync(runtime: AgentRuntime, prompt: str, *, system: str | None = None) -> AgentResult:
    return asyncio.run(runtime.run(prompt, system=system))


def parse_json_block(text: str) -> Any:
    """Agents are told to emit JSON. Strip code fences / a leading 'json' tag, then parse."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip()
    if t.lower().startswith("json"):
        t = t[4:].strip()
    return json.loads(t)
