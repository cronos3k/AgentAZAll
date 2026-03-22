#!/usr/bin/env python3
"""
AgentAZAll / AgentAZClaw Image Post-Processor

Takes raw images from Google ImageFX (which often adds sepia/cream tints)
and produces clean black-on-white output suitable for web and print.

Pipeline:
1. Remove sepia/cream tint → pure black ink on white paper
2. Boost contrast for crisp line art
3. Optionally make white background transparent (for web overlays)
4. Resize to max 1920px wide (2560px for ultrawide banners)
5. Save optimized PNG + WebP

Usage:
    python post_process_images.py input.png                    # process one file
    python post_process_images.py input_dir/ output_dir/       # batch process
    python post_process_images.py input.png --no-transparency  # keep white bg
    python post_process_images.py input.png --preview          # show before/after
"""

import os
import sys
import argparse
from pathlib import Path

try:
    from PIL import Image, ImageEnhance, ImageFilter
    import numpy as np
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)


# ── Configuration ───────────────────────────────────────────────────

MAX_WIDTH = 1920
MAX_WIDTH_BANNER = 2560       # for 21:9 aspect ratios
WEBP_QUALITY = 88
TRANSPARENCY_THRESHOLD = 245  # RGB values >= this become transparent

# Sepia removal: these define the "warm tint" color space to neutralize
# ImageFX typically produces a warm cream/sepia cast with these properties:
#   - Red channel is slightly higher than Green
#   - Green channel is slightly higher than Blue
#   - The paper background is #F5F0E8 or similar instead of #FFFFFF
SEPIA_WARMTH_THRESHOLD = 8    # max R-B difference to consider "sepia-tinted"


def remove_sepia(img: Image.Image) -> Image.Image:
    """Remove sepia/cream tint, producing pure black-on-white output.

    Method: Convert to LAB color space (separating luminance from color),
    then desaturate the color channels while preserving luminance.
    This keeps the engraving detail (dark lines) but removes the warm tint.
    After desaturation, map the lightest values to pure white.
    """
    arr = np.array(img.convert("RGB")).astype(np.float64)

    # Step 1: Detect if image has a sepia/warm tint
    # Sample background pixels (corners + edges)
    h, w = arr.shape[:2]
    corners = np.concatenate([
        arr[0:20, 0:20].reshape(-1, 3),
        arr[0:20, w-20:w].reshape(-1, 3),
        arr[h-20:h, 0:20].reshape(-1, 3),
        arr[h-20:h, w-20:w].reshape(-1, 3),
    ])
    bg_mean = corners.mean(axis=0)  # [R, G, B] average of background

    r_b_diff = bg_mean[0] - bg_mean[2]  # red minus blue
    is_sepia = r_b_diff > SEPIA_WARMTH_THRESHOLD

    if not is_sepia:
        print("    No sepia tint detected — skipping color correction")
        return img

    print(f"    Sepia detected (R-B={r_b_diff:.1f}). Background mean: "
          f"R={bg_mean[0]:.0f} G={bg_mean[1]:.0f} B={bg_mean[2]:.0f}")

    # Step 2: Convert to grayscale using luminance weights
    # (preserves perceived brightness of the engraving lines)
    gray = (0.2989 * arr[:, :, 0] +
            0.5870 * arr[:, :, 1] +
            0.1140 * arr[:, :, 2])

    # Step 3: Stretch contrast — map the background luminance to 255
    # and the darkest ink to near-0
    bg_lum = np.percentile(gray, 95)  # 95th percentile = background level
    ink_lum = np.percentile(gray, 2)   # 2nd percentile = darkest ink

    if bg_lum > ink_lum:
        # Linear stretch: ink_lum→0, bg_lum→255
        gray = (gray - ink_lum) / (bg_lum - ink_lum) * 255.0
        gray = np.clip(gray, 0, 255)

    # Step 4: Apply a slight curves adjustment to crush near-whites to pure white
    # This eliminates any residual warm cast in the "paper" areas
    white_threshold = 220
    mask_near_white = gray > white_threshold
    gray[mask_near_white] = 255.0

    # Step 5: Rebuild as RGB (all channels identical = pure grayscale)
    result = np.stack([gray, gray, gray], axis=2).astype(np.uint8)
    return Image.fromarray(result)


def boost_contrast(img: Image.Image, factor: float = 1.3) -> Image.Image:
    """Boost contrast for crisper line art."""
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(factor)


