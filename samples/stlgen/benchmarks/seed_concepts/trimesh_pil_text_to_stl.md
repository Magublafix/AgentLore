---
name: PIL + scikit-image + trimesh text-to-STL pipeline
type: library
when_to_use: When building a CLI or script that converts a text string into a 3D-printable STL file with raised letters
tags: trimesh,PIL,skimage,shapely,3d-printing,text-to-mesh,STL
---

Complete verified pipeline for converting a text string into a 3D-printable STL file with raised letters.

## Dependencies

```
trimesh, Pillow, scikit-image, shapely, numpy
```

## The correct approach

1. Render text as a grayscale bitmap using PIL/Pillow
2. Extract letter outlines with `skimage.measure.find_contours()`
3. Convert contours to Shapely polygons (note row/col axis flip)
4. Extrude each polygon with `trimesh.creation.extrude_polygon()`
5. Merge all letter meshes with `trimesh.util.concatenate()`

## Verified working APIs

- `PIL.ImageFont.load_default()` or `PIL.ImageFont.truetype(path, size)`
- `PIL.ImageDraw.Draw(img).text((x, y), text, fill=255)`
- `skimage.measure.find_contours(np.array(img), level=0.5)` — returns list of `(N, 2)` float arrays in **(row, col)** order
- Flip axes: `contour[:, ::-1]` converts (row, col) → (x, y) for Shapely
- `shapely.geometry.Polygon(xy_points)` — creates polygon from (x, y) points
- `trimesh.creation.extrude_polygon(polygon, height)` — extrudes a 2D Shapely polygon into a 3D mesh
- `trimesh.util.concatenate(meshes)` — merges a list of meshes into one
- `mesh.export('output.stl')` — saves as binary STL

## APIs that do NOT exist (common hallucinations)

- `trimesh.contour` — does not exist
- `trimesh.triangulation` — does not exist
- `trimesh.creation.text()` — does not exist
- `trimesh.creation.from_contours()` — does not exist
- `numpy.ndarray.is_empty` — does not exist; use `polygon.is_empty` on a Shapely object

## Complete minimal implementation

```python
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage import measure
from shapely.geometry import Polygon
import trimesh

def text_to_mesh(text: str, height: float = 10.0, font_size: int = 72) -> trimesh.Trimesh:
    # Render text to grayscale bitmap
    w = max(len(text) * font_size, 64)
    img = Image.new("L", (w, font_size * 2), 0)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    draw.text((4, font_size // 4), text, fill=255, font=font)

    arr = np.array(img)

    # Extract contours — returned as (row, col) arrays
    contours = measure.find_contours(arr, level=0.5)

    meshes = []
    for contour in contours:
        xy = contour[:, ::-1]          # flip (row,col) → (x,y)
        poly = Polygon(xy)
        if not poly.is_valid or poly.area < 50:
            continue
        meshes.append(trimesh.creation.extrude_polygon(poly, height))

    if not meshes:
        raise ValueError(f"No renderable glyphs found for {text!r}")
    return trimesh.util.concatenate(meshes)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Convert text to STL")
    parser.add_argument("text", help="Text string (max 15 chars)")
    parser.add_argument("-o", "--output", default="output.stl")
    args = parser.parse_args()
    if not args.text or len(args.text) > 15:
        print("Error: String must be between 1 and 15 characters.", file=sys.stderr)
        sys.exit(1)
    mesh = text_to_mesh(args.text)
    mesh.export(args.output)

if __name__ == "__main__":
    main()
```

## pyproject.toml entry point

```toml
[project.scripts]
text2stl = "text2stl.cli:main"
```
