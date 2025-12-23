import asyncio


class TooManyUserDownloadsError(Exception):
    pass


class ServerBusyError(Exception):
    pass


class ConcurrencyMiddleware:
    def __init__(self, max_per_user: int = 2, max_global: int = 5):
        self.max_per_user = max_per_user
        self.max_global = max_global
        self.user_semaphores: dict[int, asyncio.Semaphore] = {}
        self.global_semaphore = asyncio.Semaphore(max_global)

    def _get_user_semaphore(self, user_id: int) -> asyncio.Semaphore:
        if user_id not in self.user_semaphores:
            self.user_semaphores[user_id] = asyncio.Semaphore(self.max_per_user)
        return self.user_semaphores[user_id]

    async def acquire(self, user_id: int):
        user_sem = self._get_user_semaphore(user_id)

        if user_sem.locked():
            raise TooManyUserDownloadsError(
                f"You already have {self.max_per_user} active downloads. Please wait."
            )

        if self.global_semaphore.locked():
            raise ServerBusyError(
                "Server is at capacity. Please try again in a moment."
            )

        await user_sem.acquire()
        await self.global_semaphore.acquire()

    def release(self, user_id: int):
        user_sem = self._get_user_semaphore(user_id)
        user_sem.release()
        self.global_semaphore.release()
