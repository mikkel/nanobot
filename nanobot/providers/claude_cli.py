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
            "--output-format", "json",
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
            except (json.JSONDecodeError, TypeError):
                if line.strip():
                    logger.debug(f"CLI raw: {line[:300]}")

    def _log_cli_event(self, event: dict[str, Any]) -> None:
        """Log a structured Claude CLI JSON event."""
        etype = event.get("type", "")

        if etype == "assistant" and "message" in event:
            msg = event["message"]
            stop = msg.get("stop_reason", "")
            usage = msg.get("usage", {})
            logger.info(
                f"CLI assistant: stop={stop}, "
                f"input_tokens={usage.get('input_tokens', '?')}, "
                f"output_tokens={usage.get('output_tokens', '?')}"
            )

        elif etype == "content_block_start":
            block = event.get("content_block", {})
            btype = block.get("type", "")
            if btype == "tool_use":
                logger.info(f"CLI tool_use: {block.get('name', '?')}")
            elif btype == "text":
                logger.debug("CLI text block start")

        elif etype == "content_block_stop":
            # Try to log tool input after block completes
            pass

        elif etype == "result":
            # Final result from -p mode
            cost = event.get("total_cost_usd")
            session_id = event.get("session_id", "")[:12]
            result_preview = str(event.get("result", ""))[:200]
            logger.info(
                f"CLI result: session={session_id}..., "
                f"cost=${cost or '?'}"
            )
            logger.debug(f"CLI result preview: {result_preview}")

        elif etype == "system":
            # System messages (session info, etc.)
            sub = event.get("subtype", "")
            logger.debug(f"CLI system: {sub}")

        elif etype == "error":
            logger.error(f"CLI event error: {event.get('error', event)}")

    def _parse_cli_output(self, output: str) -> dict[str, Any]:
        """Parse Claude CLI JSON output."""
        if not output:
            return {"text": "", "session_id": None}
        
        try:
            # Try parsing as single JSON object
            data = json.loads(output)
            return self._extract_from_json(data)
        except json.JSONDecodeError:
            pass
        
        # Try parsing as JSONL (multiple JSON objects)
        result_text = []
        session_id = None
        usage = {}
        
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                extracted = self._extract_from_json(data)
                if extracted.get("text"):
                    result_text.append(extracted["text"])
                if extracted.get("session_id"):
                    session_id = extracted["session_id"]
                if extracted.get("usage"):
                    usage = extracted["usage"]
            except json.JSONDecodeError:
                # Non-JSON line, might be raw text
                result_text.append(line)
        
        return {
            "text": "\n".join(result_text),
            "session_id": session_id,
            "usage": usage,
        }
    
    def _extract_from_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant fields from parsed JSON.
        
        Claude CLI output format (--output-format json):
        {
            "type": "result",
            "subtype": "success",
            "result": "...",  # Main response text
            "session_id": "...",
            "usage": {...},
            "total_cost_usd": 0.01,
            ...
        }
        """
        # Check for error
        if data.get("is_error") or data.get("subtype") == "error":
            error_msg = data.get("result") or data.get("error") or "Unknown error"
            return {"text": f"Error: {error_msg}", "session_id": None, "usage": {}}
        
        # Get response text - "result" is the main field in Claude CLI JSON output
        text = (
            data.get("result") or
            data.get("response") or
            data.get("content") or
            data.get("text") or
            data.get("message") or
            ""
        )
        
        session_id = (
            data.get("session_id") or
            data.get("sessionId") or
            data.get("conversation_id") or
            data.get("conversationId") or
            None
        )
        
        # Extract usage info (Claude CLI format)
        usage = data.get("usage", {})
        if data.get("total_cost_usd"):
            usage["total_cost_usd"] = data["total_cost_usd"]
        
        return {
            "text": text,
            "session_id": session_id,
            "usage": usage,
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
