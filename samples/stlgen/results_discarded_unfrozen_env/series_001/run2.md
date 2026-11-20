# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-11-19 11:48 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 4 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (2 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 6 |
| Task submitted | no (hit limit) |
| Input tokens | 40,694 |
| Output tokens | 37,897 |
| Total tokens | 78,591 |
| Concepts captured this run | 3 |
| Noise concepts injected | 0 |
| Elapsed | 1159.5s |
| Tests passed | ❌ no |

## Test output

```
12/site-packages/trimesh/path/raster.py:85: in rasterize
    roots = path.root
            ^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/caching.py:133: in get_cached
    value = function(*args, **kwargs)
            ^^^^^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/path/path.py:1553: in root
    populate = self.enclosure_directed  # NOQA
               ^^^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/caching.py:133: in get_cached
    value = function(*args, **kwargs)
            ^^^^^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/path/path.py:1581: in enclosure_directed
    root, enclosure = polygons.enclosure_tree(self.polygons_closed)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/path/polygons.py:87: in enclosure_tree
    tree = Index(zip(bounds.keys(), bounds.values(), [None] * len(bounds)))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/exceptions.py:40: in __call__
    self.__getattribute__("exception")
    ^^^^^^^^^^^^^^^^^^^^^
/workspace/.venvs/lore/lib/python3.12/site-packages/trimesh/exceptions.py:35: in __getattribute__
    raise exc_type(*exc_args)
E   ModuleNotFoundError: No module named 'rtree'
=============================== warnings summary ===============================
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
  /tmp/lore_stlgen_run2_l_jgzl6n/tests/test_text2stl_cli.py:52: DeprecationWarning: DEPRECATED: replace `path.to_planar`->`path.to_2D), removal 1/1/2026
    section_2d, _ = section.to_planar()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
================== 3 failed, 11 passed, 2 warnings in 21.87s ===================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
