# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-28 18:06 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (8 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 10 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 71,738 |
| Output tokens | 21,021 |
| Total tokens | 92,759 |
| Concepts captured this run | 5 |
| Elapsed | 1912.2s |
| Tests passed | ❌ no |

## Test output

```
/python3
cachedir: .pytest_cache
rootdir: /tmp/lore_stlgen_run3_gyst_a_y
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
tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename FAILED [ 30%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 38%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight PASSED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count FAILED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [100%]

=================================== FAILURES ===================================
_________________ TestInvocation.test_default_output_filename __________________
/tmp/lore_stlgen_run3_gyst_a_y/tests/test_text2stl_cli.py:132: in test_default_output_filename
    text2stl("HI")
/tmp/lore_stlgen_run3_gyst_a_y/tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: Error creating mesh: Invalid polygon
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:205: in test_width_scales_with_char_count
    assert w5 > w1, (
E   AssertionError: 5-char mesh width (3.00) is not wider than 1-char mesh (3.00)
E   assert 3.0 > 3.0
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run3_gyst_a_y/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
=================== 2 failed, 11 passed, 1 warning in 17.07s ===================

```
