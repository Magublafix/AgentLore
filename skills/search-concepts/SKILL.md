---
description: Search the Lore knowledge graph for concepts relevant to the current task. Use before implementing a solution when you encounter a problem domain, technique, pattern, API, or error type that could have prior knowledge stored.
---

# search-concepts

Search the Lore knowledge graph for concepts relevant to the current task and track them in the session file.

## When to invoke

Invoke this skill whenever you encounter a problem domain, technique, pattern, API, or error type that could have prior knowledge stored in Lore. Invoke before implementing a solution, not after.

## Steps

### 1. Formulate the query

Extract 1–3 search terms from the current task context. Prefer specific technical terms over generic ones. Use the most distinctive noun or verb in the problem — not "error" or "code" but "rate-limit backoff" or "SQLite upsert".

### 2. Call search_concepts

```
search_concepts(problem="<your terms>", limit=5)
```

Optional filters: `type` (project|pattern|tool|testing|architecture), `language`.

If the MCP server is unreachable or returns an error, skip silently and continue with the task. Do not surface MCP errors to the user unless they are directly investigating Lore connectivity.

### 3. Process results

For each concept returned:
- Read the concept body and any linked concepts included in the response.
- Apply relevant knowledge directly to the current task.
- Do not re-read linked concepts with a second call — they are included in the first response.

### 4. Update the session file

Append every returned concept ID to `~/.lore/session.json`.

Rules:
- If the file does not exist, create it as `[]` first, then append.
- Never add duplicate IDs — check the existing array before appending.
- Use atomic append: read the full array, add new IDs, write back in one operation.
- If the file is corrupted (not valid JSON), reset it to `[]` before appending.

Session file format:
```json
["concept-id-1", "concept-id-2"]
```

### 5. Continue

Return to the task that triggered the search. Do not wait for user acknowledgment.
