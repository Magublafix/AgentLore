# Benchmark — Run 9

| Field | Value |
|-------|-------|
| Date | 2026-11-19 19:56 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 4 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (44 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 1 |
| Task submitted | no (hit limit) |
| Input tokens | 31,983 |
| Output tokens | 20,370 |
| Total tokens | 52,353 |
| Concepts captured this run | 0 |
| Noise concepts injected | 0 |
| Elapsed | 1016.4s |
| Tests passed | ❌ no |

## Test output

```
is_watertight
________________ TestSTLValidity.test_mesh_has_positive_volume _________________
tests/test_text2stl_cli.py:242: in test_mesh_has_positive_volume
    assert mesh.volume > 0, (
E   AssertionError: Mesh volume is -277.3190 — expected positive. Face normals may be inverted.
E   assert np.float64(-277.31896545940134) > 0
E    +  where np.float64(-277.31896545940134) = <trimesh.Trimesh(vertices.shape=(1874, 3), faces.shape=(3752, 3))>.volume
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:314: in test_character_shapes_match_text
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.000 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.0 >= 0.25
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation 0.000 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert 0.0 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run9_b2fiy1be/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
================== 4 failed, 10 passed, 2 warnings in 16.73s ===================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
