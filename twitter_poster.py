import os
from pathlib import Path
import tweepy
from io import BytesIO
from PIL import Image

def create_twitter_client() -> tweepy.Client:
    """Create and authenticate a Twitter API v2 client."""
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    bearer_token = os.getenv("X_BEARER_TOKEN")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, bearer_token, access_token, access_token_secret]):
        raise ValueError(
            "Missing X API credentials. Please set all X_* environment variables in .env"
        )

    # Use OAuth 2.0 User Context for media uploads
    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )

    return client

def create_v1_client() -> tweepy.API:
    """Create API v1.1 client for media upload (v2 media upload still in development)."""
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    auth = tweepy.OAuthHandler(api_key, api_secret)
    auth.set_access_token(access_token, access_token_secret)

    return tweepy.API(auth)

def post_image_with_caption(image_path: str, caption: str) -> dict:
    """
    Post an image with caption to X.

    Args:
        image_path: Path to the image file
        caption: Text caption for the post

    Returns:
        Dictionary with post URL and ID
    """
    # Validate image
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
    if Path(image_path).suffix.lower() not in valid_extensions:
        raise ValueError(f"Unsupported image format. Supported: {valid_extensions}")

    if len(caption) > 280:
        raise ValueError(f"Caption too long ({len(caption)} chars). Max: 280 characters")

    try:
        # If HEIC, convert to JPEG first
        upload_path = image_path
        if image_path.lower().endswith(('.heic', '.heif')):
            try:
                import pillow_heif
                heif_file = pillow_heif.read(image_path)
                img = Image.frombytes(
                    heif_file.mode,
                    heif_file.size,
                    heif_file.data
                )
            except Exception:
                # Fallback: try normal open
                img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Save as temporary JPEG
            temp_path = Path(image_path).parent / f"{Path(image_path).stem}_temp.jpg"
            img.save(temp_path, format='JPEG', quality=95)
            upload_path = str(temp_path)

        # Upload media using v1.1 API
        api_v1 = create_v1_client()
        media = api_v1.media_upload(filename=upload_path)

        # Post with media using v2 client
        client_v2 = create_twitter_client()
        response = client_v2.create_tweet(
            text=caption,
            media_ids=[media.media_id],
        )

        post_id = response.data["id"]
        post_url = f"https://x.com/i/web/status/{post_id}"

        # Clean up temporary file if created
        if upload_path != image_path:
            try:
                Path(upload_path).unlink()
            except:
                pass

        return {
            "success": True,
            "post_id": post_id,
            "post_url": post_url,
            "caption": caption,
        }

    except tweepy.TweepyException as e:
        raise Exception(f"Failed to post to X: {str(e)}")
