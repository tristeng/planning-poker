import abc

from pp.model import Deck, Card


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
    """An in memory deck database - does not persist state upon server restart."""

    DECKS = {
        1: Deck(
            id=1,
            cards=[
                Card(label="1/2", value=0.5),
                Card(label="1", value=1),
                Card(label="2", value=2),
                Card(label="3", value=3),
                Card(label="5", value=5),
                Card(label="8", value=8),
                Card(label="13", value=13),
                Card(label="21", value=21),
                Card(label="?", value=100),
            ],
        )
    }

    async def get_decks(self) -> list[Deck]:
        """Returns the available decks from the database.

        :return: the list of decks
        """
        return list(self.DECKS.values())

    async def get_deck_by_id(self, deck_id: int) -> Deck:
        """Returns a deck by it's ID

        :param deck_id: the ID of the deck to return
        :return: the deck or raise a not found error
        :raises: ValueError if no deck with the ID is found
        """
        try:
            return self.DECKS[deck_id]
        except KeyError:
            raise ValueError(f"No deck exists with ID {deck_id}")
