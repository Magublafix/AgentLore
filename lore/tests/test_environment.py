"""Tests for environment detection and the compatibility checker (LORE-047)."""

from __future__ import annotations

import json

import pytest

from lore.core.environment import (
    COMPATIBLE,
    INCOMPATIBLE,
    UNKNOWN,
    Environment,
    InterpreterDetector,
    PackageJsonDetector,
    PackageLockDetector,
    PyprojectDetector,
    RequirementsDetector,
    TomlLockDetector,
    check_compatibility,
    default_detectors,
    detect_environment,
    normalize_library_name,
    normalize_platform,
)


def compat(**kw):
    base = {"language": None, "runtime_version": None, "libraries": [], "platforms": [], "assumptions": []}
    base.update(kw)
    return base


PY = Environment(language="python", runtime_version="3.12.1", libraries={"fastapi": "0.110.0"}, platform="linux")


# ---------------------------------------------------------------- checker


def test_compatible_all_satisfied():
    c = compat(language="Python", runtime_version=">=3.11,<4", platforms=["Linux"],
               libraries=[{"name": "FastAPI", "specifier": ">=0.100"}])
    r = check_compatibility(c, PY)
    assert r.status == COMPATIBLE and not r.violated and not r.missing
    assert len(r.satisfied) == 4 and r.reason


def test_incompatible_runtime_names_constraint():
    r = check_compatibility(compat(language="python", runtime_version="<3.12"), PY)
    assert r.status == INCOMPATIBLE
    assert "<3.12" in r.violated[0] and "3.12.1" in r.violated[0]


def test_incompatible_library_and_platform():
    c = compat(libraries=[{"name": "fastapi", "specifier": "<0.100"}], platforms=["windows", "macos"])
    r = check_compatibility(c, PY)
    assert r.status == INCOMPATIBLE and len(r.violated) == 2


def test_incompatible_language_skips_runtime_checks():
    env = Environment(language="javascript", runtime_version="20.0.0", platform="linux")
    r = check_compatibility(compat(language="python", runtime_version=">=3.11"), env)
    assert r.status == INCOMPATIBLE and len(r.violated) == 1 and "language" in r.violated[0]


def test_violation_beats_missing():
    c = compat(runtime_version="<3", libraries=[{"name": "absent", "specifier": ">=1"}])
    assert check_compatibility(c, PY).status == INCOMPATIBLE


@pytest.mark.parametrize("meta", [
    None, {}, "garbage", 42, {"status": "unknown"},
    {"libraries": [{"name": "x", "specifier": "not a spec"}]},  # malformed -> unknown
    {"assumptions": ["needs docker"]},  # nothing checkable
])
def test_unknown_metadata_never_compatible(meta):
    r = check_compatibility(meta, PY)
    assert r.status == UNKNOWN and r.missing


def test_missing_environment_info_is_unknown():
    c = compat(language="python", runtime_version=">=3.11", platforms=["linux"])
    r = check_compatibility(c, Environment())
    assert r.status == UNKNOWN and len(r.missing) == 3 and not r.violated


def test_undetected_library_is_unknown_not_incompatible():
    r = check_compatibility(compat(libraries=[{"name": "requests", "specifier": ">=2"}]), PY)
    assert r.status == UNKNOWN and "requests" in r.missing[0]


def test_unparsable_env_versions_are_unknown():
    env = Environment(language="python", runtime_version="banana", libraries={"x": "weird"}, platform="linux")
    c = compat(runtime_version=">=3.11", libraries=[{"name": "x", "specifier": ">=1"}])
    r = check_compatibility(c, env)
    assert r.status == UNKNOWN and len(r.missing) == 2


def test_library_any_version_present():
    c = compat(libraries=[{"name": "fastapi", "specifier": ""}])
    assert check_compatibility(c, PY).status == COMPATIBLE


def test_pep503_name_normalization():
    env = Environment(language="python", libraries={"typing-extensions": "4.9.0"})
    c = compat(libraries=[{"name": "Typing_Extensions", "specifier": ">=4"}])
    assert check_compatibility(c, env).status == COMPATIBLE
    assert normalize_library_name("A.B_c") == "a-b-c"
    assert normalize_library_name("@Scope/Pkg", "node") == "@scope/pkg"


def test_assumptions_noted_but_not_checked():
    c = compat(runtime_version=">=3.11", assumptions=["needs docker"])
    r = check_compatibility(c, PY)
    assert r.status == COMPATIBLE and "assumptions" in r.reason


