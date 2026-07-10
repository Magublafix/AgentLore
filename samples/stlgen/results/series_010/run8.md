# Benchmark — Run 8

| Field | Value |
|-------|-------|
| Date | 2026-07-09 17:06 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (28 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 1 |
| Task submitted | no (hit limit) |
| Input tokens | 38,106 |
| Output tokens | 28,788 |
| Total tokens | 66,894 |
| Concepts captured this run | 0 |
| Elapsed | 3622.1s |
| Tests passed | ❌ no |

## Test output

```
]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight FAILED [ 57%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 64%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 71%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 78%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 85%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text FAILED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated FAILED [100%]

=================================== FAILURES ===================================
___________________ TestSTLValidity.test_mesh_is_watertight ____________________
tests/test_text2stl_cli.py:235: in test_mesh_is_watertight
    assert mesh.is_watertight, (
E   AssertionError: Mesh is not water-tight — not 3D printable. Ensure the mesh is a closed manifold with no open edges.
E   assert False
E    +  where False = <trimesh.Trimesh(vertices.shape=(552200, 3), faces.shape=(1076634, 3))>.is_watertight
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:314: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.197 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.19655348126187058 >= 0.25
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation -0.250 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert -0.24983078307846787 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run8_o9cv4mff/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
============= 3 failed, 11 passed, 2 warnings in 102.15s (0:01:42) =============

```
