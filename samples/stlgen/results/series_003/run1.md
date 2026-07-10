# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-07-08 00:35 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 8 |
| Task submitted | no (hit limit) |
| Input tokens | 29,296 |
| Output tokens | 17,660 |
| Total tokens | 46,956 |
| Concepts captured this run | 3 |
| Elapsed | 1808.0s |
| Tests passed | ❌ no |

## Test output

```
D      [  7%]
tests/test_text2stl_cli.py::TestInvocation::test_five_chars PASSED       [ 14%]
tests/test_text2stl_cli.py::TestInvocation::test_max_length FAILED       [ 21%]
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

=================================== FAILURES ===================================
________________________ TestInvocation.test_max_length ________________________
tests/test_text2stl_cli.py:192: in test_max_length
    text2stl("ABCDEFGHIJKLMNO", "-o", str(out))  # 15 chars
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:550: in run
    stdout, stderr = process.communicate(input, timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1209: in communicate
    stdout, stderr = self._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:2115: in _communicate
    ready = selector.select(timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/selectors.py:415: in select
    fd_event_list = self._selector.poll(timeout)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   Failed: Timeout (>60.0s) from pytest-timeout.
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run1_b_hwimva/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
============= 1 failed, 13 passed, 2 warnings in 240.39s (0:04:00) =============

```
