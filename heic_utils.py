"""Shared, version-tolerant HEIC/HEIF loading.

pillow-heif's API has changed across versions (the legacy `read()` function used
in earlier versions of this project was removed in 1.x), and some HEIC files trip
up one loading path but not another. Try a few strategies before giving up.
"""

from PIL import Image


def is_heic(image_path: str) -> bool:
    return image_path.lower().endswith((".heic", ".heif"))


def open_heic(image_path: str) -> Image.Image:
    """Open a HEIC/HEIF file as a Pillow Image, trying multiple pillow-heif APIs."""
    import pillow_heif

    errors = []

    if hasattr(pillow_heif, "open_heif"):
        try:
            heif_file = pillow_heif.open_heif(image_path, convert_hdr_to_8bit=True)
            return heif_file.to_pillow()
        except Exception as e:
            errors.append(f"open_heif: {e}")

    try:
        pillow_heif.register_heif_opener()
        return Image.open(image_path)
    except Exception as e:
        errors.append(f"register_heif_opener: {e}")

    raise ValueError(
        "Cannot open HEIC file (tried: " + "; ".join(errors) + "). "
        "Try converting to JPEG first using Preview or ImageMagick."
    )


def get_heic_exif(image_path: str):
    """Best-effort EXIF extraction for a HEIC/HEIF file, or None."""
    try:
        return open_heic(image_path).getexif()
    except Exception:
        return None
