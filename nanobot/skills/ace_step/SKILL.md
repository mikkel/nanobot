# ace_step — AI Music Generation

Generate songs using ACE-Step 1.5 running on the desktop GPU.

**Base URL:** `http://192.168.0.181:8000`

---

## Quick Reference (Copy-Paste Ready)

### 1. Check if server is up

```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 "curl -s http://localhost:8000/health"
```

Expected: `{"status":"ok",...}`

### 2. Submit a song generation job

```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 'curl -s -X POST http://localhost:8000/release_task \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"upbeat indie rock, male vocals, energetic drums, bright guitar\",
    \"lyrics\": \"[verse]\\nWoke up this morning feeling alive\\nThe sun is shining and I will thrive\\n[chorus]\\nThis is our moment, this is our time\\nEverything is working out just fine\",
    \"audio_duration\": 60,
    \"thinking\": true
  }"'
```

Response looks like:
```json
{
  "data": {
    "task_id": "f8401a4a-aa8c-458b-9be9-6799f914364f",
    "status": "queued",
    "queue_position": 1
  },
  "code": 200,
  "error": null
}
```

**Save the `task_id` — you need it to get results.**

### 3. Poll for results

⚠️ **IMPORTANT**: The field name is `task_id_list` (NOT `task_ids`).

```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 'curl -s -X POST http://localhost:8000/query_result \
  -H "Content-Type: application/json" \
  -d "{\"task_id_list\": [\"TASK_ID_HERE\"]}"'
```

**Poll every 5 seconds.** Generation typically takes 30-120 seconds depending on duration.

Response when done:
```json
{
  "data": [
    {
      "job_id": "...",
      "status": "succeeded",
      "result": {
        "audio_paths": [
          "/v1/audio?path=/ml2/nanobot/ACE-Step-1.5/.cache/acestep/tmp/api_audio/XXXXX.mp3"
        ]
      }
    }
  ]
}
```

When still processing: `"status": "running"` or `"status": "queued"`

### 4. Get the audio file

The `audio_paths` in the result are relative URLs. Access them at:

```
http://192.168.0.181:8000/v1/audio?path=/ml2/nanobot/ACE-Step-1.5/.cache/acestep/tmp/api_audio/XXXXX.mp3
```

Or download via SSH:
```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 "ls -lt /ml2/nanobot/ACE-Step-1.5/.cache/acestep/tmp/api_audio/ | head -5"
```

### 5. List all generated songs

```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 "ls -lt /ml2/nanobot/ACE-Step-1.5/.cache/acestep/tmp/api_audio/"
```

---

## Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | "" | Music style/description (e.g., "indie rock, female vocals, acoustic guitar") |
| `lyrics` | string | "" | Song lyrics with `[verse]`, `[chorus]`, `[bridge]` tags |
| `audio_duration` | float | 30 | Duration in seconds (e.g., 30, 60, 120) |
| `thinking` | bool | false | Use LM for audio code generation (better quality, slower) |
| `vocal_language` | string | "en" | Language code: en, zh, ja, ko, es, fr, de, etc. |
| `bpm` | int | auto | Beats per minute |
| `key_scale` | string | auto | Musical key (e.g., "C major", "A minor") |
| `time_signature` | string | auto | Time signature (e.g., "4/4", "3/4") |
| `inference_steps` | int | 8 | More steps = better quality but slower |
| `guidance_scale` | float | 7.0 | How closely to follow the prompt (higher = more faithful) |
| `seed` | int | -1 | Random seed (-1 = random) |
| `batch_size` | int | 1 | Number of variations to generate |
| `audio_format` | string | "mp3" | Output format: mp3, wav, flac, ogg |

---

## API Endpoints Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/release_task` | Submit a music generation job |
| POST | `/query_result` | Poll job status (body: `{"task_id_list": ["id"]}`) |
| GET | `/health` | Check if server is alive |
| GET | `/v1/audio?path=...` | Download/stream generated audio |
| GET | `/v1/models` | List available models |
| GET | `/v1/stats` | Server statistics |
| POST | `/create_random_sample` | Get random example parameters |
| POST | `/format_input` | Use LLM to enhance lyrics/caption |
| GET | `/docs` | Swagger UI (interactive API docs) |

---

## If the Server is Down

SSH to the desktop and start it:

```bash
ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181
cd /ml2/nanobot/ACE-Step-1.5
source ~/env.vars && export HUGGINGFACE_TOKEN
python -m uvicorn acestep.api_server:app --host 0.0.0.0 --port 8000 --workers 1
```

Verify:
```bash
curl -s http://192.168.0.181:8000/health
```

**Note:** First startup downloads model weights (~5-10 GB) and takes several minutes. Subsequent starts are fast.

---

## Common Mistakes

1. ❌ `{"task_ids": [...]}` → ✅ `{"task_id_list": [...]}`  — Wrong field name kills polling
2. ❌ Polling too fast — Give it 5 seconds between polls, generation takes 30-120s
3. ❌ Forgetting `thinking: true` — Without it, quality is lower (skips LM step)
4. ❌ Looking for a web UI — There is no built-in web UI. Use `/docs` for Swagger or call the API directly.
5. ❌ Audio paths are full filesystem paths — Use them with `/v1/audio?path=<FULL_PATH>`

