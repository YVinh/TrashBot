"""Tool functions exposed to the Marc agent via the Anthropic tool runner."""

from anthropic import beta_tool

from exif_extractor import extract_gps_coordinates
from tags_mentions import generate_hashtags, get_location_from_coords, format_hashtags


@beta_tool
def extract_gps(image_path: str) -> str:
    """Read GPS coordinates from an image's EXIF metadata and resolve them to a known city.

    Args:
        image_path: Path to the image file on disk
    """
    coords = extract_gps_coordinates(image_path)
    if not coords:
        return "No GPS metadata found in this image."
    lat, lon = coords
    location = get_location_from_coords(lat, lon)
    return f"GPS: {lat:.4f}, {lon:.4f} — resolved location: {location}"


@beta_tool
def get_hashtags(location: str) -> str:
    """Get up to 4 relevant hashtags for a location, ready to append to an X post.

    Args:
        location: A city name such as 'Brussels', 'Amsterdam', 'Antwerp', or 'Europe' as a fallback
    """
    tags = generate_hashtags(location)[:4]
    return format_hashtags(tags)
