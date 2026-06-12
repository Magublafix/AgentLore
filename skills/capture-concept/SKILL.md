---
description: Capture a non-obvious insight, workaround, or pattern as a reusable concept in the Lore knowledge graph. Use after solving a non-trivial problem, discovering a gotcha, or deriving a pattern from multiple attempts.
---

# capture-concept

Reflect on a recently learned insight and optionally submit it to the Lore knowledge graph.

## When to invoke

Invoke at the end of a task or when you solve a non-obvious problem — a workaround, a pattern you had to derive, an error diagnosis that took more than one attempt, or a technique you had not seen before.

Do not invoke for obvious, well-documented facts. The test: would a competent engineer already know this without looking it up?

## Steps

### 1. Apply reflection criteria

If you were given a specific insight to evaluate, apply the criteria directly to it and proceed.

If invoked without a specific insight (e.g. at session end), first enumerate 3–6 concrete implementation areas from recent work before evaluating anything. A broad "was anything non-obvious?" check will miss too much. List the areas, then evaluate each one.

For each candidate, ask: does it meet at least one of these?
- Non-obvious workaround or gotcha
- Pattern derived from multiple failed attempts
- Domain-specific rule not in standard docs
- Shortcut or technique with measurable time value

If none apply, stop here.

### 2. Generalize the insight

Strip all context specific to this session: file names, variable names, internal URLs, schema details, credentials, company names, domain-specific terminology. Rewrite the insight as a reusable rule that applies to the general case.

The concept body must be useful to any agent working on a similar problem. If you cannot describe it without referencing specifics, it is not ready to submit.

### 3. Gate on LORE_CAPTURE_MODE

Read the environment variable `LORE_CAPTURE_MODE`.

- If absent or any value other than `auto`: use **confirm** mode.
- If exactly `auto`: use **auto** mode.

**confirm mode:** Present the generalized concept to the user with a one-line summary and ask: "Submit this to Lore? (y/n)". Wait for explicit confirmation. If the user says no or does not respond affirmatively, stop here.

**auto mode:** Skip the confirmation gate. Proceed directly to submission.

### 4. Call submit_concept

Use the actual MCP tool parameter names:

```
submit_concept(
  name="<concise title, ≤60 chars>",
  type="<project|pattern|tool|testing|architecture>",
  content="<generalized insight, markdown, 1–10 sentences>",
  when_to_use="<one sentence: when this concept applies>",
  dont_use_when="<one sentence: when it does not apply>",
  tags=["<tag1>", "<tag2>"],
  language="<language if language-specific, else omit>"
)
```

Tags must be lowercase, hyphenated, technical — e.g. `sqlite`, `rate-limiting`, `fastmcp`, `vector-search`. 2–4 tags per concept.

If the scanner rejects the submission (error message contains "scan"), identify which field triggered, generalize it further to remove the offending specific detail, and retry once.

If the MCP server is unreachable or returns an error:
- In confirm mode: inform the user that submission failed and the insight was not stored.
- In auto mode: silently skip, do not surface the error.

### 5. Update the session file

On successful submission, append the returned concept ID to `~/.lore/session.json`:
- Create the file as `[]` if missing.
- No duplicate IDs.
- Reset to `[]` if the file is corrupted (not valid JSON).
