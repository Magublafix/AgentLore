"""Environment detection and compatibility checking (LORE-047).

Two independent halves:

1. **Detection** -- a pluggable :class:`EnvironmentDetector` protocol and
   concrete detectors (running interpreter, ``pyproject.toml``, Python
   lockfiles, ``package.json``, ``package-lock.json``).  Detectors only read
   files / interpreter metadata; they never execute project code, spawn
   processes, or touch the network, and they tolerate missing or malformed
   files (returning an empty :class:`Environment`).  :func:`detect_environment`
   merges their output.

2. **Checking** -- :func:`check_compatibility`, a pure function comparing a
   concept's compatibility metadata (shape defined in :mod:`lore.core.compat`)
   with an :class:`Environment`.  The result is ``compatible``,
   ``incompatible`` (violated constraints named) or ``unknown`` (missing
   information named).

Decision rules for the checker:
    * Any violated constraint -> ``incompatible``.
    * Else any constraint that cannot be verified (environment value missing,
      unparsable version, library not detected) -> ``unknown``.
    * Else at least one constraint verified -> ``compatible``.
    * No checkable constraint at all (metadata ``unknown``/empty/malformed,
      or only free-text assumptions) -> ``unknown``.  Absence of metadata is
      never read as compatibility, and a library that was simply not detected
      is never read as a violation.

Versions are PEP 440 (``packaging``).  Specifiers are evaluated with
``prereleases=True`` so a pre-release environment is judged on its ordering
(``3.12.0rc1`` satisfies ``>=3.11``) while PEP 440 still keeps ``4.0.0rc1``
outside ``<4`` and ``3.11.0`` equal to ``3.11`` (``>=3.11`` holds, ``<4``
fails for ``4.0``).
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from lore.core.compat import load_compatibility

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNKNOWN = "unknown"

_LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "cpython": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "node.js": "javascript",
    "ts": "javascript",
    "typescript": "javascript",
}
_PLATFORM_ALIASES = {
    "darwin": "macos",
    "mac": "macos",
    "osx": "macos",
    "macosx": "macos",
    "win32": "windows",
    "win": "windows",
    "linux2": "linux",
}


def normalize_language(value: str | None) -> str | None:
    """Lower-case a language name and fold aliases (``node``/``typescript`` -> ``javascript``)."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().lower()
    return _LANGUAGE_ALIASES.get(key, key)