def test_platform_aliases_case_insensitive():
    env = Environment(platform="Darwin")
    assert check_compatibility(compat(platforms=["MacOS"]), env).status == COMPATIBLE
    assert normalize_platform("win32") == "windows"
    assert check_compatibility(compat(platforms=["linux"]), env).status == INCOMPATIBLE


def test_node_alias_language():
    env = Environment(language="javascript", runtime_version="20.1.0")
    assert check_compatibility(compat(language="Node", runtime_version=">=18"), env).status == COMPATIBLE


@pytest.mark.parametrize("spec,version,expected", [
    (">=3.11", "3.11.0", COMPATIBLE),
    (">=3.11", "3.11", COMPATIBLE),
    (">=3.11", "3.10.99", INCOMPATIBLE),
    (">3.11", "3.11.0", INCOMPATIBLE),
    ("<4", "3.99.9", COMPATIBLE),
    ("<4", "4.0", INCOMPATIBLE),
    ("<4", "4.0.0", INCOMPATIBLE),
    ("<4", "4.0.0rc1", INCOMPATIBLE),  # PEP 440: <4 excludes pre-releases of 4
    (">=3.11", "3.12.0rc1", COMPATIBLE),  # pre-release judged on ordering
    (">=3.12", "3.12.0rc1", INCOMPATIBLE),  # rc sorts before final
    ("==3.11.*", "3.11.9", COMPATIBLE),
    ("==3.11.*", "3.12.0", INCOMPATIBLE),
    (">=3.11,<3.13", "3.13.0", INCOMPATIBLE),
])
def test_boundaries(spec, version, expected):
    env = Environment(language="python", runtime_version=version)
    assert check_compatibility(compat(runtime_version=spec), env).status == expected


def test_result_to_dict():
    d = check_compatibility(compat(runtime_version="<3"), PY).to_dict()
    assert d["status"] == INCOMPATIBLE and isinstance(d["violated"], list) and set(d) == {
        "status", "reason", "violated", "missing", "satisfied"}


# ---------------------------------------------------------------- detectors


def test_interpreter_detector():
    env = InterpreterDetector().detect()
    assert env.language == "python" and env.platform
    assert env.runtime_version and env.libraries.get("packaging")
    assert not InterpreterDetector(include_libraries=False).detect().libraries


def test_pyproject_detector(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["Fast_API==0.1.0","requests>=2","numpy[extra]==1.26.0 ; python_version>\'3\'"]\n'
        '[project.optional-dependencies]\ndev=["pytest==8.0.0"]\n'
        '[tool.poetry.dependencies]\npython="^3.11"\nrich="13.0.0"\nattrs=">=1"\n'
        '[tool.poetry.group.dev.dependencies]\nblack={version="24.1.0"}\n'
    )
    env = PyprojectDetector().detect(tmp_path)
    assert env.language == "python" and env.runtime_version is None
    assert env.libraries == {"fast-api": "0.1.0", "numpy": "1.26.0", "pytest": "8.0.0",
                             "rich": "13.0.0", "black": "24.1.0"}


def test_requirements_detector(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# c\n-r other.txt\nDjango==4.2.1  # pin\nrequests>=2\nfoo @ https://x/y.whl\n"
        "bad line!!\nflask==2.*\nPyYAML==6.0 \\\n    --hash=sha256:abc\n"
    )
    env = RequirementsDetector().detect(tmp_path)
    assert env.libraries == {"django": "4.2.1", "pyyaml": "6.0"}


def test_toml_lock_detectors(tmp_path):
    (tmp_path / "poetry.lock").write_text(
        '[[package]]\nname="Click"\nversion="8.1.7"\n[[package]]\nname="proj"\nversion="0.1"\nsource={editable="."}\n'
        '[[package]]\nname="bad"\nversion="zzz"\n'
    )
    (tmp_path / "uv.lock").write_text('[[package]]\nname="typing_extensions"\nversion="4.9.0"\n')
    assert TomlLockDetector("poetry.lock").detect(tmp_path).libraries == {"click": "8.1.7"}
    assert TomlLockDetector("uv.lock").detect(tmp_path).libraries == {"typing-extensions": "4.9.0"}


def test_package_json_detector(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"React": "18.2.0", "lodash": "^4.0.0"},
        "devDependencies": {"@types/node": "=20.1.0"},
        "engines": {"node": "20.5.0"},
    }))
    env = PackageJsonDetector().detect(tmp_path)
    assert env.language == "javascript" and env.runtime_version == "20.5.0"
    assert env.libraries == {"react": "18.2.0", "@types/node": "20.1.0"}