def make_transparent(img: Image.Image, threshold: int = TRANSPARENCY_THRESHOLD) -> Image.Image:
    """Make near-white pixels transparent."""
    arr = np.array(img.convert("RGBA"))
    mask = (
        (arr[:, :, 0] >= threshold) &
        (arr[:, :, 1] >= threshold) &
        (arr[:, :, 2] >= threshold)
    )
    arr[mask, 3] = 0
    return Image.fromarray(arr)


def resize(img: Image.Image) -> Image.Image:
    """Resize to max width, preserving aspect ratio."""
    w, h = img.size
    ratio = w / h
    max_w = MAX_WIDTH_BANNER if ratio > 2.0 else MAX_WIDTH

    if w > max_w:
        new_h = int(h * (max_w / w))
        img = img.resize((max_w, new_h), Image.LANCZOS)
    return img


def process_single(input_path: str, output_dir: str,
                   transparency: bool = True,
                   contrast: float = 1.3) -> dict:
    """Process a single image through the full pipeline."""
    fname = os.path.basename(input_path)
    stem = os.path.splitext(fname)[0]

    print(f"  Processing: {fname}")

    # Load
    img = Image.open(input_path)
    original_size = img.size
    print(f"    Original: {original_size[0]}x{original_size[1]}")

    # 1. Remove sepia
    img = remove_sepia(img)

    # 2. Boost contrast
    if contrast > 1.0:
        img = boost_contrast(img, contrast)
        print(f"    Contrast: {contrast}x")

    # 3. Resize
    img = resize(img)
    print(f"    Resized: {img.size[0]}x{img.size[1]}")

    # 4. Transparency (optional)
    if transparency:
        img = make_transparent(img)
        print(f"    Transparency: applied (threshold={TRANSPARENCY_THRESHOLD})")

    # 5. Save PNG
    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, f"{stem}.png")
    img.save(png_path, "PNG", optimize=True)
    png_size = os.path.getsize(png_path)

    # 6. Save WebP
    webp_path = os.path.join(output_dir, f"{stem}.webp")
    # WebP doesn't support RGBA well at high compression — save RGB for non-transparent
    if transparency:
        img.save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
    else:
        img.convert("RGB").save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
    webp_size = os.path.getsize(webp_path)

    print(f"    PNG: {png_size // 1024} KB | WebP: {webp_size // 1024} KB")

    return {
        "file": fname,
        "original_size": original_size,
        "output_size": img.size,
        "png_kb": png_size // 1024,
        "webp_kb": webp_size // 1024,
    }


def process_batch(input_dir: str, output_dir: str, **kwargs) -> list:
    """Process all PNG/JPG images in a directory."""
    results = []
    extensions = {".png", ".jpg", ".jpeg", ".webp"}

    files = sorted(
        f for f in Path(input_dir).iterdir()
        if f.suffix.lower() in extensions
    )

    if not files:
        print(f"  No image files found in {input_dir}")
        return results

    print(f"\n  Processing {len(files)} images from {input_dir}\n")

    for f in files:
        try:
            r = process_single(str(f), output_dir, **kwargs)
            results.append(r)
        except Exception as e:
            print(f"  ERROR processing {f.name}: {e}")

    # Summary
    total_png = sum(r["png_kb"] for r in results)
    total_webp = sum(r["webp_kb"] for r in results)
    print(f"\n  Done: {len(results)} images processed")
    print(f"  Total PNG: {total_png:,} KB | Total WebP: {total_webp:,} KB")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="AgentAZAll/AgentAZClaw image post-processor: "
                    "remove sepia tint, boost contrast, resize, save PNG+WebP"
    )
    parser.add_argument("input", help="Input image file or directory")
    parser.add_argument("output", nargs="?", default="./processed",
                        help="Output directory (default: ./processed)")
    parser.add_argument("--no-transparency", action="store_true",
                        help="Keep white background (don't make transparent)")
    parser.add_argument("--contrast", type=float, default=1.3,
                        help="Contrast boost factor (default: 1.3, 1.0=no change)")
    parser.add_argument("--preview", action="store_true",
                        help="Show before/after comparison (requires display)")

    args = parser.parse_args()

    if os.path.isdir(args.input):
        process_batch(args.input, args.output,
                      transparency=not args.no_transparency,
                      contrast=args.contrast)
    elif os.path.isfile(args.input):
        process_single(args.input, args.output,
                       transparency=not args.no_transparency,
                       contrast=args.contrast)
    else:
        print(f"Not found: {args.input}")
        sys.exit(1)


if __name__ == "__main__":
    main()
