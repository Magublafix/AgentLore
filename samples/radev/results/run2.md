# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-06-11 16:26 |
| Model | claude-sonnet-4-6 |
| Lore skills active | yes (8 concepts available) |
| Turns | 17 |
| Input tokens | 146,442 |
| Output tokens | 4,425 |
| Total tokens | 150,867 |
| Elapsed | 143.7s |
| Tests passed | ✅ yes (9/9) |

## Test output

```
============================= test session starts ==============================
platform linux -- Python 3.9.25, pytest-8.4.2, pluggy-1.6.0 -- /usr/bin/python
cachedir: .pytest_cache
rootdir: /tmp/lore_bench_run2_5wqcpxvo
configfile: pyproject.toml
plugins: cov-7.0.0, anyio-4.12.1
collecting ... collected 9 items

tests/test_radev_cli.py::TestList::test_returns_json_array PASSED        [ 11%]
tests/test_radev_cli.py::TestList::test_each_item_has_id_and_name PASSED [ 22%]
tests/test_radev_cli.py::TestCreate::test_returns_object_with_id PASSED  [ 33%]
tests/test_radev_cli.py::TestCreate::test_missing_name_exits_nonzero PASSED [ 44%]
tests/test_radev_cli.py::TestGet::test_returns_correct_object PASSED     [ 55%]
tests/test_radev_cli.py::TestGet::test_nonexistent_id_exits_nonzero PASSED [ 66%]
tests/test_radev_cli.py::TestUpdate::test_update_reflects_in_get PASSED  [ 77%]
tests/test_radev_cli.py::TestDelete::test_delete_exits_zero PASSED       [ 88%]
tests/test_radev_cli.py::TestDelete::test_get_after_delete_exits_nonzero PASSED [100%]

============================== 9 passed in 7.29s ===============================

```
