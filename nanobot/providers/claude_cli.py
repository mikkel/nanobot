"""Claude CLI provider - uses Claude Code subscription via CLI."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.auth import ClaudeOAuthManager
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# Model aliases for Claude CLI
CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "opus": "opus",
    "opus-4.5": "opus",
    "opus-4": "opus",
    "claude-opus-4-5": "opus",
    "claude-opus-4": "opus",
    "anthropic/claude-opus-4-5": "opus",  # Support LiteLLM format
    "anthropic/claude-opus-4-6": "opus",
    "anthropic/claude-opus-4.6": "opus",
    "anthropic/claude-opus-4": "opus",
    "claude-opus-4-6": "opus",
    "sonnet": "sonnet",
    "sonnet-4.5": "sonnet",
    "sonnet-4.1": "sonnet",
    "sonnet-4.0": "sonnet",
    "claude-sonnet-4-5": "sonnet",
    "claude-sonnet-4-1": "sonnet",
    "claude-sonnet-4-0": "sonnet",
    "anthropic/claude-sonnet-4-5": "sonnet",  # Support LiteLLM format
    "anthropic/claude-sonnet-4-1": "sonnet",
    "haiku": "haiku",
    "haiku-3.5": "haiku",
    "claude-haiku-3-5": "haiku",
    "anthropic/claude-haiku-3-5": "haiku",  # Support LiteLLM format
}


class ClaudeCliProvider(LLMProvider):
    """
    LLM provider that uses the Claude CLI (Claude Code subscription).

    This provider spawns the `claude` CLI process to interact with Claude,
    allowing use of Claude Max subscription instead of API credits.

    Features automatic OAuth token refresh following OpenClaw patterns.
    """

    def __init__(
        self,
        default_model: str = "opus",
        command: str = "claude",
        timeout_seconds: int = 300,
        working_dir: str | None = None,
        auth_profile: str = "anthropic:default",
    ):
        """
        Initialize the Claude CLI provider.

        Args:
            default_model: Default model to use (opus, sonnet, haiku).
            command: Path to claude CLI executable.
            timeout_seconds: Max time to wait for CLI response.
            working_dir: Working directory for CLI execution.
            auth_profile: OAuth profile ID to use for authentication.
        """
        super().__init__(api_key=None, api_base=None)
        self.default_model = self._normalize_model(default_model)
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.working_dir = working_dir
        self.auth_profile = auth_profile
        self._session_ids: dict[str, str] = {}  # session_key -> claude_session_id
        self._oauth_manager = ClaudeOAuthManager()
    
    def _normalize_model(self, model: str) -> str:
        """Normalize model name to Claude CLI format."""
        model_lower = model.lower().strip()
        return CLAUDE_MODEL_ALIASES.get(model_lower, model_lower)
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        session_key: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request via Claude CLI.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions (NOT SUPPORTED in CLI mode).
            model: Model identifier (opus, sonnet, haiku).
            max_tokens: Maximum tokens in response (ignored by CLI).
            temperature: Sampling temperature (ignored by CLI).
            session_key: Optional session key for conversation continuity.
        
        Returns:
            LLMResponse with content.
        
        Note:
            Tool calls are NOT supported when using Claude CLI.
            The CLI runs in non-interactive mode without tool execution.
        """
        model = self._normalize_model(model or self.default_model)
        
        # Build prompt from messages (include full conversation history)
        prompt = self._build_prompt_from_messages(messages)
        system_prompt = self._extract_system_prompt(messages)

        # Log request size for debugging
        prompt_bytes = len(prompt.encode("utf-8"))
        system_bytes = len(system_prompt.encode("utf-8")) if system_prompt else 0
        msg_count = len([m for m in messages if m.get("role") != "system"])
        logger.info(
            f"CLI request: model={model}, messages={msg_count}, "
            f"prompt={prompt_bytes:,}B, system={system_bytes:,}B, "
            f"total={prompt_bytes + system_bytes:,}B"
        )
        logger.debug(f"CLI system prompt ({system_bytes:,}B):\n{(system_prompt or '(none)')[:2000]}")
        logger.debug(f"CLI prompt ({prompt_bytes:,}B):\n{prompt[:5000]}")
        if len(prompt) > 5000:
            logger.debug(f"CLI prompt tail:\n...{prompt[-2000:]}")

        # NOTE: We intentionally DON'T use Claude CLI's --resume feature
        # because we manage our own session history. Using --resume would
        # cause duplicate context (our history + CLI's history).
        # Instead, we always pass the full conversation as context.

        try:
            result = await self._run_claude_cli(
                prompt=prompt,
                model=model,
                session_id=None,  # Don't resume - we pass full history
                system_prompt=system_prompt,
            )
            
            return LLMResponse(
                content=result.get("text", ""),
                tool_calls=[],  # CLI doesn't support tools
                finish_reason="stop",
                usage=result.get("usage", {}),
            )
            
        except asyncio.TimeoutError:
            logger.error(
                f"CLI request timed out: model={model}, messages={msg_count}, "
                f"prompt={prompt_bytes:,}B, system={system_bytes:,}B, "
                f"timeout={self.timeout_seconds}s"
            )
            return LLMResponse(
                content=f"Error: Claude CLI timed out after {self.timeout_seconds}s "
                        f"(prompt={prompt_bytes:,}B, {msg_count} messages).",
                finish_reason="error",
            )
        except Exception as e:
            logger.error(f"Claude CLI error: {e}")
            return LLMResponse(
                content=f"Error calling Claude CLI: {str(e)}",
                finish_reason="error",
            )
    
    def _build_prompt_from_messages(self, messages: list[dict[str, Any]]) -> str:
        """Convert message list to a single prompt string."""
        parts = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # System messages are handled separately
                continue
            elif role == "user":
                parts.append(f"Human: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                # Include tool results as context
                tool_name = msg.get("name", "tool")
                parts.append(f"[Tool Result from {tool_name}]: {content}")
        
        # Add final prompt marker
        if parts and not parts[-1].startswith("Human:"):
            parts.append("Human: Please continue.")
        
        return "\n\n".join(parts)
    
    def _extract_system_prompt(self, messages: list[dict[str, Any]]) -> str | None:
        """Extract system prompt from messages."""
        for msg in messages:
            if msg.get("role") == "system":
                return msg.get("content", "")
        return None
    
    async def _run_claude_cli(
        self,
        prompt: str,
        model: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute Claude CLI and parse response.
        
        Args:
            prompt: The user prompt.
            model: Model to use.
            session_id: Optional session ID for resumption.
            system_prompt: Optional system prompt to append.
        
        Returns:
            Dict with 'text', 'session_id', and optionally 'usage'.
        """
        # Build command arguments
        # NOTE: Prompt must be passed via stdin (pipe), NOT as argument!
        args = [
            self.command,
            "-p",  # Print mode (non-interactive)
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        
        # Add session handling
        if session_id:
            args.extend(["--resume", session_id])
        
        # Add system prompt if provided and this is a new session
        if system_prompt and not session_id:
            args.extend(["--append-system-prompt", system_prompt])
        
        # Get OAuth API key from manager (with automatic refresh)
        env = os.environ.copy()
        api_key = await self._oauth_manager.get_api_key_for_profile(self.auth_profile)

        if api_key:
            # Use OAuth token
            env["ANTHROPIC_API_KEY"] = api_key
            logger.debug(f"Using OAuth token for {self.auth_profile}")
        else:
            # Fallback to CLI subscription (remove API key from environment)
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("ANTHROPIC_API_KEY_OLD", None)
            logger.debug("Using CLI subscription mode")
        
        prompt_bytes = len(prompt.encode("utf-8"))
        cmd_str = " ".join(args)
        logger.debug(f"Running Claude CLI: {cmd_str}")
        logger.debug(f"CLI stdin: {prompt_bytes:,}B, timeout={self.timeout_seconds}s")

        # Run the CLI with prompt via stdin, streaming stdout for live logging
        t0 = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
            env=env,
        )

        # Send prompt via stdin then close it
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()

        # Read stdout line-by-line for live logging
        stdout_lines: list[str] = []
        try:
            read_coro = self._stream_stdout(process, stdout_lines)
            if self.timeout_seconds > 0:
                await asyncio.wait_for(read_coro, timeout=self.timeout_seconds)
            else:
                await read_coro
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            process.kill()
            await process.wait()
            logger.error(
                f"CLI TIMEOUT after {elapsed:.1f}s (limit={self.timeout_seconds}s): "
                f"model={model}, stdin={prompt_bytes:,}B"
            )
            raise

        # Drain stderr after process completes
        stderr_data = await process.stderr.read()
        await process.wait()

        elapsed = time.monotonic() - t0
        stdout_text = "\n".join(stdout_lines)
        stderr_text = stderr_data.decode("utf-8").strip()

        logger.info(
            f"CLI completed in {elapsed:.1f}s: model={model}, "
            f"stdin={prompt_bytes:,}B, stdout={len(stdout_text):,}B, "
            f"returncode={process.returncode}"
        )
        if stderr_text:
            logger.debug(f"CLI stderr: {stderr_text[:1000]}")

        if process.returncode != 0:
            error_msg = stderr_text or stdout_text or "CLI failed with no output"
            logger.error(f"CLI failed (code {process.returncode}): {error_msg[:500]}")
            raise RuntimeError(f"Claude CLI failed (code {process.returncode}): {error_msg}")

        # Parse JSON output
        return self._parse_cli_output(stdout_text)
    
    async def _stream_stdout(
        self,
        process: asyncio.subprocess.Process,
        lines: list[str],
    ) -> None:
        """Read stdout line-by-line and log Claude CLI events in real time."""
        assert process.stdout is not None
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8").rstrip("\n")
            lines.append(line)

            # Try to parse as JSON event for live logging
            try:
                event = json.loads(line)
                self._log_cli_event(event)
            except Exception:
                if line.strip():
                    logger.debug(f"CLI raw: {line[:300]}")

    def _log_cli_event(self, event: dict[str, Any]) -> None:
        """Log a structured Claude CLI stream-json event."""
        etype = event.get("type", "")

        if etype == "assistant" and "message" in event:
            msg = event["message"]
            stop = msg.get("stop_reason", "")
            usage = msg.get("usage", {})
            # Log tool_use and text blocks from content
            content_blocks = msg.get("content", [])
            for block in content_blocks:
                btype = block.get("type", "")
                if btype == "tool_use":
                    tool_name = block.get("name", "?")
                    tool_input = block.get("input", {})
                    # Show the most useful arg (command for Bash, path for Read, etc.)
                    detail = (
                        tool_input.get("command")
                        or tool_input.get("file_path")
                        or tool_input.get("path")
                        or tool_input.get("pattern")
                        or tool_input.get("query")
                        or tool_input.get("prompt", "")[:100]
                        or str(tool_input)[:100]
                    )
                    logger.info(f"CLI tool: {tool_name}({detail})")
                elif btype == "text":
                    text = block.get("text", "")
                    if text.strip():
                        logger.debug(f"CLI text: {text[:200]}")
            if stop:
                logger.info(
                    f"CLI turn done: stop={stop}, "
                    f"in={usage.get('input_tokens', '?')}, "
                    f"out={usage.get('output_tokens', '?')}"
                )

        elif etype == "user":
            # Tool result coming back
            msg = event.get("message", {})
            content_blocks = msg.get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        result_text = str(result_content) if not isinstance(result_content, str) else result_content
                        is_err = block.get("is_error", False)
                        status = "ERROR" if is_err else "ok"
                        logger.info(f"CLI tool result: {status}, {len(result_text):,}B")
                        logger.debug(f"CLI tool result: {result_text[:300]}")
            # Also check tool_use_result for richer info
            tur = event.get("tool_use_result")
            if isinstance(tur, dict):
                stdout = tur.get("stdout", "")
                stderr = tur.get("stderr", "")
                if stderr:
                    logger.warning(f"CLI tool stderr: {stderr[:300]}")
                if stdout:
                    logger.debug(f"CLI tool stdout: {stdout[:300]}")

        elif etype == "result":
            # Final result from -p mode
            cost = event.get("total_cost_usd")
            session_id = event.get("session_id", "")[:12]
            turns = event.get("num_turns", "?")
            duration = event.get("duration_ms", 0)
            result_preview = str(event.get("result", ""))[:200]
            logger.info(
                f"CLI done: {turns} turns, {duration}ms, "
                f"cost=${cost or '?'}, session={session_id}..."
            )
            logger.debug(f"CLI result: {result_preview}")

        elif etype == "system":
            sub = event.get("subtype", "")
            if sub == "init":
                tools = event.get("tools", [])
                model = event.get("model", "?")
                logger.info(f"CLI init: model={model}, tools={len(tools)}")
            else:
                logger.debug(f"CLI system: {sub}")

        elif etype == "error":
            logger.error(f"CLI error: {event.get('error', event)}")

    def _parse_cli_output(self, output: str) -> dict[str, Any]:
        """Parse Claude CLI stream-json output.

        stream-json emits one JSON object per line. We look for:
        - type=result: final result with text, session_id, usage, cost
        - type=assistant: intermediate messages (text/tool_use blocks)

        The "result" event is authoritative — it has the final response text.
        """
        if not output:
            return {"text": "", "session_id": None}

        # Parse all JSONL events, find the result event
        result_event = None
        last_assistant_text = ""

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = data.get("type", "")

            if etype == "result":
                result_event = data
            elif etype == "assistant":
                # Extract text from content blocks as fallback
                for block in data.get("message", {}).get("content", []):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        last_assistant_text = block["text"]

        # Use result event if found (preferred)
        if result_event:
            text = result_event.get("result", "") or ""
            if result_event.get("is_error") or result_event.get("subtype") == "error":
                text = f"Error: {text}" if text else "Error: Unknown CLI error"
            return {
                "text": text,
                "session_id": result_event.get("session_id"),
                "usage": result_event.get("usage", {}),
            }

        # Fallback: use last assistant text
        return {
            "text": last_assistant_text or "",
            "session_id": None,
            "usage": {},
        }
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
    
    def clear_session(self, session_key: str) -> None:
        """Clear stored session ID for a given key."""
        self._session_ids.pop(session_key, None)
    
    def get_session_id(self, session_key: str) -> str | None:
        """Get stored session ID for a given key."""
        return self._session_ids.get(session_key)
