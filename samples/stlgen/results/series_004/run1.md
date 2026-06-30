# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-29 18:08 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 6 |
| Turns (wrapup) | 4 |
| Task submitted | no (hit limit) |
| Input tokens | 57,487 |
| Output tokens | 14,489 |
| Total tokens | 71,976 |
| Concepts captured this run | 4 |
| Elapsed | 1557.8s |
| Tests passed | ❌ no |

## Test output

```
._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:2115: in _communicate
    ready = selector.select(timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/selectors.py:415: in select
    fd_event_list = self._selector.poll(timeout)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   Failed: Timeout (>60.0s) from pytest-timeout.
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:550: in run
    stdout, stderr = process.communicate(input, timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1209: in communicate
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
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:550: in run
    stdout, stderr = process.communicate(input, timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1209: in communicate
    stdout, stderr = self._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:2115: in _communicate
    ready = selector.select(timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/selectors.py:415: in select
    fd_event_list = self._selector.poll(timeout)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   Failed: Timeout (>60.0s) from pytest-timeout.
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
============== 4 failed, 7 passed, 2 errors in 573.73s (0:09:33) ===============

```
