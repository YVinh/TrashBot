import base64
import os
from pathlib import Path
from anthropic import Anthropic

# Register HEIC opener for PIL
try:
    from pillow_heif import register_heic_opener
    register_heic_opener()
except (ImportError, AttributeError):
    pass

def load_image_as_base64(image_path: str) -> str:
    """Convert image file to base64 string, converting HEIC to JPEG if needed."""
    from io import BytesIO
    from PIL import Image

    image = Image.open(image_path)

    # Convert HEIC/HEIF to JPEG for compatibility
    if image_path.lower().endswith(('.heic', '.heif')):
        # Convert to RGB if necessary (HEIC might be RGBA)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background

        # Save as JPEG to bytes
        jpeg_buffer = BytesIO()
        image.save(jpeg_buffer, format='JPEG', quality=95)
        return base64.standard_b64encode(jpeg_buffer.getvalue()).decode("utf-8")
    else:
        # For other formats, read directly
        with open(image_path, "rb") as image_file:
            return base64.standard_b64encode(image_file.read()).decode("utf-8")

def get_image_media_type(image_path: str) -> str:
    """Determine media type based on file extension."""
    ext = Path(image_path).suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".heic": "image/jpeg",  # HEIC will be converted to JPEG
        ".heif": "image/jpeg",  # HEIF will be converted to JPEG
    }
    return media_types.get(ext, "image/jpeg")

def generate_sassy_comment(image_path: str) -> str:
    """
    Generate a sassy comment about trash using Claude's vision API.

    Args:
        image_path: Path to the image file

    Returns:
        A witty, sassy comment about the trash in the image
    """
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in environment variables. Check your .env file.")

    client = Anthropic(api_key=api_key)

    # Validate image exists
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    # Validate file is an image
    valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
    if Path(image_path).suffix.lower() not in valid_extensions:
        raise ValueError(f"Unsupported image format. Supported: {valid_extensions}")

    # Load and encode image
    image_data = load_image_as_base64(image_path)
    media_type = get_image_media_type(image_path)

    # Create message with vision capability
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=280,  # Leave room for X's character count
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": """You are Jaume, a sassy environmental activist who posts pictures of trash and litter on X (Twitter) to raise awareness about cleanliness in urban areas.

Look at this image of trash and generate a SINGLE sassy, witty, humorous comment that will be posted to X. The comment should:
- Be concise (under 280 characters for X)
- Have attitude and sass
- Call out the mess but in a funny/entertaining way
- Possibly use relevant emojis
- Be shareable and engaging
- Not be mean to people, just roast the trash situation

Generate ONLY the comment text, nothing else. No explanations, no quotes, just the comment."""
                    }
                ],
            }
        ],
    )

    return message.content[0].text.strip()
