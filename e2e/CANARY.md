# Claude canary (optional, non-blocking)

Workflow: `.github/workflows/e2e-claude.yml` ("E2E Claude canary"). Parser: `e2e/canary/parse.py` (unit tests: `e2e/canary/test_parse.py`).

## What it proves

The login-free suite (`e2e/`, workflow `e2e.yml`) shows that `mcp-server-lore init` registers a server that Claude Code reports as Connected. The canary goes one step further: a real headless Claude Code session, driven by a real model, discovers the registered `lore` server and successfully calls `mcp__lore__search_concepts`, and the result contains the seed concept "REST CLI around a REST API". It asserts the tool call and result, not the model's prose (non-deterministic).

## Not a PR gate

It runs only on a daily `schedule` and `workflow_dispatch`. It uses a paid API key and a non-deterministic model, so it must not block merges. On a scheduled failure it opens or updates a single issue titled "Claude canary failing". If `ANTHROPIC_API_KEY` is not set, the run passes with a notice and does nothing.

## Security rationale

There is intentionally no `pull_request` or `pull_request_target` trigger: PR code (especially from forks) would run in a job with access to the key. The workflow has `contents: read` only (`issues: write` on the report job alone). The key is exposed to a single step, masked, never echoed, and the log is scanned for it before upload (the log is deleted and the job fails if found). Wheels are built in-run and kept as 1-day artifacts; nothing is published.

## Cost

Use a dedicated Anthropic Console key in a workspace with a low spend limit. Each run is capped with `--max-budget-usd 0.25`; the default model is `claude-haiku-5-5` (falls back to alias `haiku` if rejected). Expect a fraction of a cent to a few cents per run.

## Adding the secret

Repo Settings -> Secrets and variables -> Actions -> New repository secret `ANTHROPIC_API_KEY`, or the owner runs `gh secret set ANTHROPIC_API_KEY` and pastes at the prompt. Never paste a key into chat, an issue, or a commit.

## Running manually

    gh workflow run "E2E Claude canary"
    gh workflow run "E2E Claude canary" -f model=haiku

Download the `canary-log` artifact (stream-json log, stderr, summary) from the run.

## Status: unverified against real output

The parser and workflow have NOT been run against a real Claude session. The stream-json samples in the tests are hand-built from the documented format (`assistant` messages with `tool_use` blocks, `user` messages with `tool_result` blocks, final `result` event). The first live run will likely need adjustments (event shapes, `--permission-mode dontAsk` behaviour with `--allowedTools`, model id, whether `claude mcp get` prints "Connected").

## Key-leak scan and model retry

A separate `scan` step runs with `if: always()` (so also after a timeout kill) before the upload. It is the only other step that sees the key; if the key appears in any output file it deletes them all and fails. The upload runs only when `steps.scan.outcome == 'success'`, so an unscanned log is never uploaded.

The haiku-alias retry fires only when `parse.py --model-rejected` finds a specific model-rejection message (stderr or an error result event), not on any mention of "model". The retry writes `stream.retry.jsonl` / `stderr.retry.txt`, keeping the first failure's log.
