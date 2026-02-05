# ask_nanogpt_llm_model

Query any LLM model available through the NanoGPT API.

## Setup

Your API key is stored in `~/env.vars` as `NANOGPT_API_KEY`.

## Usage

```bash
ask_nanogpt_llm_model.py "model-name" "your question here"
# With system prompt:
ask_nanogpt_llm_model.py "model-name" "your question" "system prompt"
```

## Implementation

Uses the NanoGPT OpenAI-compatible endpoint at `https://nano-gpt.com/api/v1/chat/completions`.

## Files

- `ask_nanogpt_llm_model.py` - Main Python script
- `SKILL.md` - This documentation

---

## Model Selection Policy

NanoGPT has **hundreds of models**. The catalog changes constantly. **Never hardcode model IDs.** Follow these rules:

### The Rule: Only Use the Latest Generation

For every provider, use **only the newest generation available**. If a newer version exists, the older one is dead to you.

**How to decide:**
1. List available models (see command below)
2. For each provider, find the **highest version number**
3. Use that. Skip everything older.

**Examples of the principle (not a fixed list — these will change):**
- If GPT-5.2 exists → skip GPT-5.1, GPT-5, and everything before
- If Gemini 3 exists → skip Gemini 2.5
- If Grok 4.1 exists → skip Grok 4, Grok 3
- If GLM 4.7 exists → skip GLM 4.5, 4.0 (but keep derestricted/community variants of recent gens)
- If DeepSeek V3.2 exists → skip V3.1, V3
- If Kimi K2.5 exists → skip K2
- If Qwen3 exists → skip Qwen 2.5
- If ERNIE 5.0 exists → skip ERNIE 4.5
- If o4 exists → skip o3, o1

**The test:** Would you recommend this model to someone today, or would you say "just use the newer one"? If the latter, skip it.

### Always Welcome

- **GLM derestricted variants** — creative, uncensored, great for lyrics and fiction. Always use these.
- **Community finetunes & creative merges** — `arcee-ai/trinity-*`, interesting creative models. Fair game.
- **Research/search models** — `exa-research-pro`, `sonar-deep-research`, `sonar-reasoning-pro`. These serve a unique purpose.

### Always Skip

- Anything **2+ generations behind** (e.g., GPT-4 when GPT-5 exists, Llama 3 when Llama 5 exists)
- **Tiny old models** — 7B/13B models from previous years with no unique value
- **Discontinued providers** — yi-*, old Azure wrappers
- **"Preview" or "turbo" variants** when a stable full release of a newer gen exists

### When In Doubt

**Check the catalog, pick the newest, try it.** Better to use a model and get good output than refuse because you're unsure.

---

## Listing Available Models

**Always run this first if you're unsure what's current:**

```bash
source ~/env.vars && curl -s https://nano-gpt.com/api/v1/models \
  -H "Authorization: Bearer $NANOGPT_API_KEY" | \
  python3 -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data']]"
```

Sort by provider, find the highest version numbers, use those.

---

## Quick Decision Guide

| Task | What to pick |
|------|-------------|
| **Song lyrics / creative writing** | Best available Claude, GPT, Grok, or GLM derestricted |
| **Complex reasoning** | Best available thinking/reasoning model (Claude thinking, DeepSeek R1, etc.) |
| **Quick question** | Smallest current-gen model (Haiku, Flash, Mini variants) |
| **Code** | Best available coder model (Qwen coder, Codestral, GPT codex) |
| **Web research** | `exa-research-pro`, `sonar-deep-research` |
| **Uncensored/creative fiction** | GLM derestricted variants, community finetunes |

---

## Example

```bash
# Creative — use the best current-gen model
ask_nanogpt_llm_model.py "anthropic/claude-opus-4.6" "Write lyrics for a dark trip-hop song"

# GLM derestricted for creative fiction
ask_nanogpt_llm_model.py "GLM-4.6-Derestricted-v5" "Write a gritty noir scene"

# Research
ask_nanogpt_llm_model.py "exa-research-pro" "Latest developments in AI music generation"
```

*Note: The model IDs in these examples may be outdated. Always check the catalog for the latest.*
