import asyncio
import logging
from pathlib import Path

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from .config import Config
from .models.database import Database
from .services.downloader import DownloaderService
from .services.cache import CacheService
from .services.sender import SenderService
from .services.health import health_check_loop, notify_admins, systemd_notify, watchdog_loop
from .middleware.whitelist import WhitelistMiddleware
from .middleware.concurrency import ConcurrencyMiddleware
from .handlers.start import help_handler, start_handler
from .handlers.link import link_handler
from .handlers.settings import allow_handler, codec_handler, deny_handler, list_handler, lyrics_handler
from .handlers.error import error_handler
from .version import get_version


logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def configure_bot_commands(application, config):
    user_commands = [
        BotCommand("start", "Show help"),
        BotCommand("help", "Show help"),
        BotCommand("codec", "Show or set your download codec"),
        BotCommand("lyrics", "Show or set lyrics file delivery"),
    ]
    admin_commands = [
        *user_commands,
        BotCommand("allow", "Allow a user"),
        BotCommand("deny", "Deny a user"),
        BotCommand("list", "List whitelisted users"),
    ]

    await application.bot.set_my_commands(
        user_commands,
        scope=BotCommandScopeDefault()
    )

    for admin_user_id in getattr(config, 'admin_users', []):
        try:
            await application.bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_user_id)
            )
        except Exception as e:
            logger.warning(f"Failed to set admin commands for {admin_user_id}: {e}")

    logger.info("Telegram command menu configured")


async def shutdown_handler(application):
    db = application.bot_data.get('db')
    if db:
        logger.info("Closing database connection...")
        await db.close()
    logger.info("Bot shutdown complete")


async def main():
    version = get_version()
    logger.info(f"Starting Apple Music Download Telegram Bot v{version}...")

    config = Config.load()
    logger.info(f"Config loaded from config.yaml")

    db = Database(config.database_path)
    await db.initialize()
    logger.info(f"Database initialized at {config.database_path}")

    downloader = DownloaderService(config)
    await downloader.initialize()
    logger.info(f"Downloader service initialized with cookies from {config.cookies_path}")
    logger.info(f"Subscription active: {downloader.apple_music_api.active_subscription}")
    logger.info(f"Storefront: {downloader.apple_music_api.storefront}")
    logger.info(f"Default codec: {downloader.normalize_codec(config.song_codec).upper()}")
    logger.info(f"Effective default codec: {downloader.effective_codec(config.song_codec).upper()}")
    if config.use_wrapper:
        logger.info("Wrapper availability: ENABLED (ALAC/Dolby Atmos can be selected)")
    else:
        logger.info("Wrapper availability: DISABLED (wrapper-only codecs fall back to AAC)")

    cache = CacheService(db)
    sender = SenderService()
    whitelist = WhitelistMiddleware(
        config.whitelist_users,
        config.whitelist_groups,
        config.admin_users,
        cache
    )
    concurrency = ConcurrencyMiddleware(
        max_per_user=config.max_concurrent_per_user,
        max_global=config.max_concurrent_global
    )

    logger.info(
        f"Whitelist: {len(config.whitelist_users)} users, "
        f"{len(config.whitelist_groups)} groups, {len(config.admin_users)} admins"
    )
    logger.info(f"Concurrency limits: {config.max_concurrent_per_user} per user, {config.max_concurrent_global} global")
    logger.info(f"Telegram update concurrency: {config.max_concurrent_updates}")

    Path(config.temp_path).mkdir(parents=True, exist_ok=True)

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=60.0,
        read_timeout=300.0,
        write_timeout=600.0,
        pool_timeout=120.0,
    )
    application = (
        Application.builder()
        .token(config.bot_token)
        .request(request)
        .concurrent_updates(config.max_concurrent_updates)
        .build()
    )

    application.bot_data['config'] = config
    application.bot_data['db'] = db
    application.bot_data['downloader'] = downloader
    application.bot_data['cache'] = cache
    application.bot_data['sender'] = sender
    application.bot_data['whitelist'] = whitelist
    application.bot_data['concurrency'] = concurrency

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("codec", codec_handler))
    application.add_handler(CommandHandler("lyrics", lyrics_handler))
    application.add_handler(CommandHandler("allow", allow_handler))
    application.add_handler(CommandHandler("deny", deny_handler))
    application.add_handler(CommandHandler("list", list_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_handler))
    application.add_error_handler(error_handler)

    await application.initialize()
    await configure_bot_commands(application, config)
    await application.start()
    await application.updater.start_polling()

    logger.info("Bot is running...")
    systemd_notify("READY=1\nSTATUS=Bot is running")
    await notify_admins(application, "Apple Music Download Bot started.")

    health_task = asyncio.create_task(health_check_loop(application))
    watchdog_task = asyncio.create_task(watchdog_loop(application))

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Received stop signal")
    finally:
        logger.info("Stopping bot...")
        health_task.cancel()
        watchdog_task.cancel()
        await asyncio.gather(health_task, watchdog_task, return_exceptions=True)
        await notify_admins(application, "Apple Music Download Bot is stopping.")
        await application.updater.stop()
        await application.stop()
        await shutdown_handler(application)
        await application.shutdown()


def run():
    asyncio.run(main())


if __name__ == '__main__':
    run()
