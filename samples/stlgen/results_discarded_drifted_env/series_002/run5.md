# Benchmark — Run 5

| Field | Value |
|-------|-------|
| Date | 2026-11-19 21:25 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 1614 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (13 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 4 |
| Task submitted | no (hit limit) |
| Input tokens | 27,386 |
| Output tokens | 21,596 |
| Total tokens | 48,982 |
| Concepts captured this run | 0 |
| Noise concepts injected | 0 |
| Elapsed | 1035.3s |
| Tests passed | ❌ no |

## Test output

```
 [ 71%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count FAILED [ 78%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 85%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated PASSED [100%]

=================================== FAILURES ===================================
___________________ TestSTLValidity.test_mesh_is_watertight ____________________
tests/test_text2stl_cli.py:235: in test_mesh_is_watertight
    assert mesh.is_watertight, (
E   AssertionError: Mesh is not water-tight — not 3D printable. Ensure the mesh is a closed manifold with no open edges.
E   assert False
E    +  where False = <trimesh.Trimesh(vertices.shape=(188, 3), faces.shape=(366, 3))>.is_watertight
_________________ TestSTLValidity.test_no_degenerate_triangles _________________
tests/test_text2stl_cli.py:250: in test_no_degenerate_triangles
    assert min_area > 0, (
E   AssertionError: Mesh contains degenerate (zero-area) triangles — min triangle area: 0.0
E   assert 0.0 > 0
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:270: in test_width_scales_with_char_count
    assert w5 > w1, (
E   AssertionError: 5-char mesh width (2.00) is not wider than 1-char mesh (2.00)
E   assert 2.0 > 2.0
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run5_gpq9vqro/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
================== 3 failed, 11 passed, 2 warnings in 14.61s ===================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
