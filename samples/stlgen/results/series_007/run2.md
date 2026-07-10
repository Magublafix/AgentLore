# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-07-08 20:11 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (2 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 38 |
| Turns (wrapup) | 30 |
| Task submitted | yes |
| Input tokens | 32,267 |
| Output tokens | 25,400 |
| Total tokens | 57,667 |
| Concepts captured this run | 13 |
| Elapsed | 2367.8s |
| Tests passed | ✅ yes (13/13) |

## Test output

```
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-9.0.3, pluggy-1.6.0 -- /home/magublafix/AI/AgentLore/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/lore_stlgen_run2_a0giynb6
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.13.0, asyncio-1.4.0, timeout-2.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
timeout: 60.0s
timeout method: signal
timeout func_only: False
collecting ... collected 14 items

tests/test_text2stl_cli.py::TestInvocation::test_single_char PASSED      [  7%]
tests/test_text2stl_cli.py::TestInvocation::test_five_chars PASSED       [ 14%]
tests/test_text2stl_cli.py::TestInvocation::test_max_length PASSED       [ 21%]
tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename PASSED [ 28%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 35%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 42%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 50%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight PASSED [ 57%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 64%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 71%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 78%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 85%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated PASSED [100%]

=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run2_a0giynb6/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 14 passed, 2 warnings in 18.79s ========================

```
