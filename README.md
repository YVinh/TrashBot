# 🗑️ TrashBot - Marc

An AI-powered bot that posts images of trash to X (Twitter) with sassy, witty comments to raise awareness about urban cleanliness issues.

## Features

✨ **AI-Generated Comments** - Uses Claude's vision API to analyze trash images and create contextual, sassy comments
📱 **Easy to Use** - Simple CLI: `python post_trash.py image.jpg`
🐦 **X Integration** - Posts directly to X/Twitter with image and caption
🌍 **Location-Based Tags** - Auto-generate relevant hashtags and X accounts to mention based on coordinates
🎯 **Personality** - Marc has attitude and calls out mess with humor

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

Marc will:
1. Analyze the image
2. Generate a sassy comment
3. Post to X with the image

### Test Mode (Generate Comment Without Posting)

To see what Marc would say without posting:

```bash
python post_trash.py path/to/trash_image.jpg --no-post
```

### Add Location Context

```bash
python post_trash.py trash.jpg --location "Downtown Park"
```

(Optional - helps with comment generation)

### Auto Location-Based Tags & Mentions

Marc **automatically extracts GPS coordinates from your image's metadata** and adds relevant hashtags and X account mentions! 🌍

Just provide the image path:

```bash
python post_trash.py trash.jpg
```

If your image has GPS data, Marc will:
- Detect your location (Brussels, Amsterdam, etc.)
- Add 1-2 relevant local organization mentions
- Add 3-4 location-specific hashtags (#Brussels, #ClimateAction, etc.)

**No manual coordinates needed!** Modern smartphones embed GPS in photos automatically.

#### Manual Coordinates (Optional Override)

If your image doesn't have GPS metadata, provide coordinates:

```bash
python post_trash.py trash.jpg --lat 50.85 --lon 4.35
```

## Telegram bot (send a photo, get a post)

Instead of running the CLI by hand, `bot.py` runs Marc as a small Claude **agent**: it
gets the photo plus two tools (`extract_gps`, `get_hashtags`) and decides for itself
whether to look up location hashtags before writing the caption — via the Anthropic
Python SDK's [tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)
(`client.beta.messages.tool_runner`), not a fixed script.

Flow: you send a photo to the bot on Telegram → Marc replies with a draft caption and
**✅ Post to X** / **❌ Discard** buttons → nothing is posted until you tap Post. This
confirm step exists because texting a photo is much lower-friction than running a CLI
command, so an auto-post-on-receipt bot could publish something you didn't mean to send.

### Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram (`/newbot`), copy
   the token into `TELEGRAM_BOT_TOKEN` in `.env`.
2. Run `python bot.py` once, then message your bot `/start` — it replies with your
   `chat_id`. Put that in `ALLOWED_TELEGRAM_CHAT_IDS` in `.env` (comma-separated for
   multiple chats). The bot refuses every chat until this is set.
3. Restart `python bot.py` and send it a trash photo.

**GPS tip:** Telegram strips EXIF from photos sent through the normal photo picker. To
get location-based hashtags, send the image as a **File/Document** instead (attach →
File, not Photo) so EXIF survives; otherwise Marc just skips hashtags.

## The trio: Marc → Giselle → Yousuf

Beyond a single bot posting photos, three linked bot accounts run an escalating
conversation about the same trash:

- **Marc** posts the photo (as above — you send it, you approve the caption).
- **Giselle** (`giselle_agent.py`) reacts with indignation *automatically* the moment
  Marc's post succeeds — no approval step. She uses Anthropic's server-side
  [web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
  to find a real news article or public tweet about trash/cleanliness in Brussels and
  links it as her "proof," rather than re-uploading anyone's photo. Facebook is
  blocked as a source (`blocked_domains`) — scraping it violates its ToS and would
  repost private citizens' images without consent.
- **Yousuf** (`yousuf_agent.py`) comments — text only, no images or links — on both
  Marc's original post and Giselle's reply, also automatically.

**Disclosure:** all three accounts' bios should state they're bots / part of a satire
project (e.g. "🤖 satire bot, part of a Brussels-trash-shaming trio — see @<other
handles>"). Three accounts scripted to argue with each other while pretending to be
independent people is the kind of thing X's platform-manipulation rules exist to catch,
and could get all three suspended together; a disclosed bot project doesn't have that
problem and is just as funny.

### Setup

1. Create two more X accounts + developer apps (same steps as Marc's — see above), one
   for Giselle and one for Yousuf. Set each bio to disclose the project.
2. Fill in `GISELLE_X_*` and `YOUSUF_X_*` in `.env` (see `.env.example`) — both reuse
   the same `CLAUDE_API_KEY` as Marc.
3. That's it — no extra process to run. `bot.py` calls `giselle_agent.generate_reaction`
   and `yousuf_agent.generate_comments` directly, right after Marc's tweet posts, and
   reports each resulting URL back to your Telegram chat. If Giselle or Yousuf fail
   (e.g. missing credentials), you'll see a `⚠️` message but Marc's own post still stands.

This deliberately avoids polling X's timeline API to "notice" Marc's new post — X's
free API tier doesn't include read access, and polling isn't needed anyway since
`bot.py` already knows the tweet id the instant it posts it.

### Deploying on Proxmox

This fits inside the existing `boiler-scripts` LXC (CT101) alongside `telegram-mail-bot`
— a Python long-poller idles at a few MB and CT101 had ~800MB RAM and ~4GB disk free.

```bash
# from your Mac, copy the project to CT101 via the Proxmox host
rsync -av --exclude venv --exclude .git /Users/yves/TrashBot/ root@192.168.178.250:/tmp/trashbot/
ssh root@192.168.178.250 "pct push 101 --recursive /tmp/trashbot /opt/trashbot"

# inside CT101
pct exec 101 -- bash -c "
  cd /opt/trashbot &&
  python3 -m venv venv &&
  source venv/bin/activate &&
  pip install -r requirements.txt
"
```

Create `/etc/systemd/system/trashbot.service` inside CT101:

```ini
[Unit]
Description=Marc TrashBot (Telegram -> Claude agent -> X)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/trashbot
ExecStart=/opt/trashbot/venv/bin/python bot.py
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
pct exec 101 -- systemctl daemon-reload
pct exec 101 -- systemctl enable --now trashbot.service
pct exec 101 -- journalctl -u trashbot -f
```

## Supported Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- WebP (.webp)
- **HEIC (.heic)** - Apple iPhone photos (auto-converted to JPEG)
- **HEIF (.heif)** - Modern image format (auto-converted to JPEG)

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

Feel free to fork and submit pull requests to enhance Marc's personality or features!

## License

MIT License

## Support

Having issues? Check the Troubleshooting section above or open an issue on GitHub.

---

**Made with ❤️ to fight trash, one post at a time.** 🗑️✨
