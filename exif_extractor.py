"""Extract GPS coordinates from image EXIF metadata."""

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from pathlib import Path

# Register HEIC opener for PIL
try:
    import pillow_heif
    pillow_heif.register_heic_opener()
except ImportError:
    pass


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
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            degrees = float(value[0])
            minutes = float(value[1]) / 60.0
            seconds = float(value[2]) / 3600.0
            return degrees + minutes + seconds
        except (TypeError, ValueError):
            return None
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

        # For HEIC files, get EXIF from the image object directly
        if image_path.lower().endswith(('.heic', '.heif')):
            try:
                exif_data = image.getexif()
            except:
                # Try alternate method for HEIC
                exif_data = image.info.get('exif', None)
                if exif_data:
                    from PIL.Image import Exif
                    exif_obj = Exif()
                    exif_obj.load(exif_data)
                    exif_data = exif_obj
        else:
            exif_data = image.getexif()

        if not exif_data:
            return None

        # Try method 1: Using get_ifd (modern PIL versions)
        try:
            gps_ifd = exif_data.get_ifd(0x8825)
            if gps_ifd:
                gps_data = {}
                for tag_id, value in gps_ifd.items():
                    tag_name = GPSTAGS.get(tag_id, tag_id)
                    gps_data[tag_name] = value

                lat = gps_data.get("GPSLatitude")
                lon = gps_data.get("GPSLongitude")
                lat_ref = gps_data.get("GPSLatitudeRef", "N")
                lon_ref = gps_data.get("GPSLongitudeRef", "E")

                if lat and lon:
                    latitude = convert_to_degrees(lat)
                    longitude = convert_to_degrees(lon)

                    if latitude is not None and longitude is not None:
                        # Apply reference direction (S and W are negative)
                        if lat_ref == "S":
                            latitude = -latitude
                        if lon_ref == "W":
                            longitude = -longitude

                        return (latitude, longitude)
        except (AttributeError, KeyError, TypeError):
            pass

        # Try method 2: Direct tag search (fallback for older versions)
        try:
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id)
                if tag_name == "GPSInfo":
                    gps_data = {}
                    for sub_tag_id, sub_value in value.items():
                        sub_tag_name = GPSTAGS.get(sub_tag_id, sub_tag_id)
                        gps_data[sub_tag_name] = sub_value

                    lat = gps_data.get("GPSLatitude")
                    lon = gps_data.get("GPSLongitude")
                    lat_ref = gps_data.get("GPSLatitudeRef", "N")
                    lon_ref = gps_data.get("GPSLongitudeRef", "E")

                    if lat and lon:
                        latitude = convert_to_degrees(lat)
                        longitude = convert_to_degrees(lon)

                        if latitude is not None and longitude is not None:
                            if lat_ref == "S":
                                latitude = -latitude
                            if lon_ref == "W":
                                longitude = -longitude

                            return (latitude, longitude)
        except (AttributeError, KeyError, TypeError):
            pass

        return None

    except Exception as e:
        return None


def has_gps_metadata(image_path: str) -> bool:
    """Check if image has GPS metadata."""
    return extract_gps_coordinates(image_path) is not None

