---
description: End-of-session wrapup for Lore — capture new insights, rate all concepts (used and newly captured), and clear the session file. Use in persistent remote sessions where the Stop hook does not fire automatically.
---

# wrapup

Manually close out a Lore tracking session: capture any new insights first, then rate every concept (both retrieved-during-session and just-captured), and finally clear the session file.

## When to invoke

Invoke at the end of a work session when running `claude --remote` or any other persistent session where the Stop hook (`lore-stop.sh`) does not fire automatically. This skill is the manual equivalent of that hook.

Do not invoke mid-session — it clears the session file as its final step.

## Steps

### 1. Identify session concepts (Group A)

**If the session conversation is visible in your context** (benchmark runs, remote sessions with history): scan the visible turns for any `search_concepts` results or `submit_concept` calls — those concept IDs are your Group A list.

**If you are starting cold** (Stop hook, no session history visible): read `~/.lore/session.json`. Parse the array of concept IDs — these are your Group A list. If the file is missing, unreadable, or contains `[]`, Group A is empty.

There is no early exit. An empty Group A just means skip Group A rating in step 3; it does not mean the wrapup is done. **Always proceed to step 2.**

### 2. Reflection gate — capture new insights (agent-autonomous)

Do not ask the user. Work through these steps before rating anything:

**4a. Enumerate what was built or solved.**
List 3–6 concrete implementation areas from this session — specific decisions, errors encountered, APIs used, patterns applied. Do this before evaluating anything. A blank-slate "was anything non-obvious?" check will miss too much.

Examples of areas to enumerate: dependency wiring, error handling approach, data model decisions, API integration, test setup, packaging, configuration management, a specific error that required iteration.

**4b. Evaluate each area against the capture criteria.**
For each area from 4a, ask: does it meet at least one of these?
- Non-obvious workaround or gotcha
- Pattern derived from multiple failed attempts
- Domain-specific rule not in standard docs
- Technique with measurable time value

**4c. Capture qualifying areas.**
For each area that qualifies, invoke `/lore:capture-concept`. Let that skill handle generalization and submission. Record the `concept_id` returned by each `submit_concept` call — you will rate these in the next step. If nothing qualifies, move on silently.

### 3. Rate all concepts (agent-autonomous)

Rate every concept in two groups:

**Group A — concepts identified in step 1.**
These were retrieved from Lore and used during the session. Rate each on how useful it was:
- Did it directly enable a correct solution or save significant lookup time? → `outcome` 4–5
- Did it influence the approach taken but with limited or uncertain impact? → `outcome` 2–3
- Was it retrieved but not meaningfully used, or actively misleading? → `outcome` 1
- Did you follow this concept's approach and it produced wrong results or had to be abandoned? → `outcome` 1. An approach that fails is misleading regardless of how reasonable it seemed.

**Use run outcome as a signal, not a ceiling.** If the task failed, scrutinize whether this concept contributed to the failing approach. If it did, rate it 1. If the task succeeded but this concept was irrelevant, rate it 1 anyway.

**Group B — concepts captured in step 2.**
These are new insights you just submitted. Rate each on expected future value, not session usage:
- Clear, generalisable principle with high reuse potential → `outcome` 4–5
- Useful but narrow or situational → `outcome` 3
- Uncertain value; captured speculatively → `outcome` 2

Estimate `hours_saved` honestly for both groups — omit if zero or uncertain.

For each concept in both groups, call:

```
rate_concept(
  concept_id="<id>",
  outcome=<1-5>,
  hours_saved=<float>   ← omit if zero or uncertain
)
```

If `rate_concept` fails for a given concept (backend unreachable), note the failure silently and continue. Do not abort the loop.

### 4. Clear the session file

Only applies to the cold-start path (you read `~/.lore/session.json` in step 1). Write `[]` back to the file after all `rate_concept` calls have been attempted. Do not clear it early.

If the session history was visible in your context (step 1 context path), the benchmark harness clears the file — skip this step.

### 5. Confirm completion

Tell the user:

> "Session wrapped up. Rated N concept(s)."

Where N is the total count of `rate_concept` calls across both groups (regardless of whether individual calls succeeded).
