# Apple Music Download Telegram Bot

A Telegram bot for downloading Apple Music tracks, albums, and playlists, powered by gamdl.

## Features

- Download Apple Music songs, albums, and playlists
- SQLite database caching to avoid duplicate downloads
- Whitelist-based user access control
- Concurrent download limits (2 per user, 5 global)
- File size limit (default 50MB)
- Automatic temporary file cleanup
- Complete metadata support (cover art, duration, artist, etc.)

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install System Dependencies

The bot uses pywidevine and mp4decrypt for decryption. Install the following tools:

#### macOS
```bash
brew install bento4 ffmpeg
```

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install bento4 ffmpeg
```

#### Verify Installation
```bash
mp4decrypt --version
ffmpeg -version
```

### 3. Get Apple Music Cookies

The bot requires cookies exported from Apple Music website for authentication.

#### Using Browser Extension (Recommended)

1. Install browser extension:
   - Chrome: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - Firefox: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. Visit https://music.apple.com and log in
3. Confirm your Apple Music subscription is active
4. Click the extension icon and export cookies
5. Save the file as `cookies.txt` in the project root directory

#### Using yt-dlp

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt https://music.apple.com
```

**Note**:
- Cookies are typically valid for 1-3 months
- Re-export after expiration
- An active Apple Music subscription is required

### 4. Configuration

Edit `config.yaml`:

```yaml
bot_token: "YOUR_BOT_TOKEN"  # Get from @BotFather
cookies_path: "./cookies.txt"  # Path to cookies file

whitelist_users:  # Telegram user IDs allowed to use the bot
  - 123456789
  - 987654321

max_concurrent_per_user: 2
max_concurrent_global: 5
max_file_size_mb: 50

database_path: "./data/cache.db"
temp_path: "./data/temp"
```

## Running

```bash
python -m bot.main
```

## Usage

1. After starting the bot, send `/start` command
2. Send Apple Music links, for example:
   - Single track: `https://music.apple.com/us/album/.../1234567?i=1234568`
   - Album: `https://music.apple.com/us/album/.../1234567`
   - Playlist: `https://music.apple.com/us/playlist/.../pl.xxx`

## Project Structure

```
bot/
├── models/         # Database models
├── services/       # Business logic services
├── middleware/     # Middleware (whitelist, concurrency control)
├── handlers/       # Message handlers
└── main.py         # Main entry point
```

## Important Notes

1. An active Apple Music subscription is required
2. Cookies need to be re-exported periodically (every 1-3 months)
3. Ensure mp4decrypt and ffmpeg are installed
4. Ensure sufficient disk space for temporary files
5. Telegram file_id is permanent and can be reused
6. Files larger than 50MB will be skipped
7. Temporary files are deleted immediately after download

## Troubleshooting

**Q: "media-user-token" cookie not found**
A: Ensure you export cookies from https://music.apple.com while logged in with a subscribed account

**Q: "Subscription is not active"**
A: Check that your Apple Music subscription is active

**Q: mp4decrypt not found**
A: Install Bento4 toolkit (see Installation section)

**Q: What if cookies expire?**
A: Re-export cookies.txt from your browser and restart the bot

## Try

You can PM me and then use my bot by [bdim_music_bot](https://t.me/bdim_music_bot)
