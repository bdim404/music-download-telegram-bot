from telegram import Update
from telegram.ext import ContextTypes


class NotWhitelistedError(Exception):
    pass


class WhitelistMiddleware:
    def __init__(self, whitelist_users: list[int]):
        self.whitelist_users = set(whitelist_users)

    def check(self, user_id: int) -> bool:
        return user_id in self.whitelist_users

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        if not update.effective_user:
            return False

        user_id = update.effective_user.id

        if not self.check(user_id):
            if update.message:
                await update.message.reply_text(
                    "Access denied. Please contact the administrator for access."
                )
            return False

        return True