def normalize_platform(value: str | None) -> str | None:
    """Lower-case a platform name and fold aliases (``darwin`` -> ``macos``, ``win32`` -> ``windows``)."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().lower()
    return _PLATFORM_ALIASES.get(key, key)


def normalize_library_name(name: str, language: str | None = None) -> str:
    """Normalize a library name: PEP 503 for Python (and unknown language), lower-case for JavaScript."""
    name = name.strip()
    if normalize_language(language) == "javascript":
        return name.lower()
    return str(canonicalize_name(name))


def _parse_version(text: Any) -> Version | None:
    if not isinstance(text, str):
        return None
    try:
        return Version(text.strip())
    except InvalidVersion:
        return None


# ---------------------------------------------------------------------------
# Environment model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Environment:
    """What is known about a project's environment (any field may be unknown).

    Attributes:
        language: Canonical lower-case language (``"python"``, ``"javascript"``) or ``None``.
        runtime_version: Concrete runtime version string (e.g. ``"3.12.3"``) or ``None``.
        libraries: Normalized library name -> concrete version string.
        platform: Canonical lower-case platform (``"linux"``, ``"macos"``, ``"windows"``) or ``None``.
        sources: Names of the detectors that contributed (informational).
    """

    language: str | None = None
    runtime_version: str | None = None
    libraries: dict[str, str] = field(default_factory=dict)
    platform: str | None = None
    sources: tuple[str, ...] = ()

    def merge(self, other: Environment) -> Environment:
        """Return a new environment; values already known here win over ``other``.

        ``other`` only fills gaps.  Runtime version and libraries are taken
        from ``other`` only when the languages agree (or this one has none), so
        a Python interpreter never contributes to a Node project.  Platform is
        language independent.
        """
        same_lang = self.language is None or other.language is None or self.language == other.language
        libraries = dict(self.libraries)
        if same_lang:
            for name, version in other.libraries.items():
                libraries.setdefault(name, version)
        return Environment(
            language=self.language or (other.language if same_lang else None),
            runtime_version=self.runtime_version or (other.runtime_version if same_lang else None),
            libraries=libraries,
            platform=self.platform or other.platform,
            sources=self.sources + tuple(s for s in other.sources if s not in self.sources),
        )


@dataclass(frozen=True)
class CompatResult:
    """Outcome of :func:`check_compatibility`.

    Attributes:
        status: ``"compatible"`` | ``"incompatible"`` | ``"unknown"``.
        reason: One human-readable sentence/paragraph explaining the status.
        violated: Descriptions of violated constraints (non-empty iff incompatible).
        missing: What could not be verified (environment info absent/unparsable).
        satisfied: Constraints verified as met.
    """

    status: str
    reason: str
    violated: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    satisfied: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """JSON-safe dict form (lists instead of tuples)."""
        return {
            "status": self.status,
            "reason": self.reason,
            "violated": list(self.violated),
            "missing": list(self.missing),
            "satisfied": list(self.satisfied),
        }


# ---------------------------------------------------------------------------
# Detector interface
# ---------------------------------------------------------------------------


@runtime_checkable
class EnvironmentDetector(Protocol):
    """Pluggable detector: any object with ``name`` and ``detect(project_dir)``.

    ``detect`` must be side-effect free (read files only, no code execution, no
    network) and must not raise for missing/malformed input -- return an empty
    :class:`Environment` instead.
    """

    name: str

    def detect(self, project_dir: Path) -> Environment:
        """Return what this detector can determine about ``project_dir``."""
        ...


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_toml(path: Path) -> dict:
    text = _read_text(path)
    if text is None:
        return {}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict:
    text = _read_text(path)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _py_env(libs: dict[str, str], source: str) -> Environment:
    return Environment(language="python", libraries=libs, sources=(source,)) if libs else Environment()


def _pin_from_requirement(line: str) -> tuple[str, str] | None:
    """Return ``(normalized_name, version)`` for an exact ``==``/``===`` pin, else ``None``."""
    try:
        req = Requirement(line)
    except InvalidRequirement:
        return None
    pins = [s for s in req.specifier if s.operator in ("==", "===") and "*" not in s.version]
    if len(pins) != 1 or _parse_version(pins[0].version) is None:
        return None
    return str(canonicalize_name(req.name)), str(Version(pins[0].version))


class InterpreterDetector:
    """The running interpreter: language, runtime version, platform, installed distributions.

    Installed distributions are read from ``importlib.metadata`` (metadata files
    only).  They describe the interpreter running Lore, which may not be the
    project's, so this detector is lowest priority in :func:`default_detectors`.
    """

    name = "interpreter"

    def __init__(self, include_libraries: bool = True) -> None:
        self.include_libraries = include_libraries

    def detect(self, project_dir: Path | None = None) -> Environment:
        """Describe the running Python interpreter and OS."""
        v = sys.version_info
        suffix = {"alpha": "a", "beta": "b", "candidate": "rc"}.get(v.releaselevel, "")
        version = f"{v.major}.{v.minor}.{v.micro}" + (f"{suffix}{v.serial}" if suffix else "")
        libs: dict[str, str] = {}
        if self.include_libraries:
            try:
                from importlib import metadata

                for dist in metadata.distributions():
                    name, ver = dist.metadata["Name"], dist.version
                    if name and ver and _parse_version(ver) is not None:
                        libs.setdefault(str(canonicalize_name(name)), ver)
            except Exception:  # noqa: BLE001 - metadata scanning must never break detection
                libs = {}
        return Environment(
            language="python",
            runtime_version=version,
            libraries=libs,
            platform=normalize_platform(sys.platform),
            sources=(self.name,),
        )


class PyprojectDetector:
    """``pyproject.toml``: language plus *exactly pinned* dependencies.

    Ranges (``>=1``) carry no concrete version and are ignored; ``requires-python``
    is a constraint, not a runtime, so it is not reported as a runtime version.
    Reads PEP 621 ``dependencies``/``optional-dependencies``/``dependency-groups``
    and Poetry's ``tool.poetry.dependencies`` (exact version strings only).
    """

    name = "pyproject"

    def detect(self, project_dir: Path) -> Environment:
        """Parse ``<project_dir>/pyproject.toml``; empty environment if absent or malformed."""
        path = Path(project_dir) / "pyproject.toml"
        if not path.is_file():
            return Environment()
        data = _read_toml(path)
        if not data:
            return Environment()
        libs: dict[str, str] = {}
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        lines: list[Any] = list(project.get("dependencies") or [])
        for group in (project.get("optional-dependencies") or {}).values():
            lines.extend(group if isinstance(group, list) else [])
        for group in (data.get("dependency-groups") or {}).values():
            lines.extend(group if isinstance(group, list) else [])
        for line in lines:
            if isinstance(line, str) and (pin := _pin_from_requirement(line)):
                libs.setdefault(*pin)
        poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
        if isinstance(poetry, dict):
            deps = dict(poetry.get("dependencies") or {})
            for group in (poetry.get("group") or {}).values():
                if isinstance(group, dict):
                    deps.update(group.get("dependencies") or {})
            for name, spec in deps.items():
                if isinstance(spec, dict):
                    spec = spec.get("version")
                if isinstance(spec, str) and name.lower() != "python" and re.fullmatch(r"=?=?\s*[0-9][^\s,<>!~^*|]*", spec):
                    ver = _parse_version(spec.lstrip("= "))
                    if ver is not None:
                        libs.setdefault(str(canonicalize_name(name)), str(ver))
        return Environment(language="python", libraries=libs, sources=(self.name,))


class RequirementsDetector:
    """``requirements.txt`` exact pins (``name==1.2.3``); includes, URLs and ranges are skipped."""

    name = "requirements.txt"

    def detect(self, project_dir: Path) -> Environment:
        """Parse ``<project_dir>/requirements.txt``; empty environment if absent or malformed."""
        text = _read_text(Path(project_dir) / "requirements.txt")
        if text is None:
            return Environment()
        libs: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.split(" #", 1)[0].strip().rstrip("\\").strip()
            if not line or line.startswith(("#", "-")):
                continue
            if pin := _pin_from_requirement(line):
                libs.setdefault(*pin)
        return _py_env(libs, self.name)


class TomlLockDetector:
    """``poetry.lock`` / ``uv.lock``: ``[[package]]`` tables with ``name`` and ``version``.

    Editable/virtual/directory sources (the project itself) are skipped.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.name = filename

    def detect(self, project_dir: Path) -> Environment:
        """Parse the lockfile; empty environment if absent or malformed."""
        path = Path(project_dir) / self.filename
        if not path.is_file():
            return Environment()
        packages = _read_toml(path).get("package")
        if not isinstance(packages, list):
            return Environment()
        libs: dict[str, str] = {}
        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            name, ver, source = pkg.get("name"), pkg.get("version"), pkg.get("source")
            if isinstance(source, dict) and any(k in source for k in ("editable", "virtual", "directory")):
                continue
            if isinstance(name, str) and (parsed := _parse_version(ver)) is not None:
                libs.setdefault(str(canonicalize_name(name)), str(parsed))
        return _py_env(libs, self.name)


