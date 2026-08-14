"""Derive the committed icon assets from the hex-sticker masters.

    python scripts/make_icons.py            # masters in the repo root
    python scripts/make_icons.py --src DIR

Requires Pillow, which the dev and docs installs already pull in. The masters are
gitignored; see CLAUDE.md for which one feeds which asset, and why.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# (master, output, size) — square unless noted.
TARGETS = [
    ("biwt_icon_mini.png", "src/biwt/gui/icons/biwt.png", 256),
    ("biwt_icon_mini.png", "docs/assets/logo.png", 256),
    ("biwt_icon_mini.png", "docs/assets/favicon.png", 64),
    # Width-bound rather than square: it sits inline at the top of the README, so
    # its own aspect is what should survive.
    ("biwt_icon.png", "docs/assets/biwt-sticker.png", None),
    # GitHub's repo social preview. Upload by hand under Settings -> Social
    # preview; there is no file location the repo picks up on its own.
    ("biwt_icon.png", "docs/assets/social-preview.png", "github"),
]
STICKER_WIDTH = 420

# GitHub's own template: 1280x640, and it asks for a 40 pt border around anything
# that matters because the card is cropped at some sizes. Doubled to 80 px here,
# since the sticker carries the wordmark and has nothing to gain from filling the
# frame edge to edge.
GH_CARD = (1280, 640)
GH_SAFE = 80
GH_GROUND = (0, 150, 136, 255)   # the site header's teal


def square_pad(im):
    from PIL import Image

    side = max(im.size)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default=".", help="directory holding the masters")
    parser.add_argument("--repo", default=".", help="repository root to write into")
    args = parser.parse_args(argv)

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required: pip install pillow", file=sys.stderr)
        return 1

    src, repo = Path(args.src), Path(args.repo)
    missing = {m for m, _, _ in TARGETS if not (src / m).exists()}
    if missing:
        print(f"masters not found in {src}: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    for master, out_rel, size in TARGETS:
        im = Image.open(src / master).convert("RGBA")
        if size == "github":
            # Fit the sticker inside the safe area, centred on the ground. No text
            # is drawn: the sticker already carries the name and the tagline, so
            # this needs no font and cannot render one differently per machine.
            card = Image.new("RGBA", GH_CARD, GH_GROUND)
            room = (GH_CARD[0] - 2 * GH_SAFE, GH_CARD[1] - 2 * GH_SAFE)
            art = im.copy()
            art.thumbnail(room, Image.LANCZOS)
            card.alpha_composite(art, ((GH_CARD[0] - art.width) // 2,
                                       (GH_CARD[1] - art.height) // 2))
            im = card
        elif size is None:
            h = round(im.height * STICKER_WIDTH / im.width)
            im = im.resize((STICKER_WIDTH, h), Image.LANCZOS)
        else:
            im = square_pad(im).resize((size, size), Image.LANCZOS)
        out = repo / out_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, optimize=True)
        print(f"  {out_rel:36s} {im.width}x{im.height}  {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
