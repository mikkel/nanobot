#!/usr/bin/env python3
"""
ask_nanogpt_llm_model - Query any LLM via NanoGPT API
Usage: ask_nanogpt_llm_model.py "model-name" "your question here"
"""

import os
import sys
import json
import requests

def load_api_key():
    """Load API key from ~/env.vars"""
    env_path = os.path.expanduser('~/env.vars')
    if not os.path.exists(env_path):
        print("Error: ~/env.vars not found", file=sys.stderr)
        sys.exit(1)
    
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('NANOGPT_API_KEY='):
                return line.split('=', 1)[1]
    
    print("Error: NANOGPT_API_KEY not found in env.vars", file=sys.stderr)
    sys.exit(1)

def ask_nanogpt(model, query, system_prompt=None):
    """Query any LLM via NanoGPT API"""
    api_key = load_api_key()
    base_url = "https://nano-gpt.com/api/v1"
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": query})
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload
    )
    
    if response.status_code != 200:
        print(f"Error: API returned {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)
    
    data = response.json()
    content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    print(content)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: ask_nanogpt_llm_model.py \"model-name\" \"your question\" [\"system prompt\"]", file=sys.stderr)
        sys.exit(1)
    
    model = sys.argv[1]
    query = sys.argv[2]
    system_prompt = sys.argv[3] if len(sys.argv) > 3 else None
    ask_nanogpt(model, query, system_prompt)