_EXACT_JS_VERSION = re.compile(r"v?=?\s*(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)")


def _exact_js(spec: Any) -> str | None:
    if not isinstance(spec, str):
        return None
    m = _EXACT_JS_VERSION.fullmatch(spec.strip())
    return m.group(1) if m else None


class PackageJsonDetector:
    """``package.json``: language ``javascript`` plus exactly pinned dependencies.

    Caret/tilde/range specs are ignored (no concrete version).  ``engines.node``
    is reported as the runtime only if it is an exact version.
    """

    name = "package.json"

    def detect(self, project_dir: Path) -> Environment:
        """Parse ``<project_dir>/package.json``; empty environment if absent or malformed."""
        path = Path(project_dir) / "package.json"
        data = _read_json(path) if path.is_file() else {}
        if not data:
            return Environment()
        libs: dict[str, str] = {}
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            deps = data.get(section)
            if isinstance(deps, dict):
                for name, spec in deps.items():
                    if (ver := _exact_js(spec)) and isinstance(name, str):
                        libs.setdefault(name.lower(), ver)
        engines = data.get("engines")
        runtime = _exact_js(engines.get("node")) if isinstance(engines, dict) else None
        return Environment(language="javascript", runtime_version=runtime, libraries=libs, sources=(self.name,))


