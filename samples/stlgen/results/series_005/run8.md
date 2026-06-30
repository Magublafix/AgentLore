# Benchmark — Run 8

| Field | Value |
|-------|-------|
| Date | 2026-06-30 02:59 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (25 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 5 |
| Turns (wrapup) | 4 |
| Task submitted | no (hit limit) |
| Input tokens | 78,721 |
| Output tokens | 26,518 |
| Total tokens | 105,239 |
| Concepts captured this run | 3 |
| Elapsed | 2932.9s |
| Tests passed | ❌ no |

## Test output

```
long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight FAILED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles FAILED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count FAILED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text FAILED [100%]

=================================== FAILURES ===================================
___________________ TestSTLValidity.test_mesh_is_watertight ____________________
tests/test_text2stl_cli.py:170: in test_mesh_is_watertight
    assert mesh.is_watertight, (
E   AssertionError: Mesh is not water-tight — not 3D printable. Ensure the mesh is a closed manifold with no open edges.
E   assert False
E    +  where False = <trimesh.Trimesh(vertices.shape=(126, 3), faces.shape=(292, 3))>.is_watertight
_________________ TestSTLValidity.test_no_degenerate_triangles _________________
tests/test_text2stl_cli.py:185: in test_no_degenerate_triangles
    assert min_area > 0, (
E   AssertionError: Mesh contains degenerate (zero-area) triangles — min triangle area: 0.0
E   assert 0.0 > 0
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:205: in test_width_scales_with_char_count
    assert w5 > w1, (
E   AssertionError: 5-char mesh width (22.00) is not wider than 1-char mesh (22.50)
E   assert 22.0 > 22.5
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:249: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.137 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.13698702674079957 >= 0.25
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run8_unojcs2_/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
=================== 4 failed, 9 passed, 1 warning in 24.19s ====================

```
