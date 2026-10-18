from abc import ABC, abstractmethod

from ..models import Offer


class Provider(ABC):
    """Źródło cen. Nowe źródła (np. Kiwi, SerpApi Google Flights) implementują ten interfejs."""

    name = "base"

    @abstractmethod
    def search_month(
        self, origin: str, destination: str, month: str, one_way: bool, currency: str
    ) -> list[Offer]:
        """Zwraca oferty z wylotem w danym miesiącu (month = 'YYYY-MM')."""
