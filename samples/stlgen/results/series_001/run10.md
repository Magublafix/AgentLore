# Benchmark — Run 10

| Field | Value |
|-------|-------|
| Date | 2026-07-19 10:54 |
| Backend | gists |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (27 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 3 |
| Task submitted | no (hit limit) |
| Input tokens | 31,225 |
| Output tokens | 37,415 |
| Total tokens | 68,640 |
| Concepts captured this run | 1 |
| Elapsed | 4709.3s |
| Tests passed | ❌ no |

## Test output

```
xt
    assert iou >= 0.25, (
E   AssertionError: Character shape IoU 0.000 < 0.25 — cross-section does not resemble 'HELLO'. Letters may be malformed, missing, or in wrong order.
E   assert 0.0 >= 0.25
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:361: in test_character_shapes_not_truncated
    assert min_corr >= 0.3, (
E   AssertionError: Band-profile correlation 0.000 < 0.3 — cross-section looks truncated (missing a chunk of its vertical or horizontal extent) even though it may still pass the IoU shape check. Check for clipping against canvas/render boundaries — e.g. font size too large relative to canvas combined with edge-anchored text placement.
E   assert 0.0 >= 0.3
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/triangles.py:302: RuntimeWarning: divide by zero encountered in divide
    center_mass = integrated[1:4] / volume

tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/triangles.py:302: RuntimeWarning: invalid value encountered in divide
    center_mass = integrated[1:4] / volume

tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/triangles.py:316: RuntimeWarning: invalid value encountered in scalar multiply
    integrated[5] + integrated[6] - (volume * (center_mass[[1, 2]] ** 2).sum())

tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
  /home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/triangles.py:325: RuntimeWarning: invalid value encountered in scalar multiply
    inertia[1, 2] = -(integrated[8] - (volume * np.prod(center_mass[[1, 2]])))

tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run10_ya2m2yzn/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
=================== 5 failed, 9 passed, 6 warnings in 42.25s ===================

```
