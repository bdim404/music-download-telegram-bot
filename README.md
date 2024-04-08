# music-download-telegram-bot

An Apple Music & Spotify Music Telegram bot downloader created with Python.

You can find the private version [here](https://github.com/bdim404/music-download-telegram-bot/tree/private)

## Features

- **Download songs** in 256kbps AAC or 64kbps HE-AAC for high-quality audio experience.
- **FFmpeg Integration** for advanced users to remux audio without re-encoding, preserving original quality.
- **yt-dlp Utilization** for efficient and reliable downloading from music platforms.
- **Customization Options** to tailor the bot's behavior to your specific needs.

## News!

- Add the function of posting while downloading, you can download OVER 100 songs playlist at a time.(29/3/2024)

## Installation

Before proceeding, ensure that you have [FFmpeg](https://ffmpeg.org/download.html) installed on your system.

### Setup Instructions

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/bdim404/AMdlBOT.git
   ```

2. **Create a .env File**:
   - Navigate to the project directory.
   - Create a `.env` file and insert your Telegram bot token.

3. **Provide Necessary Files**:
   - Place your `cookies.txt` and `device.wvd` files in the project directory, or specify their paths in the `.env` file.

4. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Run the Main Script**:
   - Navigate to the `src` directory.
   - Execute `main.py` to start the bot:
     ```bash
     cd src
     python main.py
     ```

## Important Notes

- Follow the installation steps carefully to avoid any errors during setup.
- This bot sends songs through a media group, so make sure you have a channel that holds a cache of songs.
- Ensure that your Telegram bot token and the files `cookies.txt` and `device.wvd` are valid and up-to-date for the bot to function correctly.
- Check your internet connection before running the bot to ensure smooth access to GitHub and the FFmpeg website.

## Donate

If you like the bot, you can support the developer!

https://ko-fi.com/bdim404
