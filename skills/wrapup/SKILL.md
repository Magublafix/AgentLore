---
description: End-of-session wrapup for Lore — rate tracked concepts, capture new insights, and clear the session file. Use in persistent remote sessions where the Stop hook does not fire automatically.
---

# wrapup

Manually close out a Lore tracking session: resolve and rate every concept used, capture any new insights, then clear the session file.

## When to invoke

Invoke at the end of a work session when running `claude --remote` or any other persistent session where the Stop hook (`lore-stop.sh`) does not fire automatically. This skill is the manual equivalent of that hook.

Do not invoke mid-session — it clears the session file as its final step.

## Steps

### 1. Read the session file

Read `~/.lore/session.json`.

- If the file does not exist, tell the user: "No concepts tracked this session." and stop.
- If the file exists but contains an empty array (`[]`), tell the user: "No concepts tracked this session." and stop.
- If the file is not valid JSON, treat it as empty: tell the user "Session file was corrupted — nothing to rate." and stop.

### 2. Resolve concept names

For each concept ID in the session array, call:

```
get_concept(concept_id="<uuid>")
```

This returns a record with fields: `concept_id`, `name`, `type`, `content`, `avg_rating`, `usage_count`.

Collect the name and type for each concept so you can present a readable list to the user.

If the MCP backend is unreachable or returns an error for a given ID, fall back to displaying the raw concept ID for that entry. Do not abort the wrapup — continue with whatever names resolved successfully.

### 3. Present the concept list

Display the full list of concepts used this session, one per line, in this format:

```
1. <name> (<type>) — ID: <concept_id>
2. <name> (<type>) — ID: <concept_id>
...
```

For any concept whose name could not be resolved, show:

```
N. <concept_id> (unresolved)
```

### 4. Rate each concept (agent-autonomous)

Do not prompt the user for ratings. You assess and submit each rating yourself based on your recollection of the session.

Rate each concept on its **own merits** — how useful *this concept* was, independent of whether the overall task succeeded or failed. A concept can be rated 5 on a failed run if it was genuinely the right guidance; it can be rated 0 on a passing run if the approach it recommended was abandoned.

For each concept, reflect:
- Did it directly enable a correct solution or save significant lookup time? → `outcome` 4–5
- Did it influence the approach taken but with limited or uncertain impact? → `outcome` 2–3
- Was it retrieved but not meaningfully used, or actively misleading? → `outcome` 1

**Use run outcome as a signal, not a ceiling.** If the task failed, scrutinize whether this concept contributed to the failing approach. If it did, rate it 0–1. If the task succeeded but this concept was irrelevant, rate it 0–1 anyway.

Estimate `hours_saved` honestly — omit if zero or uncertain.

Then call:

```
rate_concept(
  concept_id="<id>",
  outcome=<1-5>,
  hours_saved=<float>   ← omit if zero or uncertain
)
```

If `rate_concept` fails for a given concept (backend unreachable), note the failure silently and continue. Do not abort the loop.

### 5. Reflection gate (agent-autonomous)

Do not ask the user. Work through these steps:

**5a. Enumerate what was built or solved.**
List 3–6 concrete implementation areas from this session — specific decisions, errors encountered, APIs used, patterns applied. Do this before evaluating anything. A blank-slate "was anything non-obvious?" check will miss too much.

Examples of areas to enumerate: dependency wiring, error handling approach, data model decisions, API integration, test setup, packaging, configuration management, a specific error that required iteration.

**5b. Evaluate each area against the capture criteria.**
For each area from 5a, ask: does it meet at least one of these?
- Non-obvious workaround or gotcha
- Pattern derived from multiple failed attempts
- Domain-specific rule not in standard docs
- Technique with measurable time value

**5c. Capture qualifying areas.**
For each area that qualifies, invoke `/lore:capture-concept`. Let that skill handle generalization and submission. If nothing qualifies, move on silently.

### 6. Clear the session file

Write `[]` back to `~/.lore/session.json`, overwriting whatever was there.

Only do this after all `rate_concept` calls have been attempted (success or failure). Do not clear the file early.

### 7. Confirm completion

Tell the user:

> "Session wrapped up. Rated N concept(s)."

Where N is the count of concepts for which `rate_concept` was called (regardless of whether individual calls succeeded).
