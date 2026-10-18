from .base import Provider
from .travelpayouts import TravelpayoutsProvider


def build_provider(name: str, settings: dict) -> Provider:
    if name == "travelpayouts":
        return TravelpayoutsProvider(**settings)
    raise ValueError(f"Nieznany provider: {name}")
