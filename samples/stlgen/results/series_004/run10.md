# Benchmark — Run 10

| Field | Value |
|-------|-------|
| Date | 2026-06-29 22:00 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (33 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 7 |
| Turns (wrapup) | 5 |
| Task submitted | no (hit limit) |
| Input tokens | 46,507 |
| Output tokens | 13,617 |
| Total tokens | 60,124 |
| Concepts captured this run | 3 |
| Elapsed | 1229.4s |
| Tests passed | ❌ no |

## Test output

```
ext2stl_cli.py:202: in test_width_scales_with_char_count
    mesh5 = _load_mesh(out5)
            ^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:39: in _load_mesh
    assert mesh is not None and len(mesh.vertices) > 0, \
E   AssertionError: Failed to load mesh from /tmp/pytest-of-magublafix/pytest-911/test_width_scales_with_char_co0/hello.stl
E   assert (<trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))> is not None and 0 > 0)
E    +  where 0 = len(TrackedArray([], shape=(0, 3), dtype=float64))
E    +    where TrackedArray([], shape=(0, 3), dtype=float64) = <trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))>.vertices
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:218: in test_cross_section_is_nonempty
    mesh = _load_mesh(out)
           ^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:39: in _load_mesh
    assert mesh is not None and len(mesh.vertices) > 0, \
E   AssertionError: Failed to load mesh from /tmp/pytest-of-magublafix/pytest-911/test_cross_section_is_nonempty0/hello.stl
E   assert (<trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))> is not None and 0 > 0)
E    +  where 0 = len(TrackedArray([], shape=(0, 3), dtype=float64))
E    +    where TrackedArray([], shape=(0, 3), dtype=float64) = <trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))>.vertices
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:236: in test_character_shapes_match_text
    stl_img = _stl_cross_section_bitmap(out)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:47: in _stl_cross_section_bitmap
    mesh = _load_mesh(stl_path)
           ^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:39: in _load_mesh
    assert mesh is not None and len(mesh.vertices) > 0, \
E   AssertionError: Failed to load mesh from /tmp/pytest-of-magublafix/pytest-911/test_character_shapes_match_te0/hello.stl
E   assert (<trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))> is not None and 0 > 0)
E    +  where 0 = len(TrackedArray([], shape=(0, 3), dtype=float64))
E    +    where TrackedArray([], shape=(0, 3), dtype=float64) = <trimesh.Trimesh(vertices.shape=(0, 3), faces.shape=(0, 3))>.vertices
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
========================= 7 failed, 6 passed in 23.16s =========================

```