---

## Audio File Location on Disk

All generated MP3s are saved to:
```
/ml2/nanobot/ACE-Step-1.5/.cache/acestep/tmp/api_audio/
```

Files persist across server restarts. The in-memory job store does NOT persist — if the server restarts, old task IDs won't resolve, but the audio files are still on disk.

---

## Crafting Great Prompts (IMPORTANT — Read This)

The `prompt` field describes the **sound/style** (not the lyrics). The `lyrics` field is the **words sung**. Both must be exceptional to get a great result.

### Prompt (Style) Guidelines

**Be specific about genre + subgenre + mood + instrumentation + vocal style:**
- ❌ Bad: `"rock song"`
- ✅ Good: `"dark alternative rock, brooding female vocals, distorted guitars, heavy bass, atmospheric reverb, 90s grunge influence, emotional intensity"`

**Reference the sonic palette, not artist names** (the model doesn't know artists):
- ❌ Bad: `"sounds like Halsey"`
- ✅ Good: `"dark electropop, breathy vulnerable female vocals, glitchy synths, trap-influenced drums, cinematic production, emotional rawness"`

**Stack descriptors — more detail = better results:**
- Mood: haunting, euphoric, melancholic, aggressive, dreamy, raw, intimate
- Texture: atmospheric, lo-fi, polished, gritty, lush, sparse, layered
- Vocals: breathy, powerful, raspy, ethereal, spoken-word, falsetto, raw
- Production: reverb-heavy, compressed, analog warmth, digital glitch, cinematic
- **Hook (ALWAYS INCLUDE):** describe how the song opens — what grabs the listener in the first 10 seconds

### User's Taste Profile (Mikkel's Influences)

Build prompts that channel these artists' sonic DNA:

| Artist | Sonic DNA for Prompts |
|--------|----------------------|
| **The XX** | minimal indie, intimate whispered vocals, sparse guitar, deep bass, atmospheric space, nocturnal mood, tender and melancholic |
| **Halsey** | dark electropop, raw vulnerable female vocals, trap-influenced beats, cinematic production, confessional lyrics, emotional intensity |
| **Aaliyah** | silky smooth R&B, ethereal female vocals, understated production, cool rhythmic grooves, sensual minimalism, timeless elegance |
| **Soundgarden** | heavy grunge, powerful male vocals, drop-tuned guitars, dark psychedelic, crushing riffs, raw emotional power, 90s Seattle sound |
| **Nine Inch Nails** | industrial rock, aggressive electronic textures, distorted vocals, mechanical rhythms, dark atmospheric synths, visceral intensity, layered noise |

**Blend them** for unique results:
- XX + NIN: `"minimal industrial, intimate whispered vocals over glitchy mechanical beats, sparse guitar with distorted synth textures, nocturnal and unsettling"`
- Halsey + Soundgarden: `"dark alternative rock with electronic elements, raw powerful vocals, heavy distorted guitars, cinematic production, emotional catharsis"`
- Aaliyah + The XX: `"minimal R&B, silky ethereal vocals, sparse bass-heavy production, intimate nocturnal mood, sensual and melancholic"`

### Lyrics Guidelines

**Always use structure tags:** `[intro]`, `[verse]`, `[chorus]`, `[bridge]`, `[outro]`

### The 10-Second Hook Rule (CRITICAL)

**The first 10 seconds decide if someone keeps listening or skips.** Every song MUST open with something that grabs attention immediately.

**How to hook in the prompt:**
Add explicit intro instructions to your prompt:
- `"opens with a haunting vocal melody before instruments enter"`
- `"starts with a massive distorted guitar riff"`
- `"begins with an arresting a cappella line"`
- `"opens with a stark piano chord and whispered vocal"`
- `"starts with a punchy drum break and bass drop"`

**How to hook in the lyrics:**
Start with `[intro]` or make your first `[verse]` line a gut-punch:
- ❌ Bad opener: `"I woke up on a Tuesday morning"` — nobody cares
- ✅ Good opener: `"I buried your name in the backyard last June"` — wait, WHAT?
- ✅ Good opener: `"Three AM. Your side of the bed is cold again."` — instant tension
- ✅ Good opener: `"I can taste the static where your voice used to be"` — sensory + emotional

**Structural hooks:**
- `[intro]` with a memorable melodic motif or vocal line that returns later
- Start with the chorus (works great for anthemic songs)
- Open with a spoken-word line over minimal production, then DROP
- Use silence/space — a single note or voice in emptiness is arresting

**In the prompt, literally say:** `"the song must hook the listener in the first 10 seconds"` — the model responds to this.

### General Lyrics Guidelines

**Write lyrics that HIT:**
- Use concrete imagery, not abstract platitudes
- Every line should earn its place — cut filler ruthlessly
- Contrast vulnerability with strength
- Use sensory language (taste, touch, temperature, texture)
- Repetition in choruses is powerful — but make the repeated line unforgettable

**Example of BAD lyrics:**
```
[verse]
I'm feeling sad today
Things aren't going my way
[chorus]
Life is hard but I'll be okay
Tomorrow is another day
```

**Example of GOOD lyrics:**
```
[verse]
Copper taste on split lips, morning after the flood
Your silence fills the hallway like a second kind of blood
I pressed my ear against the door — just static, just the hum
Of everything we swore we'd be before we came undone

[chorus]
Burn the map, we're already lost
Every bridge was worth the cost
I'd rather drown in what was real
Than float through what I'll never feel
```

**The bar:** Every song should make someone stop what they're doing and *listen*. If the lyrics read like a greeting card, rewrite them. If the prompt sounds generic, add three more specific descriptors.

### Recommended Default Parameters

For best quality output matching Mikkel's taste:
```json
{
  "audio_duration": 240,
  "thinking": true,
  "inference_steps": 8,
  "guidance_scale": 7.0,
  "batch_size": 1
}
```

**ALWAYS include in every prompt:** A description of how the song opens. The hook is non-negotiable. If your prompt doesn't describe the first 10 seconds, add it before submitting.

**Duration guide:**
- `60` — quick test / demo
- `120` — short song (verse-chorus-verse)
- `240` — full song (4 minutes — **recommended default**)
- `360-600` — extended / epic tracks

**GPU tier limits (RTX A6000 = 48GB = tier7):**
- With `thinking: true` (LM): up to **600s (10 min)**
- Without LM: up to **600s (10 min)**

Tier reference: ≤4GB=180s, 4-6GB=360s, 6-16GB=240s w/LM, 16-24GB=480s, 24GB+=600s

---

## LLM-Powered Song Pipeline (Recommended Workflow)

For best results, use a frontier LLM to write the lyrics and refine the prompt BEFORE submitting to ACE-Step.

### Which LLM to use for lyrics

Use the `ask_nanogpt_llm_model` skill. **Only use current-gen frontier models:**

| Model | Use For |
|-------|---------|
| `anthropic/claude-opus-4.6` | **Best for lyrics** — poetic, concrete, emotionally devastating |
| `openai/gpt-5.2` | Strong alternative — good structure and imagery |
| `x-ai/grok-4-07-09` | Creative + edgy, good for darker themes |
| `gemini-2.5-pro` | Solid all-rounder |

**⚠️ Use current-gen models for lyrics.** See `ask_nanogpt_llm_model/SKILL.md` for full guidelines — avoid truly obsolete models (GPT-3.5, Llama 2 era, etc.) but don't be overly restrictive. GLM derestricted, community finetunes, and creative models are all fair game.

### System prompt for the lyrics LLM

Use this system prompt (or similar) when asking an LLM to write a song:

```
You are an elite songwriter who writes for artists like The XX, Halsey, Aaliyah, Soundgarden, and Nine Inch Nails. Your lyrics are:
- Concrete and sensory (taste, touch, temperature, texture) — never abstract platitudes
- Emotionally devastating — every line earns its place
- Structured with tags: [intro], [verse], [chorus], [bridge], [outro]
- The FIRST LINE must be a gut-punch that stops someone mid-scroll

You also provide a detailed music production prompt describing:
- Genre, subgenre, mood, instrumentation, vocal style, production style
- How the song OPENS (the first 10 seconds must hook the listener)
- Dynamic changes throughout the song
- Do NOT reference artist names — describe the sound instead

Output format:
PROMPT: <detailed style/production description>
LYRICS:
<structured lyrics with tags>
```

### Full pipeline example

```bash
# Step 1: Ask Claude Opus 4.6 to write the song
python3 ask_nanogpt_llm_model.py "anthropic/claude-opus-4.6" \
  "Write a dark trip-hop song about insomnia from the perspective of someone who hasn't slept in 3 days" \
  "You are an elite songwriter..."

# Step 2: Parse the PROMPT and LYRICS from the response

# Step 3: Submit to ACE-Step with audio_duration=240, thinking=true
```

---

## End-to-End Example

```bash
# 1. Submit
RESPONSE=$(ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 'curl -s -X POST http://localhost:8000/release_task \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"lo-fi hip hop, chill beats, rainy day vibes\",\"lyrics\":\"[verse]\\nRaindrops on the window pane\\nSoft beats washing away the pain\",\"audio_duration\":60,\"thinking\":true}"')

TASK_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['task_id'])")
echo "Task ID: $TASK_ID"

# 2. Poll until done
while true; do
  RESULT=$(ssh -i ~/.ssh/id_ed25519 nanobot@192.168.0.181 "curl -s -X POST http://localhost:8000/query_result \
    -H 'Content-Type: application/json' \
    -d '{\"task_id_list\": [\"$TASK_ID\"]}'")
  STATUS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['status'])" 2>/dev/null)
  echo "Status: $STATUS"
  if [ "$STATUS" = "succeeded" ] || [ "$STATUS" = "failed" ]; then
    echo "$RESULT" | python3 -m json.tool
    break
  fi
  sleep 5
done
```
