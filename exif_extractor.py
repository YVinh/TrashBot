"""Extract GPS coordinates from image EXIF metadata."""

from PIL import Image
from PIL.ExifTags import TAGS
from pathlib import Path


def get_exif_data(image_path: str) -> dict:
    """
    Extract EXIF data from image.

    Args:
        image_path: Path to the image file

    Returns:
        Dictionary of EXIF data with tag names as keys
    """
    try:
        image = Image.open(image_path)
        exif_data = image.getexif()

        if not exif_data:
            return {}

        # Convert numeric tag IDs to human-readable names
        readable_exif = {}
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, tag_id)
            readable_exif[tag_name] = value

        return readable_exif
    except Exception as e:
        print(f"⚠️  Could not read EXIF data: {e}")
        return {}


def convert_to_degrees(value):
    """Convert GPS coordinates from DMS (degrees, minutes, seconds) to decimal degrees."""
    if isinstance(value, tuple) and len(value) == 3:
        degrees = float(value[0])
        minutes = float(value[1]) / 60.0
        seconds = float(value[2]) / 3600.0
        return degrees + minutes + seconds
    return None


def extract_gps_coordinates(image_path: str) -> tuple or None:
    """
    Extract GPS coordinates from image EXIF data.

    Args:
        image_path: Path to the image file

    Returns:
        Tuple of (latitude, longitude) in decimal format, or None if not found
    """
    try:
        image = Image.open(image_path)
        exif_data = image.getexif()

        if not exif_data:
            return None

        # Look for GPS IFD (Image File Directory)
        gps_ifd = exif_data.get_ifd(0x8825) if hasattr(exif_data, 'get_ifd') else None

        if not gps_ifd:
            return None

        gps_data = {}
        for tag_id, value in gps_ifd.items():
            tag_name = TAGS.get(tag_id, tag_id)
            gps_data[tag_name] = value

        # Extract latitude and longitude
        lat_ref = gps_data.get("GPSLatitudeRef", "N")
        lat = gps_data.get("GPSLatitude")
        lon_ref = gps_data.get("GPSLongitudeRef", "E")
        lon = gps_data.get("GPSLongitude")

        if lat and lon:
            latitude = convert_to_degrees(lat)
            longitude = convert_to_degrees(lon)

            # Apply reference direction (S and W are negative)
            if lat_ref == "S":
                latitude = -latitude
            if lon_ref == "W":
                longitude = -longitude

            return (latitude, longitude)

        return None

    except Exception as e:
        # Silently fail if EXIF extraction doesn't work
        return None


def has_gps_metadata(image_path: str) -> bool:
    """Check if image has GPS metadata."""
    return extract_gps_coordinates(image_path) is not None
