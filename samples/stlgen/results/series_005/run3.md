# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-29 23:59 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (9 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 4 |
| Turns (wrapup) | 6 |
| Task submitted | no (hit limit) |
| Input tokens | 78,615 |
| Output tokens | 22,925 |
| Total tokens | 101,540 |
| Concepts captured this run | 4 |
| Elapsed | 2533.8s |
| Tests passed | ❌ no |

## Test output

```
nyio-4.13.0, asyncio-1.4.0, timeout-2.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
timeout: 60.0s
timeout method: signal
timeout func_only: False
collecting ... collected 13 items

tests/test_text2stl_cli.py::TestInvocation::test_single_char PASSED      [  7%]
tests/test_text2stl_cli.py::TestInvocation::test_five_chars PASSED       [ 15%]
tests/test_text2stl_cli.py::TestInvocation::test_max_length PASSED       [ 23%]
tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename PASSED [ 30%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 38%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error PASSED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight FAILED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text FAILED [100%]

=================================== FAILURES ===================================
___________________ TestSTLValidity.test_mesh_is_watertight ____________________
tests/test_text2stl_cli.py:170: in test_mesh_is_watertight
    assert mesh.is_watertight, (
E   AssertionError: Mesh is not water-tight — not 3D printable. Ensure the mesh is a closed manifold with no open edges.
E   assert False
E    +  where False = <trimesh.Trimesh(vertices.shape=(664, 3), faces.shape=(6540, 3))>.is_watertight
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:249: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.199 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.19865200425682866 >= 0.25
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run3_r3i0ajkx/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
=================== 2 failed, 11 passed, 1 warning in 30.13s ===================

```
