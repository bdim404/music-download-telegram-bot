from telegram import Update
from telegram.ext import ContextTypes

from ..services.audit import log_user_action


class NotWhitelistedError(Exception):
    pass


class WhitelistMiddleware:
    def __init__(
        self,
        whitelist_users: list[int],
        whitelist_groups: list[int] = None,
        admin_users: list[int] = None,
        cache=None
    ):
        self.whitelist_users = set(whitelist_users)
        self.whitelist_groups = set(whitelist_groups) if whitelist_groups else set()
        self.admin_users = set(admin_users) if admin_users else set()
        self.cache = cache

    def check_user(self, user_id: int) -> bool:
        return user_id in self.admin_users or user_id in self.whitelist_users

    def check_group(self, group_id: int) -> bool:
        return group_id in self.whitelist_groups

    def check(self, user_id: int) -> bool:
        return self.check_user(user_id)

    def check_admin(self, user_id: int) -> bool:
        return user_id in self.admin_users

    async def check_user_async(self, user_id: int) -> bool:
        if self.check_user(user_id):
            return True
        if self.cache:
            return await self.cache.is_user_whitelisted(user_id)
        return False

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        if not update.effective_user:
            return False

        user_id = update.effective_user.id

        if not await self.check_user_async(user_id):
            log_user_action(update, "access_denied")
            if update.message:
                await update.message.reply_text(
                    "Access denied. Please contact the administrator for access.\n"
                    f"Your Telegram user ID is `{user_id}`.",
                    parse_mode="Markdown"
                )
            return False

        log_user_action(update, "access_allowed")
        return True
