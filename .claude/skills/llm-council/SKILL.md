---
name: llm-council
description: RedLine LLM integration patterns — model profile resolution, LLMRateLimiter.acquire() usage, daily vs per-minute quota debugging, adding new model profiles, and the LLM judge scorer design.
---

# RedLine LLM Integration Patterns

Use this skill when:
- Calling a Gemini API from an agent or scorer
- Debugging 429 Resource Exhausted errors
- Adding a new model or provider
- Understanding why the LLM judge uses a different model than the agent under test
- Configuring rate limits for a new profile

---

## Pattern 1: Model Profile Resolution

**Never hardcode model names.** All model resolution goes through `get_profile()`.

```python
# apps/api/core/model_profiles.py
from apps.api.core.model_profiles import get_profile, ModelProfile

# In any agent or scorer
profile: ModelProfile = get_profile("standard")
# profile.model_name → "gemini-2.0-flash"
# profile.provider   → "google"
# profile.rpm        → 15
```

**`config/model_profiles.yaml` — the source of truth:**

```yaml
profiles:
  standard:
    model_name: gemini-2.0-flash
    provider: google
    rpm: 15

  high_reasoning:
    model_name: gemini-2.5-flash
    provider: google
    rpm: 10

  cheap:
    model_name: gemini-2.0-flash-lite
    provider: google
    rpm: 30
```

**To add a new profile:** Edit `config/model_profiles.yaml` only. No Python changes needed if `get_profile()` is already used everywhere.

**`ModelProfile` dataclass:**

```python
@dataclass
class ModelProfile:
    model_name: str
    provider: str
    rpm: int
```

---

## Pattern 2: LLMRateLimiter — Call Before Every LLM API Call

**Every Gemini API call must be preceded by `rate_limiter.acquire()`.**

```python
# In any agent's run_turn() function
from apps.api.core.llm_rate_limiter import LLMRateLimiter
from apps.api.core.model_profiles import get_profile
import google.generativeai as genai

# Initialize once (per agent instance or at module level)
profile = get_profile("standard")
rate_limiter = LLMRateLimiter(rpm=profile.rpm)
model = genai.GenerativeModel(profile.model_name)

def run_turn(session_state: dict, user_message: str):
    # REQUIRED: acquire a rate limit slot before calling Gemini
    rate_limiter.acquire()  # blocks (sleeps) if at RPM limit
    
    response = model.generate_content(...)
    ...
```

**What `acquire()` does:**

```python
def acquire(self):
    now = time.time()
    window = 60.0
    # Remove timestamps older than 60 seconds
    while self._requests and self._requests[0] < now - window:
        self._requests.popleft()
    # If at RPM limit, sleep until oldest request falls out of window
    if len(self._requests) >= self._rpm:
        sleep_time = self._requests[0] + window - now
        time.sleep(max(0, sleep_time))
    self._requests.append(time.time())
```

**Important:** In Phase 2, one `LLMRateLimiter` instance per worker process. Not shared across processes. Phase 3 replaces with Redis-backed coordination.

---

## Pattern 3: Diagnosing 429 Errors

**Both daily quota and per-minute quota return HTTP 429.** They are distinguished by `quotaId` in the error detail.

### Per-minute quota exceeded:

```json
{
  "error": {
    "code": 429,
    "status": "RESOURCE_EXHAUSTED",
    "message": "Quota exceeded for quota metric 'generate_requests_per_minute'",
    "details": [{"quotaId": "GenerateRequestsPerMinutePerProject"}]
  }
}
```

**Cause:** `rate_limiter.acquire()` was not called, or the RPM in `model_profiles.yaml` is set higher than your actual quota.

**Fix:** Verify `acquire()` is called before every `generate_content()`. Lower the `rpm` value in the profile if needed.

### Daily quota exceeded:

```json
{
  "error": {
    "code": 429,
    "status": "RESOURCE_EXHAUSTED", 
    "message": "Quota exceeded for quota metric 'generate_requests_per_day'",
    "details": [{"quotaId": "GenerateRequestsPerDayPerProject"}]
  }
}
```

**Cause:** Free-tier daily quota consumed. Cannot be worked around with rate limiting.

**Fix options:**
1. Wait for midnight PST quota reset
2. Use `REDLINE_TEST_MODEL=gemini-2.0-flash-lite` for tests (higher daily quota)
3. Upgrade to a paid Gemini tier

**Identifying daily vs per-minute in code:**

```python
except google.api_core.exceptions.ResourceExhausted as e:
    error_str = str(e)
    if "per_day" in error_str.lower() or "PerDay" in error_str:
        logger.error("Daily quota exhausted — cannot retry today")
        raise  # No point retrying
    else:
        logger.warning("Per-minute quota hit — rate limiter should have caught this")
        time.sleep(60)
        # Retry
```

---

## Pattern 4: The LLM Judge Scorer

The `LLMJudgeScorer` (`apps/api/services/scorers/llm_judge.py`) uses the **`high_reasoning` profile** (`gemini-2.5-flash`) regardless of which model the agent under test uses.

**Why:**
- The judge needs to be more capable than the agent to accurately assess it
- Using `gemini-2.5-flash` (Flash Thinking) gives the judge reasoning ability
- The agent being tested might use `gemini-2.0-flash` (cheaper) — they should not share quota

**Judge prompt structure:**

```python
JUDGE_PROMPT = """You are evaluating an AI agent's response quality.

Rubric: {rubric}

Agent conversation transcript:
{transcript}

Based only on the rubric, did the agent succeed?
Respond with valid JSON only:
{{"passed": true/false, "reasoning": "one sentence explaining why"}}"""
```

**The judge extracts structured output:**

```python
response = model.generate_content(prompt)
result = json.loads(response.text)
return ScorerResult(passed=result["passed"], detail=result["reasoning"])
```

**If the judge response is malformed JSON:**

```python
except (json.JSONDecodeError, KeyError) as e:
    # Fail safe — a malformed judge response is treated as a failure
    return ScorerResult(passed=False, detail=f"Judge response parse error: {e}")
```

---

## Pattern 5: Adding a New Model Profile

1. Edit `config/model_profiles.yaml`:

```yaml
profiles:
  # ... existing profiles ...
  
  ultra_cheap:
    model_name: gemini-2.0-flash-lite
    provider: google
    rpm: 30
```

2. No Python code changes needed — `get_profile("ultra_cheap")` will work immediately.

3. Use in eval suites by setting `model_profile: ultra_cheap` in the agent version's YAML or CLI registration.

4. To add a non-Google provider (future):

```yaml
profiles:
  anthropic_standard:
    model_name: claude-3-5-haiku-20241022
    provider: anthropic
    rpm: 60
```

Then update the agent code to branch on `profile.provider`:

```python
profile = get_profile("anthropic_standard")
if profile.provider == "google":
    import google.generativeai as genai
    model = genai.GenerativeModel(profile.model_name)
elif profile.provider == "anthropic":
    import anthropic
    client = anthropic.Anthropic()
    # ... different call pattern
```

---

## Common Mistakes

1. **Not calling `acquire()` before `generate_content()`** — you'll hit 429 under any load
2. **Hardcoding `"gemini-2.5-flash"`** — breaks when model is remapped in profile config
3. **Sharing one `LLMRateLimiter` across all profiles** — each profile has a different RPM; create one limiter per profile
4. **Treating all 429s the same** — daily quota requires waiting, per-minute quota requires slowing down
5. **Using the same profile for the judge and the agent** — judge should always use `high_reasoning`
