# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-07-07 20:33 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (4 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 11 |
| Task submitted | no (hit limit) |
| Input tokens | 26,724 |
| Output tokens | 18,520 |
| Total tokens | 45,244 |
| Concepts captured this run | 2 |
| Elapsed | 1751.9s |
| Tests passed | ❌ no |

## Test output

```
ASSED [ 57%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 64%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 71%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count FAILED [ 78%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 85%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated FAILED [100%]

=================================== FAILURES ===================================
_______________________ TestInvocation.test_single_char ________________________
tests/test_text2stl_cli.py:182: in test_single_char
    text2stl("A", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-1975/test_single_char0/a.stl exited 1
E   stdout: 
E   stderr: Error generating STL: Could not extract any contours from text
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:264: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-1975/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Error generating STL: Could not extract any contours from text
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation 0.137 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert 0.13700830606307088 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run2_yq5y6l7f/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - Failed:...
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
================== 3 failed, 11 passed, 2 warnings in 21.70s ===================

```
