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

By default Lore detects your project's environment from the working directory (manifests and lockfiles). To be explicit, pass `project_dir="<path>"` or `environment={"language": "python", "runtime_version": "3.12.1", "libraries": {"<lib>": "<version>"}, "platform": "linux"}`. Pass `include_incompatible=false` to drop known-incompatible results.

Optional filters: `type` (project|pattern|tool|testing|architecture), `language`. Omit `type` unless you are certain which category the concept you need falls under — a wrong guess filters out every match, including ones that would otherwise be found. When in doubt, search without it.

If the MCP server is unreachable or returns an error, skip silently and continue with the task. Do not surface MCP errors to the user unless they are directly investigating Lore connectivity.

### 3. Process results

For each concept returned:
- Read the concept body and any linked concepts included in the response.
- Check `compatibility_check.status` (and `reason`) on the result and on linked concepts. Results are already ordered compatible, then unknown, then incompatible; a high rating never overrides this.
  - `compatible`: apply it normally.
  - `unknown`: warn yourself that applicability is unverified (the reason says what is missing). If feasible, run the concept's `reproducer` (when it is not `none_available`) or a small check in your environment to validate the workaround **before relying on it**. Reproducers are never run for you; read them first and only run what is safe.
  - `incompatible`: do not apply it as-is. Tell the user about the mismatch (the reason names the violated constraint) and look for an alternative or an adaptation.
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
