# Benchmark — Run 6

| Field | Value |
|-------|-------|
| Date | 2026-07-08 06:44 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (9 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 3 |
| Task submitted | no (hit limit) |
| Input tokens | 25,277 |
| Output tokens | 16,049 |
| Total tokens | 41,326 |
| Concepts captured this run | 0 |
| Elapsed | 1724.4s |
| Tests passed | ❌ no |

## Test output

```
st' object has no attribute 'bounds'
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:264: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-2060/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Error generating STL: 'list' object has no attribute 'bounds'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:282: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2060/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error generating STL: 'list' object has no attribute 'bounds'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2060/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error generating STL: 'list' object has no attribute 'bounds'
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2060/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Error generating STL: 'list' object has no attribute 'bounds'
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - Failed:...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
==================== 8 failed, 2 passed, 4 errors in 19.91s ====================

```
