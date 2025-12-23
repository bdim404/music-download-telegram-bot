import asyncio
import logging
from pathlib import Path

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
from .middleware.whitelist import WhitelistMiddleware
from .middleware.concurrency import ConcurrencyMiddleware
from .handlers.start import start_handler
from .handlers.link import link_handler
from .handlers.error import error_handler


logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def shutdown_handler(application):
    db = application.bot_data.get('db')
    if db:
        logger.info("Closing database connection...")
        await db.close()
    logger.info("Bot shutdown complete")


async def main():
    logger.info("Starting Apple Music Download Telegram Bot...")

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

    cache = CacheService(db)
    sender = SenderService()
    whitelist = WhitelistMiddleware(config.whitelist_users, config.whitelist_groups)
    concurrency = ConcurrencyMiddleware(
        max_per_user=config.max_concurrent_per_user,
        max_global=config.max_concurrent_global
    )

    logger.info(f"Whitelist: {len(config.whitelist_users)} users, {len(config.whitelist_groups)} groups")
    logger.info(f"Concurrency limits: {config.max_concurrent_per_user} per user, {config.max_concurrent_global} global")

    Path(config.temp_path).mkdir(parents=True, exist_ok=True)

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    application = (
        Application.builder()
        .token(config.bot_token)
        .request(request)
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_handler))
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    logger.info("Bot is running...")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Received stop signal")
    finally:
        logger.info("Stopping bot...")
        await application.updater.stop()
        await application.stop()
        await shutdown_handler(application)
        await application.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
