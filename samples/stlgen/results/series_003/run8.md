# Benchmark — Run 8

| Field | Value |
|-------|-------|
| Date | 2026-06-29 15:50 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (21 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 6 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 49,117 |
| Output tokens | 13,979 |
| Total tokens | 63,096 |
| Concepts captured this run | 5 |
| Elapsed | 1455.4s |
| Tests passed | ❌ no |

## Test output

```
.py:1209: in communicate
    stdout, stderr = self._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:2115: in _communicate
    ready = selector.select(timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/selectors.py:415: in select
    fd_event_list = self._selector.poll(timeout)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   Failed: Timeout (>60.0s) from pytest-timeout.
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:236: in test_character_shapes_match_text
    stl_img = _stl_cross_section_bitmap(out)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:49: in _stl_cross_section_bitmap
    section = mesh.section(plane_origin=[0, 0, z_mid], plane_normal=[0, 0, 1])
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/base.py:2348: in section
    path = lines_to_path(lines)
           ^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/path/exchange/misc.py:79: in lines_to_path
    return edges_to_path(edges=inverse.reshape((-1, 2)), vertices=lines[unique])
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/path/exchange/misc.py:215: in edges_to_path
    dfs_connected = graph.fill_traversals(dfs, edges=edges)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/graph.py:627: in fill_traversals
    included = util.vstack_empty([np.column_stack((i[:-1], i[1:])) for i in splits])
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/trimesh/graph.py:627: in <listcomp>
    included = util.vstack_empty([np.column_stack((i[:-1], i[1:])) for i in splits])
                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/magublafix/AI/AgentLore/.venv/lib64/python3.11/site-packages/numpy/lib/_shape_base_impl.py:665: in column_stack
    arrays.append(arr)
E   Failed: Timeout (>60.0s) from pytest-timeout.
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
=============== 5 failed, 7 passed, 1 error in 579.82s (0:09:39) ===============

```
