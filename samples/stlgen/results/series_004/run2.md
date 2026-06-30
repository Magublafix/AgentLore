# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-06-29 18:37 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (4 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 9 |
| Turns (wrapup) | 8 |
| Task submitted | no (hit limit) |
| Input tokens | 50,607 |
| Output tokens | 14,950 |
| Total tokens | 65,557 |
| Concepts captured this run | 8 |
| Elapsed | 1291.4s |
| Tests passed | ❌ no |

## Test output

```
st_default_output_filename FAILED [ 30%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 38%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight PASSED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text FAILED [100%]

=================================== FAILURES ===================================
________________________ TestInvocation.test_max_length ________________________
tests/test_text2stl_cli.py:127: in test_max_length
    text2stl("ABCDEFGHIJKLMNO", "-o", str(out))  # 15 chars
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl ABCDEFGHIJKLMNO -o /tmp/pytest-of-magublafix/pytest-896/test_max_length0/max.stl exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
_________________ TestInvocation.test_default_output_filename __________________
/tmp/lore_stlgen_run2_5pyfom5r/tests/test_text2stl_cli.py:132: in test_default_output_filename
    text2stl("HI")
/tmp/lore_stlgen_run2_5pyfom5r/tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: Error: Could not generate text geometry
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:249: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.240 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.2401894451962111 >= 0.25
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run2_5pyfom5r/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
=================== 3 failed, 10 passed, 1 warning in 15.11s ===================

```
