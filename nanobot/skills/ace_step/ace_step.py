#!/usr/bin/env python3
"""
ACE-Step API client - query local ACE-Step server and poll for results.
"""

import os
import sys
import time
import requests

# Configuration
API_BASE = os.environ.get("ACE_STEP_API_BASE", "http://192.168.0.181:8000")
MODEL = "ace-step-1.5"
POLL_INTERVAL = 2  # seconds
MAX_POLL_ATTEMPTS = 60  # 2 minutes max


def send_request(prompt: str) -> str:
    """Send a chat completion request to ACE-Step."""
    url = f"{API_BASE}/v1/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result.get("task_id", "")
    except Exception as e:
        print(f"Error sending request: {e}", file=sys.stderr)
        sys.exit(1)


def poll_status(task_id: str) -> str:
    """Poll the job status endpoint until completion or timeout."""
    url = f"{API_BASE}/jobs/{task_id}/status"

    for _ in range(MAX_POLL_ATTEMPTS):
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            status = response.json()

            if status.get("status") == "completed":
                return status.get("result", "No result returned")
            elif status.get("status") == "failed":
                return f"Job failed: {status.get('error', 'Unknown error')}"
            elif status.get("status") == "pending":
                print(f"Pending... (waiting for result)", file=sys.stderr)
            elif status.get("status") == "running":
                print(f"Processing... (this may take a moment)", file=sys.stderr)

        except Exception as e:
            print(f"Error polling status: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL)
            continue

        time.sleep(POLL_INTERVAL)

    return "Timeout waiting for result"


def main():
    if len(sys.argv) < 2:
        print("Usage: ace_step 'your prompt here'", file=sys.stderr)
        sys.exit(1)

    prompt = sys.argv[1]
    print(f"Sending prompt to ACE-Step...", file=sys.stderr)

    task_id = send_request(prompt)
    if not task_id:
        print("Error: No task ID returned", file=sys.stderr)
        sys.exit(1)

    print(f"Task ID: {task_id}", file=sys.stderr)
    print("Waiting for result...", file=sys.stderr)

    result = poll_status(task_id)
    print(result)


if __name__ == "__main__":
    main()
