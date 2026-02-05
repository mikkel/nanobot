# ACE-Step API Skill

## Overview

This skill provides a CLI tool to interact with the local ACE-Step LLM server.

## Files

- `ace_step.py` - Python script that sends requests and polls for results
- `SKILL.md` - This documentation

## Usage

```bash
ace_step "your prompt here"
```

## Environment Variables

- `ACE_STEP_API_BASE` - Base URL of the ACE-Step server (default: `http://192.168.0.181:8000`)

## Setup Notes

If the server is down, start it on the desktop:

```bash
cd /ml2/nanobot/ACE-Step-1.5
source ~/env.vars && export HUGGINGFACE_TOKEN
python -m uvicorn acestep.api_server:app --host 0.0.0.0 --port 8000 --workers 1
```

Verify it's running:

```bash
wget -qO- http://192.168.0.181:8000/docs | head -20
```

Or check the health endpoint:

```bash
wget -qO- http://192.168.0.181:8000/health
```

## Implementation Details

- **Endpoint**: `POST /v1/chat/completions`
- **Model**: `ace-step-1.5`
- **Polling**: Checks `/jobs/{task_id}/status` every 2 seconds until `completed` or `failed`
- **Timeout**: 2 minutes max (60 attempts × 2 second intervals)
