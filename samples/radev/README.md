# radev — restful-api.dev CLI

A Linux CLI client for the [restful-api.dev](https://restful-api.dev/) public REST API.

## Install

```bash
cd samples/radev
pip install -e .
```

After install, `radev` is available on your PATH.

## CLI Interface

All commands output JSON to stdout. Exit code 0 on success, non-zero on error.

### list

```bash
radev list
```

Returns a JSON array of all objects. Each item has at minimum `id` and `name`.

### get

```bash
radev get <id>
```

Returns the object with the given ID as JSON (`{id, name, data}`). Exits non-zero if not found.

### create

```bash
radev create --name "My Object" --data '{"key": "value"}'
```

Creates a new object. `--name` is required. `--data` is optional (defaults to `{}`). Returns the created object including its assigned `id`.

### update

```bash
radev update <id> --data '{"key": "new value"}'
```

Partially updates the object's `data` field (PATCH semantics). Returns the updated object. Exits non-zero if not found.

### delete

```bash
radev delete <id>
```

Deletes the object. Exits non-zero if not found.

## Running the tests

```bash
pytest samples/radev/tests/test_radev_cli.py -v
```

10 tests total — requires network access to `https://api.restful-api.dev`.

## Benchmark results

See `results/run1.md` and `results/run2.md` for token and prompt counts from the benchmark runs.