class PackageLockDetector:
    """``package-lock.json`` (lockfile v1, v2, v3): resolved top-level package versions."""

    name = "package-lock.json"

    def detect(self, project_dir: Path) -> Environment:
        """Parse ``<project_dir>/package-lock.json``; empty environment if absent or malformed."""
        path = Path(project_dir) / "package-lock.json"
        data = _read_json(path) if path.is_file() else {}
        if not data:
            return Environment()
        libs: dict[str, str] = {}
        packages = data.get("packages")
        if isinstance(packages, dict):
            for key, meta in packages.items():
                if not (isinstance(key, str) and key.startswith("node_modules/") and isinstance(meta, dict)):
                    continue
                name = key[len("node_modules/"):]
                if "node_modules/" in name:  # nested transitive copy
                    continue
                if isinstance(meta.get("version"), str):
                    libs.setdefault(name.lower(), meta["version"])
        deps = data.get("dependencies")  # lockfile v1
        if isinstance(deps, dict):
            for name, meta in deps.items():
                if isinstance(meta, dict) and isinstance(meta.get("version"), str):
                    libs.setdefault(str(name).lower(), meta["version"])
        if not libs:
            return Environment()
        return Environment(language="javascript", libraries=libs, sources=(self.name,))


def default_detectors(include_interpreter: bool = True) -> list[EnvironmentDetector]:
    """Default detectors in priority order (earlier wins): lockfiles, manifests, interpreter.

    Lockfiles come first because they hold resolved versions; the interpreter is
    last because it describes Lore's own process, not necessarily the project.
    """
    detectors: list[EnvironmentDetector] = [
        TomlLockDetector("uv.lock"),
        TomlLockDetector("poetry.lock"),
        RequirementsDetector(),
        PyprojectDetector(),
        PackageLockDetector(),
        PackageJsonDetector(),
    ]
    if include_interpreter:
        detectors.append(InterpreterDetector())
    return detectors


def detect_environment(
    project_dir: str | Path | None = None,
    detectors: list[EnvironmentDetector] | None = None,
) -> Environment:
    """Run detectors in order and merge results (earlier detectors win on conflict).

    Args:
        project_dir: Project root to inspect (default: current directory).
        detectors: Detector list; defaults to :func:`default_detectors`.

    A detector that raises is skipped, so one bad plugin cannot break detection.
    """
    root = Path(project_dir) if project_dir is not None else Path.cwd()
    env = Environment()
    for detector in detectors if detectors is not None else default_detectors():
        try:
            found = detector.detect(root)
        except Exception:  # noqa: BLE001 - detectors are pluggable; isolate failures
            continue
        env = env.merge(found)
    return env


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


def _check_specifier(spec_text: str, version_text: str | None) -> bool | None:
    """True/False if decidable, ``None`` if the specifier or version is unparsable."""
    version = _parse_version(version_text)
    if version is None:
        return None
    try:
        return SpecifierSet(spec_text).contains(version, prereleases=True)
    except InvalidSpecifier:
        return None