def test_package_json_range_engine_not_a_runtime(tmp_path):
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=18"}}')
    assert PackageJsonDetector().detect(tmp_path).runtime_version is None


def test_package_lock_v3_and_v1(tmp_path):
    (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"name": "x"}, "node_modules/Express": {"version": "4.18.2"},
        "node_modules/@a/b": {"version": "1.0.0"},
        "node_modules/express/node_modules/dep": {"version": "9.9.9"}}}))
    env = PackageLockDetector().detect(tmp_path)
    assert env.libraries == {"express": "4.18.2", "@a/b": "1.0.0"}
    (tmp_path / "package-lock.json").write_text(json.dumps({"dependencies": {"left-pad": {"version": "1.3.0"}}}))
    assert PackageLockDetector().detect(tmp_path).libraries == {"left-pad": "1.3.0"}


@pytest.mark.parametrize("detector,filename", [
    (PyprojectDetector(), "pyproject.toml"), (RequirementsDetector(), "requirements.txt"),
    (TomlLockDetector("uv.lock"), "uv.lock"), (TomlLockDetector("poetry.lock"), "poetry.lock"),
    (PackageJsonDetector(), "package.json"), (PackageLockDetector(), "package-lock.json"),
])
@pytest.mark.parametrize("content", [b"", b"\xff\xfe{{{ not valid", b"[[[", b"[]", b'{"a": '])
def test_missing_and_malformed_files(detector, filename, content, tmp_path):
    assert detector.detect(tmp_path) == Environment()  # missing
    (tmp_path / filename).write_bytes(content)
    env = detector.detect(tmp_path)  # must not raise
    assert env.libraries == {}


def test_malformed_shapes_tolerated(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": ["a"], "engines": 5}')
    (tmp_path / "poetry.lock").write_text('package = "nope"')
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = "x"\n[tool]\npoetry = 3\n')
    for d in (PackageJsonDetector(), TomlLockDetector("poetry.lock"), PyprojectDetector()):
        d.detect(tmp_path)


def test_directory_named_like_file(tmp_path):
    (tmp_path / "pyproject.toml").mkdir()
    assert PyprojectDetector().detect(tmp_path) == Environment()


# ---------------------------------------------------------------- merge / orchestration


def test_detect_environment_priority_and_merge(tmp_path):
    (tmp_path / "uv.lock").write_text('[[package]]\nname="fastapi"\nversion="0.111.0"\n')
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["fastapi==0.1.0","pydantic==2.0"]')
    env = detect_environment(tmp_path)
    assert env.libraries["fastapi"] == "0.111.0" and env.libraries["pydantic"] == "2.0"
    assert env.language == "python" and env.runtime_version and env.platform
    assert env.sources[0] == "uv.lock" and "interpreter" in env.sources


def test_node_project_not_polluted_by_interpreter(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "18.2.0"}}')
    env = detect_environment(tmp_path)
    assert env.language == "javascript" and env.runtime_version is None
    assert env.libraries == {"react": "18.2.0"} and env.platform
    # runtime unknown -> checker must say unknown, not use python's version
    assert check_compatibility(compat(language="node", runtime_version=">=18"), env).status == UNKNOWN


def test_empty_project_falls_back_to_interpreter(tmp_path):
    env = detect_environment(tmp_path)
    assert env.language == "python" and env.sources == ("interpreter",)


def test_custom_and_failing_detectors(tmp_path):
    class Fixed:
        name = "fixed"

        def detect(self, project_dir):
            return Environment(language="python", runtime_version="3.9.0", platform="linux", sources=("fixed",))

    class Boom:
        name = "boom"

        def detect(self, project_dir):
            raise RuntimeError("x")

    env = detect_environment(tmp_path, [Boom(), Fixed()])
    assert env.runtime_version == "3.9.0" and env.sources == ("fixed",)
    assert detect_environment(tmp_path, []) == Environment()


def test_default_detectors_without_interpreter():
    assert not any(isinstance(d, InterpreterDetector) for d in default_detectors(include_interpreter=False))


def test_end_to_end(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.110.0\n")
    env = detect_environment(tmp_path)
    assert check_compatibility(compat(libraries=[{"name": "FastAPI", "specifier": ">=0.100,<1"}]), env).status == COMPATIBLE
    assert check_compatibility(compat(libraries=[{"name": "FastAPI", "specifier": ">=1"}]), env).status == INCOMPATIBLE
