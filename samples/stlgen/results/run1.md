# Benchmark — Run 1/4

| Field | Value |
|-------|-------|
| Date | 2026-06-16 18:24 |
| Model | qwen2.5-coder:32b |
| Lore search active | no |
| Turn budget | 20 |
| Turns (main loop) | 20 |
| Turns (capture) | 15 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 237,123 |
| Output tokens | 8,618 |
| Total tokens | 245,741 |
| Concepts captured this run | 7 |
| Elapsed | 1969.8s |
| Tests passed | ❌ no |

## Test output

```
ocess:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - FileNot...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - FileNotF...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - FileNotF...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected
FAILED tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected - F...
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
========================= 9 failed, 4 errors in 1.81s ==========================

```
