import asyncio
import logging
import os
import socket


logger = logging.getLogger(__name__)


def systemd_notify(message: str):
    notify_socket = os.getenv("NOTIFY_SOCKET")
    if not notify_socket:
        return

    if notify_socket.startswith("@"):
        notify_socket = "\0" + notify_socket[1:]

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(notify_socket)
        sock.sendall(message.encode())
        sock.close()
    except Exception as e:
        logger.debug(f"systemd notify failed: {e}")


async def notify_admins(application, text: str):
    config = application.bot_data.get('config')
    admin_users = getattr(config, 'admin_users', []) if config else []
    if not admin_users:
        return

    for user_id in admin_users:
        try:
            await application.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            logger.warning(f"Failed to notify admin {user_id}: {e}")


async def watchdog_loop(application):
    watchdog_usec = os.getenv("WATCHDOG_USEC")
    if watchdog_usec:
        interval = max(int(watchdog_usec) / 2_000_000, 1)
    else:
        config = application.bot_data.get('config')
        interval = getattr(config, 'health_check_interval_seconds', 300) if config else 300

    while True:
        systemd_notify("WATCHDOG=1\nSTATUS=Bot event loop is responsive")
        await asyncio.sleep(interval)


async def health_check_loop(application):
    config = application.bot_data.get('config')
    downloader = application.bot_data.get('downloader')
    interval = getattr(config, 'health_check_interval_seconds', 300) if config else 300
    bot_was_healthy = True
    wrapper_was_healthy = True

    while True:
        await asyncio.sleep(interval)
        try:
            me = await application.bot.get_me()
            if not bot_was_healthy:
                await notify_admins(application, f"Bot health restored: @{me.username}")
            bot_was_healthy = True
            systemd_notify(f"STATUS=Bot healthy: @{me.username}")
        except Exception as e:
            logger.exception("Bot health check failed")
            if bot_was_healthy:
                await notify_admins(application, f"Bot health check failed: {type(e).__name__}: {e}")
            bot_was_healthy = False
            systemd_notify(f"STATUS=Bot health check failed: {type(e).__name__}")

        if not getattr(config, 'use_wrapper', False):
            continue

        try:
            wrapper_healthy = bool(downloader and downloader._check_wrapper_available())
        except Exception as e:
            logger.warning(f"Wrapper health check raised: {e}")
            wrapper_healthy = False

        if wrapper_healthy and not wrapper_was_healthy:
            logger.info(f"Wrapper health restored: {config.wrapper_url}")
            await notify_admins(application, f"Wrapper health restored: {config.wrapper_url}")
        elif not wrapper_healthy and wrapper_was_healthy:
            logger.warning(f"Wrapper health check failed: {config.wrapper_url}")
            await notify_admins(application, f"Wrapper health check failed: {config.wrapper_url}")

        wrapper_was_healthy = wrapper_healthy
