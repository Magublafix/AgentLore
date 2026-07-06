"""
Acceptance test suite for the text2stl CLI.
Tests run against the installed `text2stl` command in the working environment.

Run with:
  pip install -e .
  pytest tests/test_text2stl_cli.py -v
"""
from __future__ import annotations

import subprocess
import pytest
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text2stl(*args, check=True, timeout=60):
    result = subprocess.run(
        ["text2stl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        pytest.fail(
            f"text2stl {' '.join(args)} exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _load_mesh(stl_path):
    import trimesh
    mesh = trimesh.load(str(stl_path), force="mesh")
    assert mesh is not None and len(mesh.vertices) > 0, \
        f"Failed to load mesh from {stl_path}"
    return mesh


def _stl_cross_section_bitmap(stl_path, size=(400, 100)):
    """Slice mesh at mid-height and rasterize cross-section to a normalized PIL image."""
    from PIL import Image
    mesh = _load_mesh(stl_path)
    z_mid = float(mesh.bounds[:, 2].mean())
    section = mesh.section(plane_origin=[0, 0, z_mid], plane_normal=[0, 0, 1])
    if section is None:
        return None
    section_2d, _ = section.to_planar()
    bounds_range = section_2d.bounds[1] - section_2d.bounds[0]
    max_extent = float(bounds_range.max())
    if max_extent <= 0:
        return None
    pitch = max_extent / max(size)
    img = section_2d.rasterize(pitch=pitch)
    return img.resize(size, Image.LANCZOS).convert("L")


def _text_reference_bitmap(text, size=(400, 100)):
    """Render text, then crop tightly to glyph bounds before scaling to `size`.

    `_stl_cross_section_bitmap` rasterizes a mesh cross-section using a pitch
    derived from the section's own (geometry-tight) bounding box, so the STL
    side of the comparison always fills the frame edge-to-edge with no
    incidental padding. If this reference were left at its natural centered
    size within `size`, the two images would be at different effective
    scales and IoU would penalize correctly-shaped text just for being
    smaller-with-padding rather than malformed. Cropping to the tight glyph
    bbox here matches that convention on both sides. See benchmarks/README.md
    "IoU test scale-normalization fix" for the empirical before/after.
    """
    from PIL import Image, ImageDraw, ImageFont
    canvas = (size[0] * 4, size[1] * 4)
    img = Image.new("L", canvas, 0)
    draw = ImageDraw.Draw(img)
    font_size = int(canvas[1] * 0.75)
    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_path, font_size)
            break
        except (IOError, OSError):
            pass
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = max(0, (canvas[0] - tw) // 2)
    y = max(0, (canvas[1] - th) // 2)
    draw.text((x, y), text, fill=255, font=font)
    tight = img.getbbox()
    if tight is None:
        return img.resize(size, Image.LANCZOS)
    return img.crop(tight).resize(size, Image.LANCZOS)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    intersection = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(intersection) / float(union) if union > 0 else 0.0


def _band_profile(a: np.ndarray, axis: int, n: int = 20) -> np.ndarray:
    """Mean ink density in `n` equal bands along `axis` (0=columns, 1=rows).

    Captures *where* ink sits along an axis, not just how much. Unlike IoU
    on the tight-cropped-and-rescaled image, this is sensitive to which
    fraction of the glyph's extent is actually present — a glyph missing a
    contiguous chunk (e.g. truncated by a canvas edge) gets its remaining
    features compressed/redistributed into the band layout in a way that no
    longer lines up with an intact reference, even after independent
    rescaling. See `_min_band_correlation` / "truncation-detection fix" in
    benchmarks/README.md.
    """
    # axis=1 means "bands along rows" (top-to-bottom), so the band count is
    # taken from the row dimension (shape[0]); axis=0 means "bands along
    # columns" (left-to-right), taken from shape[1].
    length = a.shape[0] if axis == 1 else a.shape[1]
    edges = np.linspace(0, length, n + 1).astype(int)
    bands = []
    for i in range(n):
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            bands.append(0.0)
            continue
        sl = a[lo:hi, :] if axis == 1 else a[:, lo:hi]
        bands.append(float(sl.mean()))
    return np.array(bands)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation, treating a constant (zero-variance) series as
    uncorrelated (0.0) instead of raising/NaN-ing — a fully solid or fully
    empty band profile carries no shape information either way."""
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _min_band_correlation(arr_stl: np.ndarray, arr_ref: np.ndarray) -> float:
    """Worst-of-(row-profile, column-profile) correlation between the STL
    cross-section and the reference, best-of-(normal, vertically-flipped)
    orientation.

    Both profiles are computed on the same tight-cropped-and-rescaled
    bitmaps the IoU test uses, so legitimate scale/padding differences
    wash out exactly as they do for IoU (a uniformly-scaled, untruncated
    glyph reproduces the reference's band profile almost exactly on both
    axes). Truncation, however, removes a contiguous chunk of the glyph
    along one axis *before* the independent rescale — that reshuffles
    where remaining features (crossbars, counters, serifs) land along that
    axis, which IoU's whole-image overlap can't distinguish from "smaller
    but correctly shaped" but which band correlation on the affected axis
    picks up sharply (the row profile no longer resembles the reference's
    row profile even though the rescaled image is now the same size).
    Taking the min across axes ensures truncation on *either* axis is
    caught, since a glyph clipped on one axis only is otherwise free to
    pass on the other.
    """
    best = -1.0
    for candidate in (arr_stl, np.flipud(arr_stl)):
        row_corr = _safe_corr(_band_profile(candidate, axis=1), _band_profile(arr_ref, axis=1))
        col_corr = _safe_corr(_band_profile(candidate, axis=0), _band_profile(arr_ref, axis=0))
        best = max(best, min(row_corr, col_corr))
    return best


# ---------------------------------------------------------------------------
# Basic invocation
# ---------------------------------------------------------------------------

class TestInvocation:
    def test_single_char(self, tmp_path):
        out = tmp_path / "a.stl"
        text2stl("A", "-o", str(out))
        assert out.exists() and out.stat().st_size > 0

    def test_five_chars(self, tmp_path):
        out = tmp_path / "hello.stl"
        text2stl("HELLO", "-o", str(out))
        assert out.exists() and out.stat().st_size > 0

    def test_max_length(self, tmp_path):
        out = tmp_path / "max.stl"
        text2stl("ABCDEFGHIJKLMNO", "-o", str(out))  # 15 chars
        assert out.exists() and out.stat().st_size > 0

    def test_default_output_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        text2stl("HI")
        stl_files = list(tmp_path.glob("*.stl"))
        assert len(stl_files) >= 1, "No .stl file written to cwd when -o omitted"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_empty_string_rejected(self, tmp_path):
        out = tmp_path / "out.stl"
        result = text2stl("", "-o", str(out), check=False)
        assert result.returncode != 0, "Empty string should be rejected"

    def test_too_long_rejected(self, tmp_path):
        out = tmp_path / "out.stl"
        result = text2stl("ABCDEFGHIJKLMNOP", "-o", str(out), check=False)  # 16 chars
        assert result.returncode != 0, "String of 16 chars should be rejected"


# ---------------------------------------------------------------------------
# STL validity
# ---------------------------------------------------------------------------

class TestSTLValidity:
    @pytest.fixture
    def hello_stl(self, tmp_path):
        out = tmp_path / "hello.stl"
        text2stl("HELLO", "-o", str(out))
        return out

    def test_stl_loads_without_error(self, hello_stl):
        mesh = _load_mesh(hello_stl)
        assert len(mesh.faces) > 0

    def test_mesh_is_watertight(self, hello_stl):
        mesh = _load_mesh(hello_stl)
        assert mesh.is_watertight, (
            "Mesh is not water-tight — not 3D printable. "
            "Ensure the mesh is a closed manifold with no open edges."
        )

    def test_mesh_has_positive_volume(self, hello_stl):
        mesh = _load_mesh(hello_stl)
        assert mesh.volume > 0, (
            f"Mesh volume is {mesh.volume:.4f} — expected positive. "
            "Face normals may be inverted."
        )

    def test_no_degenerate_triangles(self, hello_stl):
        mesh = _load_mesh(hello_stl)
        min_area = float(mesh.area_faces.min())
        assert min_area > 0, (
            f"Mesh contains degenerate (zero-area) triangles — "
            f"min triangle area: {min_area}"
        )


# ---------------------------------------------------------------------------
# Dimension scaling
# ---------------------------------------------------------------------------

class TestDimensions:
    def test_width_scales_with_char_count(self, tmp_path):
        out1 = tmp_path / "a.stl"
        out5 = tmp_path / "hello.stl"
        text2stl("A", "-o", str(out1))
        text2stl("HELLO", "-o", str(out5))
        mesh1 = _load_mesh(out1)
        mesh5 = _load_mesh(out5)
        w1 = float(mesh1.bounds[1][0] - mesh1.bounds[0][0])
        w5 = float(mesh5.bounds[1][0] - mesh5.bounds[0][0])
        assert w5 > w1, (
            f"5-char mesh width ({w5:.2f}) is not wider than 1-char mesh ({w1:.2f})"
        )


# ---------------------------------------------------------------------------
# Character shape verification
# ---------------------------------------------------------------------------

class TestCharacterShapes:
    def test_cross_section_is_nonempty(self, tmp_path):
        out = tmp_path / "hello.stl"
        text2stl("HELLO", "-o", str(out))
        mesh = _load_mesh(out)
        z_mid = float(mesh.bounds[:, 2].mean())
        section = mesh.section(plane_origin=[0, 0, z_mid], plane_normal=[0, 0, 1])
        assert section is not None, (
            "No cross-section at mid-height — mesh may not be extruded text. "
            "Check that characters have non-zero height."
        )

    def test_character_shapes_match_text(self, tmp_path):
        """
        Mid-height cross-section IoU vs PIL-rendered reference must be >= 0.25.

        We try both normal and vertically-flipped orientations to survive the
        difference between STL (Y-up) and PIL (Y-down) coordinate conventions.
        """
        out = tmp_path / "hello.stl"
        text2stl("HELLO", "-o", str(out))

        stl_img = _stl_cross_section_bitmap(out)
        if stl_img is None:
            pytest.fail("Could not rasterize cross-section — check mesh height")

        ref_img = _text_reference_bitmap("HELLO")
        arr_stl = np.array(stl_img) > 127
        arr_ref = np.array(ref_img) > 127

        iou = max(
            _iou(arr_stl, arr_ref),
            _iou(np.flipud(arr_stl), arr_ref),
        )

        assert iou >= 0.25, (
            f"Character shape IoU {iou:.3f} < 0.25 — "
            "cross-section does not resemble 'HELLO'. "
            "Letters may be malformed, missing, or in wrong order."
        )

    def test_character_shapes_not_truncated(self, tmp_path):
        """
        Catches truncation (e.g. glyphs clipped by a canvas/render boundary)
        that survives `test_character_shapes_match_text`'s IoU check.

        That test crops both the STL cross-section and the PIL reference to
        their own tight bounding box before rescaling to a common frame
        (deliberately, to tolerate legitimate scale/padding differences —
        see `_text_reference_bitmap`'s docstring). The side effect: a glyph
        that's missing a meaningful chunk of its vertical (or horizontal)
        extent still gets stretched to fill the frame, and the surviving
        fragment can incidentally resemble the full glyph well enough to
        clear the IoU threshold. A real generated implementation hit this:
        an oversized font combined with bottom-anchored placement clipped
        the bottom ~25-45% of every glyph against the canvas edge, and the
        truncated cross-section still passed IoU >= 0.25.

        This test checks `_min_band_correlation` instead: it divides the
        same tight-cropped bitmaps into bands along each axis and compares
        ink-density profiles. Truncation removes a contiguous chunk of the
        glyph along one axis *before* the crop/rescale, which reshuffles
        where remaining features land in the band layout — a signal IoU's
        whole-image overlap can't see. Legitimate scale/padding variation
        leaves both profiles essentially unchanged (both sides are already
        tight-cropped), so it doesn't reintroduce the original IoU
        false-negative. See benchmarks/README.md "truncation-detection fix"
        for the empirical calibration.
        """
        out = tmp_path / "hello.stl"
        text2stl("HELLO", "-o", str(out))

        stl_img = _stl_cross_section_bitmap(out)
        if stl_img is None:
            pytest.fail("Could not rasterize cross-section — check mesh height")

        ref_img = _text_reference_bitmap("HELLO")
        arr_stl = np.array(stl_img) > 127
        arr_ref = np.array(ref_img) > 127

        min_corr = _min_band_correlation(arr_stl, arr_ref)

        assert min_corr >= 0.3, (
            f"Band-profile correlation {min_corr:.3f} < 0.3 — cross-section "
            "looks truncated (missing a chunk of its vertical or horizontal "
            "extent) even though it may still pass the IoU shape check. "
            "Check for clipping against canvas/render boundaries — e.g. "
            "font size too large relative to canvas combined with "
            "edge-anchored text placement."
        )
