# Benchmark — Run 8

| Field | Value |
|-------|-------|
| Date | 2026-06-30 07:29 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (26 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 5 |
| Turns (wrapup) | 3 |
| Task submitted | no (hit limit) |
| Input tokens | 34,894 |
| Output tokens | 11,729 |
| Total tokens | 46,623 |
| Concepts captured this run | 3 |
| Elapsed | 1001.6s |
| Tests passed | ❌ no |

## Test output

```
v/bin/python: No module named text2stl\n').returncode
_____________________________ test_stl_water_tight _____________________________
tests/test_text2stl_cli.py:117: in test_stl_water_tight
    assert result.returncode == 0
E   AssertionError: assert 1 == 0
E    +  where 1 = CompletedProcess(args=['/home/magublafix/AI/AgentLore/.venv/bin/python', '-m', 'text2stl', 'Hi', '-o', 'test_manifold.stl'], returncode=1, stdout='', stderr='/home/magublafix/AI/AgentLore/.venv/bin/python: No module named text2stl\n').returncode
___________________________ test_stl_normals_outward ___________________________
tests/test_text2stl_cli.py:136: in test_stl_normals_outward
    assert result.returncode == 0
E   AssertionError: assert 1 == 0
E    +  where 1 = CompletedProcess(args=['/home/magublafix/AI/AgentLore/.venv/bin/python', '-m', 'text2stl', 'X', '-o', 'test_normals.stl'], returncode=1, stdout='', stderr='/home/magublafix/AI/AgentLore/.venv/bin/python: No module named text2stl\n').returncode
___________________________ test_stl_positive_volume ___________________________
tests/test_text2stl_cli.py:155: in test_stl_positive_volume
    assert result.returncode == 0
E   AssertionError: assert 1 == 0
E    +  where 1 = CompletedProcess(args=['/home/magublafix/AI/AgentLore/.venv/bin/python', '-m', 'text2stl', 'ABC', '-o', 'test_volume.stl'], returncode=1, stdout='', stderr='/home/magublafix/AI/AgentLore/.venv/bin/python: No module named text2stl\n').returncode
_______________________ test_stl_characters_recognizable _______________________
tests/test_text2stl_cli.py:175: in test_stl_characters_recognizable
    assert result.returncode == 0
E   AssertionError: assert 1 == 0
E    +  where 1 = CompletedProcess(args=['/home/magublafix/AI/AgentLore/.venv/bin/python', '-m', 'text2stl', 'Hello', '-o', 'test_chars.stl'], returncode=1, stdout='', stderr='/home/magublafix/AI/AgentLore/.venv/bin/python: No module named text2stl\n').returncode
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::test_cli_basic - AssertionError: assert 1 ...
FAILED tests/test_text2stl_cli.py::test_cli_with_output_flag - AssertionError...
FAILED tests/test_text2stl_cli.py::test_cli_empty_string - AssertionError: as...
FAILED tests/test_text2stl_cli.py::test_cli_too_long_string - AssertionError:...
FAILED tests/test_text2stl_cli.py::test_cli_15_char_limit - AssertionError: a...
FAILED tests/test_text2stl_cli.py::test_cli_printable_ascii - AssertionError:...
FAILED tests/test_text2stl_cli.py::test_stl_valid_format - AssertionError: as...
FAILED tests/test_text2stl_cli.py::test_stl_water_tight - AssertionError: ass...
FAILED tests/test_text2stl_cli.py::test_stl_normals_outward - AssertionError:...
FAILED tests/test_text2stl_cli.py::test_stl_positive_volume - AssertionError:...
FAILED tests/test_text2stl_cli.py::test_stl_characters_recognizable - Asserti...
========================= 11 failed, 2 passed in 2.55s =========================

```
