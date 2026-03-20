# 🗑️ TrashBot - Jaume

An AI-powered bot that posts images of trash to X (Twitter) with sassy, witty comments to raise awareness about urban cleanliness issues.

## Features

✨ **AI-Generated Comments** - Uses Claude's vision API to analyze trash images and create contextual, sassy comments
📱 **Easy to Use** - Simple CLI: `python post_trash.py image.jpg`
🐦 **X Integration** - Posts directly to X/Twitter with image and caption
🎯 **Personality** - Jaume has attitude and calls out mess with humor

## Setup

### Prerequisites

- Python 3.9 or higher
- An X (Twitter) account and API credentials
- A Claude API key from Anthropic

### Step 1: Clone and Install

```bash
git clone https://github.com/YVinh/TrashBot.git
cd TrashBot
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Get Your API Credentials

#### Claude API Key

1. Go to https://console.anthropic.com/
2. Sign up or log in
3. Click "API Keys" in the left sidebar
4. Click "Create Key"
5. Copy the key and save it safely

#### X (Twitter) API Credentials

1. Go to https://developer.twitter.com/en/portal/dashboard
2. Create an app or use an existing one
3. Go to "Keys and tokens" tab
4. Under "Authentication Tokens & Keys" section, regenerate or copy:
   - **API Key** (Consumer Key)
   - **API Secret Key** (Consumer Secret)
   - **Access Token**
   - **Access Token Secret**
5. Go to the "Bearer Token" section and copy the **Bearer Token**

⚠️ **Important:** Make sure your app has **Read and Write** permissions:
- Go to "App Settings"
- Under "User authentication settings", set "App permissions" to include Write access

### Step 3: Configure Environment

1. Copy the example env file:
```bash
cp .env.example .env
```

2. Edit `.env` and fill in your API credentials:
```
CLAUDE_API_KEY=your_claude_api_key_here
X_API_KEY=your_x_api_key_here
X_API_SECRET=your_x_api_secret_here
X_BEARER_TOKEN=your_x_bearer_token_here
X_ACCESS_TOKEN=your_x_access_token_here
X_ACCESS_TOKEN_SECRET=your_x_access_token_secret_here
```

⚠️ **Never commit `.env` to Git** - it's already in `.gitignore`

## Usage

### Post an Image with Auto-Generated Comment

```bash
python post_trash.py path/to/trash_image.jpg
```

Jaume will:
1. Analyze the image
2. Generate a sassy comment
3. Post to X with the image

### Test Mode (Generate Comment Without Posting)

To see what Jaume would say without posting:

```bash
python post_trash.py path/to/trash_image.jpg --no-post
```

### Add Location Context

```bash
python post_trash.py trash.jpg --location "Downtown Park"
```

(Optional - helps with comment generation)

## Supported Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- WebP (.webp)

## Troubleshooting

### "Image file not found"
- Make sure the image path is correct (relative or absolute)
- Try using the full path: `/absolute/path/to/image.jpg`

### "Missing X API credentials"
- Verify all keys are correctly copied in `.env`
- Check there are no extra spaces or quotes around values
- Make sure your X app has Read and Write permissions

### "Failed to post to X"
- Check your internet connection
- Verify your API keys are still valid
- Make sure your app has Write permissions on X
- Try posting to X manually to ensure your account works

### "Unsupported image format"
- Use JPEG, PNG, GIF, or WebP
- Try converting your image format

## How It Works

1. **Image Upload** - You provide an image file path
2. **Comment Generation** - Claude analyzes the image and generates witty commentary
3. **X Posting** - The image and comment are posted to X as a tweet
4. **Awareness** - Friends and followers see the trash issue highlighted with humor

## Project Structure

```
TrashBot/
├── post_trash.py        # Main entry point
├── comment_generator.py # Claude integration for sassy comments
├── twitter_poster.py    # X API integration
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
├── .env                 # (gitignored) Your actual API keys
└── README.md           # This file
```

## Development

### Install in Development Mode

```bash
pip install -e .
```

### Run Tests

```bash
python post_trash.py test_image.jpg --no-post
```

## Contributing

Feel free to fork and submit pull requests to enhance Jaume's personality or features!

## License

MIT License

## Support

Having issues? Check the Troubleshooting section above or open an issue on GitHub.

---

**Made with ❤️ to fight trash, one post at a time.** 🗑️✨
