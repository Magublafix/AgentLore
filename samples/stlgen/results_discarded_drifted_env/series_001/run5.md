# Benchmark — Run 5

| Field | Value |
|-------|-------|
| Date | 2026-11-19 18:13 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 4 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (21 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 10 |
| Task submitted | no (hit limit) |
| Input tokens | 35,178 |
| Output tokens | 30,506 |
| Total tokens | 65,684 |
| Concepts captured this run | 9 |
| Noise concepts injected | 0 |
| Elapsed | 1381.0s |
| Tests passed | ❌ no |

## Test output

```
s 0.0000 — expected positive. Face normals may be inverted.
E   assert np.float64(0.0) > 0
E    +  where np.float64(0.0) = <trimesh.Trimesh(vertices.shape=(39230, 3), faces.shape=(97576, 3))>.volume
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:286: in test_cross_section_is_nonempty
    assert section is not None, (
E   AssertionError: No cross-section at mid-height — mesh may not be extruded text. Check that characters have non-zero height.
E   assert None is not None
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:303: in test_character_shapes_match_text
    pytest.fail("Could not rasterize cross-section — check mesh height")
E   Failed: Could not rasterize cross-section — check mesh height
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:353: in test_character_shapes_not_truncated
    pytest.fail("Could not rasterize cross-section — check mesh height")
E   Failed: Could not rasterize cross-section — check mesh height
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/triangles.py:302: RuntimeWarning: divide by zero encountered in divide
    center_mass = integrated[1:4] / volume

tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/triangles.py:302: RuntimeWarning: invalid value encountered in divide
    center_mass = integrated[1:4] / volume

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
============= 5 failed, 9 passed, 2 warnings in 114.06s (0:01:54) ==============
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
