"""Канал уведомлений. Telegram-бот подменяет sink при запуске; без него — только лог."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable

log = logging.getLogger("arb.notify")

Buttons = list[tuple[str, str]]  # (текст кнопки, callback_data)
Sink = Callable[[str, Buttons | None], Awaitable[None]]

# Сколько неотправленных сообщений держим, пока нет связи с Telegram (старые выпадают первыми).
MAX_PENDING = 300
IMPORTANT_EVENTS = re.compile(
    r"^(?:💰 Продажа #\d+\b|✅ Покупка у поставщика #\d+\b|⚠️ Оплата \S+ у \S+ не привязана:)"
)


class Notifier:
    def __init__(self) -> None:
        self.sink: Sink | None = None
        # Нет связи с Telegram — сообщение (о продаже, о заказе) не теряем, а досылаем позже.
        self.pending: deque[tuple[float, str, Buttons | None]] = deque(maxlen=MAX_PENDING)
        self._lock = asyncio.Lock()

    async def __call__(self, text: str, buttons: Buttons | None = None) -> None:
        log.info("%s", text.replace("\n", " | "))
        if not IMPORTANT_EVENTS.match(text):
            return
        async with self._lock:
            self.pending.append((time.time(), text, buttons))
            await self._flush()

    async def flush(self) -> None:
        """Дослать накопившиеся сообщения (вызывается и по таймеру)."""
        if self.sink and self.pending:
            async with self._lock:
                await self._flush()

    async def _flush(self) -> None:
        while self.pending and self.sink:
            ts, text, buttons = self.pending[0]
            late = time.time() - ts
            body = text if late < 120 else f"⏳ Не доставлено вовремя (нет связи с Telegram), {time.strftime('%d.%m %H:%M', time.localtime(ts))}:\n{text}"
            try:
                await self.sink(body, buttons)
            except Exception as e:  # noqa: BLE001
                log.warning("не удалось отправить уведомление (%s), в очереди %d — дошлю позже", e, len(self.pending))
                return
            self.pending.popleft()

    async def loop(self, every: float = 60) -> None:
        while True:
            await asyncio.sleep(every)
            try:
                await self.flush()
            except Exception as e:  # noqa: BLE001
                log.warning("досылка уведомлений упала: %s", e)
