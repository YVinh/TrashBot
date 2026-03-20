#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from comment_generator import generate_sassy_comment
from twitter_poster import post_image_with_caption
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
        help="Latitude of trash location (for location-based tags)",
        default=None,
    )
    parser.add_argument(
        "--lon",
        type=float,
        help="Longitude of trash location (for location-based tags)",
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

    if args.lat and args.lon:
        # Add location-based hashtags and mentions
        location = get_location_from_coords(args.lat, args.lon)
        print(f"📍 Detected location: {location}")

        hashtags = generate_hashtags(location)
        mentions = get_mentions_for_location(location)

        # Build caption smartly to fit X's ~280 character limit
        # Priority: mentions (1-2 most relevant) → comment → hashtags (3-4 most relevant)

        # Start with 1-2 key mentions
        key_mentions = mentions[:2]  # Top 2 mentions
        mentions_str = format_mentions(key_mentions)

        # Keep top 4 hashtags
        key_hashtags = hashtags[:4]
        hashtags_str = format_hashtags(key_hashtags)

        # Build caption: mentions on first line, comment, hashtags on last line
        caption = f"{mentions_str}\n{comment}\n{hashtags_str}"

        # If still too long, trim mentions
        if len(caption) > 280:
            caption = f"{comment}\n{hashtags_str}"

        # Final length check
        if len(caption) > 280:
            print(f"⚠️  Warning: Caption is {len(caption)} chars (limit ~280)")
            caption = f"{comment}\n#ClimateAction #TrashAlert"

        print(f"✅ Added location-based hashtags and mentions")
        print(f"   Location: {location}")
        print(f"   Mentions: {', '.join(key_mentions)}")
        print(f"   Hashtags: {', '.join(key_hashtags)}")
        print(f"   Total length: {len(caption)} chars\n")
        print(f"📤 Final caption:\n{caption}\n")
    else:
        print("💡 Tip: Add --lat and --lon for auto location-based tags and mentions!")
        print(f"   Example: python3 post_trash.py image.jpg --lat 50.85 --lon 4.35")
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
