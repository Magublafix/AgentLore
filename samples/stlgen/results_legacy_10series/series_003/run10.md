# Benchmark — Run 10

| Field | Value |
|-------|-------|
| Date | 2026-07-24 18:08 |
| Backend | gists |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (24 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 15 |
| Task submitted | no (hit limit) |
| Input tokens | 22,599 |
| Output tokens | 11,740 |
| Total tokens | 34,339 |
| Concepts captured this run | 9 |
| Elapsed | 949.6s |
| Tests passed | ❌ no |

## Test output

```
"A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-3545/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Error creating STL: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:282: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-3545/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error creating STL: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-3545/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error creating STL: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-3545/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Error creating STL: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
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
==================== 8 failed, 2 passed, 4 errors in 17.60s ====================

```
