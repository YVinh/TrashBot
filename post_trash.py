#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from comment_generator import generate_sassy_comment
from twitter_poster import post_image_with_caption
from exif_extractor import extract_gps_coordinates
from tags_mentions import (
    get_location_from_coords,
    generate_hashtags,
    get_mentions_for_location,
    format_mentions,
    format_hashtags,
)

def main():
    """Main entry point for posting trash images."""
    # Load environment variables from .env file
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)

    parser = argparse.ArgumentParser(
        description="Post trash images to X with AI-generated sassy comments"
    )
    parser.add_argument(
        "image",
        help="Path to the trash image file",
    )
    parser.add_argument(
        "--location",
        help="Optional location context for comment generation",
        default=None,
    )
    parser.add_argument(
        "--lat",
        type=float,
        help="Override latitude (auto-extracted from image if available)",
        default=None,
    )
    parser.add_argument(
        "--lon",
        type=float,
        help="Override longitude (auto-extracted from image if available)",
        default=None,
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        help="Generate comment but don't post to X (for testing)",
    )

    args = parser.parse_args()

    image_path = args.image

    # Validate image exists
    if not Path(image_path).exists():
        print(f"❌ Error: Image file not found: {image_path}")
        sys.exit(1)

    print(f"🗑️  Loading image: {image_path}")

    # Try to extract GPS coordinates from image metadata
    latitude = args.lat
    longitude = args.lon

    if not latitude or not longitude:
        print("📍 Checking image for GPS metadata...")
        coords = extract_gps_coordinates(image_path)
        if coords:
            latitude, longitude = coords
            print(f"   ✓ Found GPS coordinates in image: {latitude:.4f}, {longitude:.4f}")
        else:
            print("   ⚠️  No GPS metadata found in image")
            # Debug: Check what EXIF data exists
            from exif_extractor import get_exif_data
            exif_info = get_exif_data(image_path)
            if exif_info:
                print(f"   📋 Image has EXIF data: {len(exif_info)} tags found")
                if "GPSInfo" not in exif_info:
                    print("      (but no GPSInfo tag - location may not have been recorded)")
            if args.lat or args.lon:
                print("   Using manually provided coordinates")
            else:
                print("   💡 Tip: Set --lat and --lon for location-based tags, or add GPS to photo")
    else:
        print(f"📍 Using provided coordinates: {latitude:.4f}, {longitude:.4f}")

    # Generate comment
    print("✨ Generating sassy comment with Jaume's personality...")
    try:
        comment = generate_sassy_comment(image_path)
        print(f"\n📝 Generated comment:\n{comment}\n")
    except Exception as e:
        print(f"❌ Error generating comment: {str(e)}")
        sys.exit(1)

    # Build final caption with hashtags and mentions
    caption = comment
    hashtags_used = []
    mentions_used = []

    if latitude and longitude:
        # Add location-based hashtags and mentions
        location = get_location_from_coords(latitude, longitude)
        print(f"📍 Detected location: {location}")

        hashtags = generate_hashtags(location)
        mentions = get_mentions_for_location(location)

        # Build caption smartly to fit X's ~280 character limit
        # NOTE: X API has restrictions on automated mentions, so we only use hashtags
        # Keep top 4 hashtags
        key_hashtags = hashtags[:4]
        hashtags_str = format_hashtags(key_hashtags)

        # Build caption: comment + hashtags (no automatic mentions due to X API restrictions)
        caption = f"{comment}\n{hashtags_str}"

        # Final length check
        if len(caption) > 280:
            print(f"⚠️  Warning: Caption is {len(caption)} chars (limit ~280)")
            caption = f"{comment}\n#ClimateAction #TrashAlert"

        print(f"✅ Added location-based hashtags")
        print(f"   Location: {location}")
        print(f"   Hashtags: {', '.join(key_hashtags)}")
        print(f"   Total length: {len(caption)} chars\n")
        print(f"📤 Final caption:\n{caption}\n")
    else:
        print("💡 No location data - posting without location-based tags")
        print(f"\n📤 Caption:\n{caption}\n")

    # Post to X if not in test mode
    if not args.no_post:
        print("📤 Posting to X...")
        try:
            result = post_image_with_caption(image_path, caption)
            print(f"✅ Success! Posted to: {result['post_url']}")
            print(f"   Tweet ID: {result['post_id']}")
        except Exception as e:
            print(f"❌ Error posting to X: {str(e)}")
            print("   Make sure your .env file has valid X API credentials")
            sys.exit(1)
    else:
        print("⏭️  Skipping post (--no-post flag was set)")
        print("   To post, run again without the --no-post flag")

if __name__ == "__main__":
    main()
