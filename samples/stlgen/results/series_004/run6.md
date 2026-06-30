# Benchmark — Run 6

| Field | Value |
|-------|-------|
| Date | 2026-06-29 20:27 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (21 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 7 |
| Turns (wrapup) | 4 |
| Task submitted | no (hit limit) |
| Input tokens | 64,666 |
| Output tokens | 12,847 |
| Total tokens | 77,513 |
| Concepts captured this run | 3 |
| Elapsed | 1489.0s |
| Tests passed | ✅ yes (13/13) |

## Test output

```
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-9.0.3, pluggy-1.6.0 -- /home/magublafix/AI/AgentLore/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/lore_stlgen_run6_s0w_aqh6
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.13.0, asyncio-1.4.0, timeout-2.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
timeout: 60.0s
timeout method: signal
timeout func_only: False
collecting ... collected 13 items

tests/test_text2stl_cli.py::TestInvocation::test_single_char PASSED      [  7%]
tests/test_text2stl_cli.py::TestInvocation::test_five_chars PASSED       [ 15%]
tests/test_text2stl_cli.py::TestInvocation::test_max_length PASSED       [ 23%]
tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename PASSED [ 30%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 38%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight PASSED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [100%]

=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run6_s0w_aqh6/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 13 passed, 1 warning in 22.02s ========================

```
