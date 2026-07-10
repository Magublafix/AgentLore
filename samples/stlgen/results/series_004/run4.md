# Benchmark — Run 4

| Field | Value |
|-------|-------|
| Date | 2026-07-08 05:49 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (7 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 12 |
| Task submitted | no (hit limit) |
| Input tokens | 42,384 |
| Output tokens | 17,215 |
| Total tokens | 59,599 |
| Concepts captured this run | 2 |
| Elapsed | 1898.1s |
| Tests passed | ❌ no |

## Test output

```
71%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count FAILED [ 78%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 85%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text FAILED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated FAILED [100%]

=================================== FAILURES ===================================
_________________ TestSTLValidity.test_no_degenerate_triangles _________________
tests/test_text2stl_cli.py:250: in test_no_degenerate_triangles
    assert min_area > 0, (
E   AssertionError: Mesh contains degenerate (zero-area) triangles — min triangle area: 0.0
E   assert 0.0 > 0
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:270: in test_width_scales_with_char_count
    assert w5 > w1, (
E   AssertionError: 5-char mesh width (8.92) is not wider than 1-char mesh (9.14)
E   assert 8.916667938232422 > 9.137931823730469
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:314: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.233 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.23334430391649819 >= 0.25
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation -0.111 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert -0.11108678514057554 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run4_1ykk9nen/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
================== 4 failed, 10 passed, 2 warnings in 17.77s ===================

```
