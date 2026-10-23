# Relay

A Slack support agent for an internal data platform team. Ask it a question in
a channel; it calls tools to find the answer, replies in-thread with the
evidence, and logs what it did so the team can see whether it is actually
helping.

```
Slack message
   │
   ├─ signature check (HMAC, 5-minute replay window)
   ├─ ack within 3s, work moves to the background
   │
   ▼
agent loop ──► tool? ──► runbook search (BM25)
   │  ▲                  incident lookup
   │  └── result ────────  platform metrics
   ▼
answer ──► Slack thread
       └─► SQLite request log ──► /  (dashboard)
       └─► Langfuse trace
```

---

## Why it is built this way

**The loop is bounded.** `MAX_TOOL_ITERATIONS` caps tool round trips. A model
that keeps asking for the same tool is a real failure mode, not a hypothetical
one, and an unbounded loop bills forever and never answers. When the cap is
hit, Relay makes one more call with the tools withheld so the model has to
answer in prose from what it already gathered — the user gets a partial answer
instead of nothing.

**Tool errors go back to the model, not up the stack.** A bad argument or an
unknown service returns a string starting `Error:` that the model reads on its
next turn, and it usually corrects itself. Raising would turn one confused tool
call into a failed request.

**The data source lives behind the tool.** `get_platform_metrics` reads a JSON
snapshot today; pointing it at Prometheus changes that one function and nothing
the model sees. That is the whole reason to put a tool boundary there.

**Measurement does not depend on the tracing vendor.** Every request writes a
row to SQLite, and the dashboard reads only from there. Langfuse adds the
per-call detail — which tool ran, with what arguments, returning what — but if
tracing is off or the account lapses, the operational numbers survive.

**Deflection rate is the number that matters.** Of the questions people asked,
how many did Relay answer from tool evidence without pointing at the on-call
engineer. Request volume alone says nothing about whether the thing is useful.

---

## Running it

Nothing external is required to run the whole path. With no API key at all:

```bash
pip install -r requirements.txt
LLM_PROVIDER=demo python -m scripts.seed     # populate the request log
LLM_PROVIDER=demo uvicorn app.main:app --reload
```

Then open <http://localhost:8000> for the dashboard and
<http://localhost:8000/docs> for the API.

Ask it something without Slack:

```bash
curl -s localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question":"why is spark slow today"}' | python -m json.tool
```

`LLM_PROVIDER=demo` routes to a keyword-based stand-in rather than a model, so
the agent loop, the tools, the store and the dashboard all exercise their real
code paths offline. For actual reasoning, set a real provider.

### With a real model

```bash
cp .env.example .env
# set LLM_PROVIDER=groq and GROQ_API_KEY=...
uvicorn app.main:app --reload
```

Groq, OpenAI and Anthropic are all supported; `app/llm.py` normalises their
tool-call formats to one shape so the agent does not care which is in use.

### With Slack

1. Create an app at api.slack.com/apps.
2. **OAuth & Permissions** → add `chat:write` and `app_mentions:read`, install
   to the workspace, copy the Bot User OAuth Token into `SLACK_BOT_TOKEN`.
3. **Basic Information** → copy the Signing Secret into `SLACK_SIGNING_SECRET`.
4. **Event Subscriptions** → point the request URL at
   `https://<your-host>/slack/events` and subscribe to `app_mention`.
5. Invite the bot to a channel and mention it.

For local development, expose port 8000 with any tunnel (`ngrok http 8000`)
and use that URL in step 4.

### With tracing

Create a free project at cloud.langfuse.com, put the public and secret keys in
`.env`, restart. Each question becomes one trace with a child span per tool
call carrying its arguments and output. With the keys unset, `NullTracer` is
used and nothing changes about how the app behaves.

---

## Tests

```bash
python -m pytest -q
```

46 tests, no network, no API key. The ones worth reading are in
`tests/test_agent.py` — they cover what the loop does when the model
misbehaves, which is the part that is hard to get right:

| Test | Behaviour pinned |
|---|---|
| `test_iteration_cap_stops_a_model_that_will_not_stop_calling_tools` | Cap fires, forced-answer turn produces a usable partial |
| `test_bad_tool_name_is_returned_to_the_model_rather_than_raised` | Model mistakes are recoverable, not fatal |
| `test_provider_exception_is_contained_and_reported` | A dead LLM endpoint degrades to an escalation, not a 500 |
| `test_empty_model_response_falls_back_to_a_usable_message` | Never reply with an empty string |

`tests/test_slack.py` tests signature verification against forged, stale,
wrong-secret and tampered-body requests, because that endpoint is the security
boundary of the service.

---

## Layout

```
app/
  main.py        FastAPI: /slack/events, /ask, /health, / (dashboard)
  agent.py       the bounded tool-calling loop
  llm.py         provider adapters (Groq / OpenAI / Anthropic / demo / fake)
  tools/
    registry.py  tool registration + dispatch
    runbooks.py  BM25 search over the runbook corpus
    incidents.py incident lookup by service and status
    metrics.py   platform health snapshot, flags SLO breaches
  retrieval.py   BM25 implementation
  slack.py       signature verification, event filtering, posting
  store.py       SQLite request log
  dashboard.py   Plotly charts + the HTML page
  tracing.py     Langfuse wrapper with a no-op fallback
data/
  runbooks/*.md  the corpus
  incidents.json
  metrics.json
scripts/seed.py  populate the log through the real agent path
```

## Adding a tool

One decorator; the loop does not change.

```python
from app.tools.registry import registry

@registry.register(
    name="get_quota",
    description="Current quota usage for a team. Use when a user asks whether "
                "they are near a limit.",
    parameters={
        "type": "object",
        "properties": {"team": {"type": "string"}},
        "required": ["team"],
    },
)
def get_quota(team: str) -> str:
    ...
```

The description is the prompt. It is what decides whether the model reaches
for this tool at the right moment, so it is worth more care than the code.

## Known limits

- The runbook corpus is five documents. BM25 is the right call at that size;
  past a few hundred it wants a dense retriever alongside it.
- `_seen_events` de-duplicates Slack retries in memory, so it resets on deploy
  and does not work across replicas. Redis would be the fix for more than one
  instance.
- Metrics and incidents are local snapshots, not live queries.
- There is no feedback capture. A thumbs-up/down reaction handler writing back
  to the request log would make the deflection rate something you could trust
  rather than infer from the answer text.