def check_compatibility(compatibility: dict | None, env: Environment) -> CompatResult:
    """Compare concept compatibility metadata with an environment.  Pure; never raises.

    Args:
        compatibility: Metadata dict as defined in :mod:`lore.core.compat`.
            ``None``, legacy, or malformed values are treated as ``unknown``.
        env: The detected environment.

    Returns:
        :class:`CompatResult`.  See the module docstring for decision rules.
        Free-text ``assumptions`` are never machine-checked; if they exist on an
        otherwise ``compatible`` result they are noted in the reason.
    """
    meta = load_compatibility(compatibility)
    language = normalize_language(meta["language"])
    runtime = meta["runtime_version"]
    libraries = meta["libraries"]
    platforms = [p for p in (normalize_platform(p) for p in meta["platforms"]) if p]

    if meta["status"] == "unknown" or not (language or runtime or libraries or platforms):
        return CompatResult(UNKNOWN, "No machine-checkable compatibility constraints are declared for this concept.",
                            missing=("concept compatibility metadata",))

    violated: list[str] = []
    missing: list[str] = []
    satisfied: list[str] = []
    env_language = normalize_language(env.language)

    language_ok = True
    if language:
        if env_language is None:
            missing.append(f"environment language (concept requires {language})")
        elif env_language != language:
            language_ok = False
            violated.append(f"language: requires {language}, environment is {env_language}")
        else:
            satisfied.append(f"language {language}")

    # Runtime and library checks are meaningless against a different language.
    if language_ok:
        if runtime:
            label = f"runtime {runtime}"
            if not env.runtime_version:
                missing.append(f"environment runtime version (concept requires {runtime})")
            else:
                ok = _check_specifier(runtime, env.runtime_version)
                if ok is None:
                    missing.append(f"parsable environment runtime version (got {env.runtime_version!r}; concept requires {runtime})")
                elif ok:
                    satisfied.append(f"{label} (environment {env.runtime_version})")
                else:
                    violated.append(f"runtime_version: requires {runtime}, environment is {env.runtime_version}")
        for lib in libraries:
            name, spec = lib["name"], lib["specifier"]
            key = normalize_library_name(name, env_language or language)
            have = env.libraries.get(key)
            if have is None:
                missing.append(f"library {key} (not detected in environment; concept requires {spec or 'any version'})")
            elif not spec:
                satisfied.append(f"library {key} present ({have})")
            else:
                ok = _check_specifier(spec, have)
                if ok is None:
                    missing.append(f"parsable version of library {key} (got {have!r}; concept requires {spec})")
                elif ok:
                    satisfied.append(f"library {key}{spec} (environment {have})")
                else:
                    violated.append(f"library {key}: requires {spec}, environment has {have}")

    if platforms:
        env_platform = normalize_platform(env.platform)
        if env_platform is None:
            missing.append(f"environment platform (concept supports {', '.join(platforms)})")
        elif env_platform in platforms:
            satisfied.append(f"platform {env_platform}")
        else:
            violated.append(f"platform: supports {', '.join(platforms)}, environment is {env_platform}")

    if violated:
        return CompatResult(INCOMPATIBLE, "Incompatible: " + "; ".join(violated) + ".",
                            tuple(violated), tuple(missing), tuple(satisfied))
    if missing:
        return CompatResult(UNKNOWN, "Cannot verify: " + "; ".join(missing) + ".",
                            (), tuple(missing), tuple(satisfied))
    reason = "All declared constraints are satisfied: " + "; ".join(satisfied) + "."
    if meta["assumptions"]:
        reason += " Free-text assumptions are not machine-checked."
    return CompatResult(COMPATIBLE, reason, (), (), tuple(satisfied))


__all__ = [
    "COMPATIBLE", "INCOMPATIBLE", "UNKNOWN", "CompatResult", "Environment", "EnvironmentDetector",
    "InterpreterDetector", "PackageJsonDetector", "PackageLockDetector", "PyprojectDetector",
    "RequirementsDetector", "TomlLockDetector", "check_compatibility", "default_detectors",
    "detect_environment", "normalize_language", "normalize_library_name", "normalize_platform",
]
