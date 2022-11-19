import pytest

from pp.db import MemoryDeckDB

db = MemoryDeckDB()


class TestMemoryDB:
    @pytest.mark.asyncio
    async def test_get_decks(self):
        decks = await db.get_decks()
        assert len(decks) == 1

    @pytest.mark.asyncio
    async def test_get_deck_by_id(self):
        deck = await db.get_deck_by_id(1)
        assert deck.id == 1
        assert len(deck.cards) == 9

    @pytest.mark.asyncio
    async def test_get_deck_by_id_not_exists(self):
        with pytest.raises(ValueError) as ex:
            await db.get_deck_by_id(10)
            assert "No deck exists with ID 10" in str(ex.value)
