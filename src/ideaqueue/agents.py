"""Agents: the models people bring. Every agent is a command that reads a prompt on stdin."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from .config import AgentSpec, ConfigError


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    cost_usd: float | None = None
    error: str = ""


class Agent(Protocol):
    def run(self, prompt: str, cwd: Path, env: dict[str, str], log: TextIO,
            timeout: float | None = None) -> RunResult: ...


def _resolve_env(raw: dict) -> dict[str, str]:
    """Values written as "env:NAME" are read from the worker's environment."""
    out = {}
    for key, value in raw.items():
        value = str(value)
        if value.startswith("env:"):
            name = value[4:]
            if name not in os.environ:
                raise ConfigError(f"environment variable {name} is not set (needed for {key})")
            value = os.environ[name]
        out[key] = value
    return out


class CommandAgent:
    """Runs any command. The prompt goes to stdin, everything printed goes to the log."""

    def __init__(self, argv: list[str], env: dict | None = None):
        self.argv = argv
        self.env = _resolve_env(env or {})

    def run(self, prompt, cwd, env, log, timeout=None) -> RunResult:
        full_env = {**os.environ, **self.env, **env}
        log.write(f"$ {shlex.join(self.argv)}\n")
        log.flush()
        try:
            proc = subprocess.Popen(
                self.argv, cwd=cwd, env=full_env, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            return RunResult(ok=False, error=f"command not found: {self.argv[0]}")
        try:
            out, _ = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            log.write(out or "")
            return RunResult(ok=False, output=out or "", error=f"timed out after {timeout}s")
        log.write(out)
        log.flush()
        return self.parse(out, proc.returncode)

    def parse(self, out: str, returncode: int) -> RunResult:
        if returncode != 0:
            return RunResult(ok=False, output=out, error=f"exit code {returncode}")
        return RunResult(ok=True, output=out)


class ClaudeCodeAgent(CommandAgent):
    """Claude Code in headless mode. Uses whatever login `claude` has (subscription or API key)."""

    def __init__(self, options: dict):
        argv = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", options.get("permission_mode", "acceptEdits")]
        if "model" in options:
            argv += ["--model", options["model"]]
        if options.get("allowed_tools"):
            argv += ["--allowedTools", ",".join(options["allowed_tools"])]
        argv += list(options.get("extra_args", []))
        super().__init__(argv, options.get("env"))

    def parse(self, out, returncode):
        result = None
        for line in out.splitlines():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "result":
                result = msg
        if result is None:
            return RunResult(ok=False, output=out, error=f"no result from claude (exit {returncode})")
        return RunResult(
            ok=not result.get("is_error", False) and returncode == 0,
            output=result.get("result", ""),
            cost_usd=result.get("total_cost_usd"),
            error=result.get("subtype", "") if result.get("is_error") else "",
        )


class CodexAgent(CommandAgent):
    """OpenAI Codex CLI. Uses whatever login `codex` has (ChatGPT plan or API key)."""

    def __init__(self, options: dict):
        argv = ["codex", "exec", "--skip-git-repo-check",
                "--sandbox", options.get("sandbox", "workspace-write")]
        if "model" in options:
            argv += ["--model", options["model"]]
        argv += list(options.get("extra_args", []))
        argv.append("-")
        super().__init__(argv, options.get("env"))


def build_agent(spec: AgentSpec) -> Agent:
    if spec.use == "claude-code":
        return ClaudeCodeAgent(spec.options)
    if spec.use == "codex":
        return CodexAgent(spec.options)
    if spec.use == "command":
        run = spec.options.get("run")
        if not run:
            raise ConfigError(f"agent '{spec.name}' uses `command` but has no `run`")
        argv = shlex.split(run) if isinstance(run, str) else list(run)
        return CommandAgent(argv, spec.options.get("env"))
    raise ConfigError(f"agent '{spec.name}': unknown `use = \"{spec.use}\"`"
                      " (expected claude-code, codex or command)")
