"""Wysyłka powiadomień na Telegram."""

import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

MAX_LEN = 4000  # Telegram przyjmuje do 4096 znaków w jednej wiadomości


class Notifier:
    def send(self, text: str) -> None:
        for chunk in split_message(text):
            self._send(chunk)

    def _send(self, text: str) -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def _send(self, text: str) -> None:
        print(text)
        print("-" * 40)


class TelegramNotifier(Notifier):
    """Bot Telegrama zakładany przez @BotFather (instrukcja w README)."""

    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise ValueError("Ustaw TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID")
        self.token = token
        self.chat_id = chat_id

    def _send(self, text: str) -> None:
        data = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram: {body.get('description')}")


def telegram_chat_ids(token: str) -> list[tuple[str, str]]:
    """Zwraca (chat_id, nazwa) czatów, które ostatnio pisały do bota."""
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30) as r:
        updates = json.loads(r.read().decode("utf-8")).get("result", [])
    chats = {}
    for u in updates:
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
        if chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            chats[str(chat["id"])] = name
    return list(chats.items())


def build_notifier(channel: str) -> Notifier:
    if channel == "telegram":
        return TelegramNotifier(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""))
    if channel == "console":
        return ConsoleNotifier()
    raise ValueError(f"Nieznany kanał powiadomień: {channel}")


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Dzieli tekst na części po pełnych liniach, nie przekraczając limitu (nie rozcina tagów HTML)."""
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current.strip("\n"))
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current.strip():
        chunks.append(current.strip("\n"))
    return chunks
