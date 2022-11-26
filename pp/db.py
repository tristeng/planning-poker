import abc
import json
from pathlib import Path

from pp.model import Deck


class DeckDB(abc.ABC):
    """Abstract deck database class"""

    @abc.abstractmethod
    async def get_decks(self) -> list[Deck]:
        """Returns the available decks from the database.

        :return: the list of decks
        """

    @abc.abstractmethod
    async def get_deck_by_id(self, deck_id: int) -> Deck:
        """Returns a deck by it's ID

        :param deck_id: the ID of the deck to return
        :return: the deck or raise a not found error
        :raises: ValueError if no deck with the ID is found
        """


class MemoryDeckDB(DeckDB):
    """An in memory deck database - loads decks from a JSON file upon init."""

    def __init__(self, config: Path):
        """Initializes a new Memory Deck DB

        :param config: the path to a JSON file that contains a list of decks
        """
        self.decks: dict[int, Deck] = {}

        # we expect this to be a list of decks
        with config.open() as f:
            parsed = json.load(f)

        for obj in parsed:
            deck = Deck.parse_obj(obj)
            self.decks[deck.id] = deck

    async def get_decks(self) -> list[Deck]:
        """Returns the available decks from the database.

        :return: the list of decks
        """
        return list(self.decks.values())

    async def get_deck_by_id(self, deck_id: int) -> Deck:
        """Returns a deck by it's ID

        :param deck_id: the ID of the deck to return
        :return: the deck or raise a not found error
        :raises: ValueError if no deck with the ID is found
        """
        try:
            return self.decks[deck_id]
        except KeyError:
            raise ValueError(f"No deck exists with ID {deck_id}")
