"""Generate synthetic test images for scan pipeline tests."""

import os
from PIL import Image, ImageDraw, ImageFont

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "scan")


def _make_image(lines, filename, size=(600, 100)):
    """Create an image with text lines."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    y = 10
    for line in lines:
        draw.text((10, y), line, fill="black")
        y += 25
    path = os.path.join(FIXTURES_DIR, filename)
    img.save(path)
    return path


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    # 1. Image with sensitive data (phone + ID card)
    _make_image(
        ["Phone: 13800138000", "ID: 110101199001011234"],
        "sensitive.png",
        size=(600, 80),
    )

    # 2. Image with no sensitive data
    _make_image(
        ["No sensitive info here.", "Just plain text."],
        "no_match.png",
        size=(500, 80),
    )

    # 3. Image with email
    _make_image(
        ["Contact: zhang@example.com", "Phone: 13900139000"],
        "email_phone.png",
        size=(500, 80),
    )

    # 4. Minimal single-line image
    _make_image(
        ["Tel 13800138000 end"],
        "single_line.png",
        size=(400, 50),
    )

    print(f"Generated fixtures in {FIXTURES_DIR}")
    for f in os.listdir(FIXTURES_DIR):
        print(f"  {f}")


if __name__ == "__main__":
    main()
