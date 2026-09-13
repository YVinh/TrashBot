from comment_generator import get_image_media_type


def test_get_image_media_type_known_extensions():
    assert get_image_media_type("photo.jpg") == "image/jpeg"
    assert get_image_media_type("photo.PNG") == "image/png"
    assert get_image_media_type("photo.webp") == "image/webp"


def test_get_image_media_type_heic_maps_to_jpeg():
    assert get_image_media_type("photo.heic") == "image/jpeg"
    assert get_image_media_type("photo.HEIF") == "image/jpeg"


def test_get_image_media_type_unknown_extension_defaults_to_jpeg():
    assert get_image_media_type("photo.bmp") == "image/jpeg"
