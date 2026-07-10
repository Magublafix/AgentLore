# Benchmark — Run 8

| Field | Value |
|-------|-------|
| Date | 2026-07-08 03:19 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (23 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 9 |
| Task submitted | no (hit limit) |
| Input tokens | 25,071 |
| Output tokens | 18,133 |
| Total tokens | 43,204 |
| Concepts captured this run | 2 |
| Elapsed | 2111.8s |
| Tests passed | ❌ no |

## Test output

```
cter_shapes_match_text FAILED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated FAILED [100%]

=================================== FAILURES ===================================
___________________ TestSTLValidity.test_mesh_is_watertight ____________________
tests/test_text2stl_cli.py:235: in test_mesh_is_watertight
    assert mesh.is_watertight, (
E   AssertionError: Mesh is not water-tight — not 3D printable. Ensure the mesh is a closed manifold with no open edges.
E   assert False
E    +  where False = <trimesh.Trimesh(vertices.shape=(51080, 3), faces.shape=(96938, 3))>.is_watertight
________________ TestSTLValidity.test_mesh_has_positive_volume _________________
tests/test_text2stl_cli.py:242: in test_mesh_has_positive_volume
    assert mesh.volume > 0, (
E   AssertionError: Mesh volume is -273044.2500 — expected positive. Face normals may be inverted.
E   assert np.float64(-273044.25) > 0
E    +  where np.float64(-273044.25) = <trimesh.Trimesh(vertices.shape=(51080, 3), faces.shape=(96938, 3))>.volume
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:314: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.196 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.19621263974446726 >= 0.25
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation -0.274 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert -0.27441465999766673 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run8_r6edy39r/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
================== 4 failed, 10 passed, 2 warnings in 25.75s ===================

```
