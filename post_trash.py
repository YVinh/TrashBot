#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from comment_generator import generate_sassy_comment
from twitter_poster import post_image_with_caption

def main():
    """Main entry point for posting trash images."""
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
        "--no-post",
        action="store_true",
        help="Generate comment but don't post to X (for testing)",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

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

    # Post to X if not in test mode
    if not args.no_post:
        print("📤 Posting to X...")
        try:
            result = post_image_with_caption(image_path, comment)
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
