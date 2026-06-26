# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-26 10:30 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (13 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (capture) | 15 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 75,688 |
| Output tokens | 25,853 |
| Total tokens | 101,541 |
| Concepts captured this run | 2 |
| Elapsed | 2463.5s |
| Tests passed | ❌ no |

## Test output

```
hars PASSED       [ 15%]
tests/test_text2stl_cli.py::TestInvocation::test_max_length PASSED       [ 23%]
tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename PASSED [ 30%]
tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected PASSED [ 38%]
tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected PASSED [ 46%]
tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error FAILED [ 53%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight PASSED [ 61%]
tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume PASSED [ 69%]
tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles PASSED [ 76%]
tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count PASSED [ 84%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty PASSED [ 92%]
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text PASSED [100%]

=================================== FAILURES ===================================
_________________ TestSTLValidity.test_stl_loads_without_error _________________
tests/test_text2stl_cli.py:165: in test_stl_loads_without_error
    mesh = _load_mesh(hello_stl)
           ^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:37: in _load_mesh
    import trimesh
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/__init__.py:12: in <module>
    from . import (
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/creation.py:15: in <module>
    from .base import Trimesh
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/base.py:43: in <module>
    from .exchange.export import export_mesh
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/exchange/export.py:10: in <module>
    from .obj import export_obj
<frozen importlib._bootstrap>:1176: in _find_and_load
    ???
<frozen importlib._bootstrap>:1147: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:690: in _load_unlocked
    ???
<frozen importlib._bootstrap_external>:936: in exec_module
    ???
<frozen importlib._bootstrap_external>:1032: in get_code
    ???
<frozen importlib._bootstrap_external>:1132: in get_data
    ???
E   Failed: Timeout (>60.0s) from pytest-timeout.
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
  /tmp/lore_stlgen_run3_sqzrwvdc/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
============== 1 failed, 12 passed, 1 warning in 90.66s (0:01:30) ==============

```
