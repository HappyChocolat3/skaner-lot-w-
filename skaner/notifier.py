"""Wysyłka powiadomień na WhatsApp."""

import base64
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

MAX_LEN = 1500  # bezpieczna długość jednej wiadomości


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


class CallMeBotNotifier(Notifier):
    """Darmowe API CallMeBot – wysyła wiadomości WhatsApp na Twój własny numer.

    Aktywacja: https://www.callmebot.com/blog/free-api-whatsapp-messages/
    """

    def __init__(self, phone: str, apikey: str):
        if not phone or not apikey:
            raise ValueError("Ustaw WHATSAPP_PHONE i CALLMEBOT_APIKEY")
        self.phone = phone
        self.apikey = apikey

    def _send(self, text: str) -> None:
        query = urllib.parse.urlencode({"phone": self.phone, "text": text, "apikey": self.apikey})
        with urllib.request.urlopen(f"https://api.callmebot.com/whatsapp.php?{query}", timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        if "error" in body.lower() and "queued" not in body.lower():
            raise RuntimeError(f"CallMeBot: {body[:300]}")


class TwilioNotifier(Notifier):
    def __init__(self, sid: str, token: str, from_number: str, to_number: str):
        if not all([sid, token, from_number, to_number]):
            raise ValueError("Ustaw TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_PHONE")
        self.sid, self.token = sid, token
        self.from_number, self.to_number = from_number, to_number

    def _send(self, text: str) -> None:
        data = urllib.parse.urlencode(
            {"From": f"whatsapp:{self.from_number}", "To": f"whatsapp:{self.to_number}", "Body": text}
        ).encode()
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json", data=data
        )
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        urllib.request.urlopen(req, timeout=30).close()


def build_notifier(channel: str) -> Notifier:
    env = os.environ.get
    if channel == "callmebot":
        return CallMeBotNotifier(env("WHATSAPP_PHONE", ""), env("CALLMEBOT_APIKEY", ""))
    if channel == "twilio":
        return TwilioNotifier(
            env("TWILIO_ACCOUNT_SID", ""),
            env("TWILIO_AUTH_TOKEN", ""),
            env("TWILIO_WHATSAPP_FROM", ""),
            env("WHATSAPP_PHONE", ""),
        )
    if channel == "console":
        return ConsoleNotifier()
    raise ValueError(f"Nieznany kanał powiadomień: {channel}")


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Dzieli tekst na części po pustych liniach (bloki ofert), nie przekraczając limitu."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > limit:
            chunks.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        chunks.append(current)
    return chunks
