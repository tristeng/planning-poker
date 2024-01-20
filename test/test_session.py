import json

import fastapi
import pytest

from pp.model import Game, Player, PlayerMessage, MessageType, GameSettings, RoundState
from pp.session import GameSession


@pytest.fixture
def game() -> Game:
    return Game(code="abcd", deck_id=1, name="A new game", game_settings=GameSettings())


@pytest.fixture
def game_session(game) -> GameSession:
    return GameSession(game=game)


@pytest.fixture
def alice() -> Player:
    return Player(username="alice")


@pytest.fixture
def bob() -> Player:
    return Player(username="bob")


@pytest.fixture
def mock_websocket(monkeypatch):
    class MockWebSocket:
        def __init__(self):
            self.data_list = []

        async def send_text(self, data):
            """Keep track of the data that was sent so we can assert its as expected"""
            self.data_list.append(json.loads(data))

    def mock_init():
        return MockWebSocket()

    monkeypatch.setattr(fastapi, "WebSocket", mock_init)


@pytest.fixture
def game_and_players(game_session: GameSession, alice: Player, bob: Player) -> tuple[GameSession, Player, Player]:
    game_session.add_player(player=alice)
    game_session.add_player(player=bob)
    return game_session, alice, bob


class TestSession:
    @pytest.mark.asyncio
    async def test_broadcast(self, game_and_players, mock_websocket):
        game_session, alice, bob = game_and_players

        # by default, each player won't have a websocket associated with them, so a broadcast should be a no-op
        msg = PlayerMessage(type=MessageType.CONNECTED, payload=alice)
        num_sent = await game_session.broadcast(msg)
        assert num_sent == 0

        alice_ws = fastapi.WebSocket()
        game_session.set_websocket(alice, alice_ws)

        num_sent = await game_session.broadcast(msg)
        assert num_sent == 1
        assert len(alice_ws.data_list) == 1
        assert alice_ws.data_list[0]["type"] == "CONNECTED"
        player = Player.model_validate(alice_ws.data_list[0]["payload"])
        assert player == alice

        bob_ws = fastapi.WebSocket()
        game_session.set_websocket(bob, bob_ws)

        msg = PlayerMessage(type=MessageType.CONNECTED, payload=bob)
        num_sent = await game_session.broadcast(msg)
        assert num_sent == 2
        assert len(alice_ws.data_list) == 2
        assert alice_ws.data_list[1]["type"] == "CONNECTED"
        player = Player.model_validate(alice_ws.data_list[1]["payload"])
        assert player == bob
        assert len(bob_ws.data_list) == 1
        assert bob_ws.data_list[0]["type"] == "CONNECTED"
        player = Player.model_validate(alice_ws.data_list[1]["payload"])
        assert player == bob

    def test_add_player(self, game_session, alice, bob):
        # should be no players to start
        assert not game_session.players

        # assume alice is the one who starts the game
        game_session.add_player(player=alice)
        assert len(game_session.players) == 1
        assert game_session.players[alice.id].player == alice
        assert game_session.players[alice.id].websocket is None

        # alice should be the admin
        assert game_session.admin_id == alice.id

        # assert that adding alice again has no effect
        game_session.add_player(player=alice)
        assert len(game_session.players) == 1
        assert game_session.players[alice.id].player == alice

        # now add bob
        game_session.add_player(player=bob)
        assert len(game_session.players) == 2
        assert game_session.players[bob.id].player == bob
        assert game_session.players[bob.id].websocket is None
        assert game_session.admin_id != bob.id

    def test_remove_player(self, game_and_players):
        game_session, alice, bob = game_and_players

        # default game has 2 players
        assert len(game_session.players) == 2

        # remove alice the admin
        game_session.remove_player(alice)
        assert len(game_session.players) == 1
        assert alice.id not in game_session.players
        assert bob.id in game_session.players

        # remove bob
        game_session.remove_player(bob)
        assert len(game_session.players) == 0
        assert bob.id not in game_session.players

        # remove bob again to make sure there are no errors
        game_session.remove_player(bob)

        # ensure that even though alice has left, she is still considered the admin, in case she rejoins
        assert game_session.is_admin(alice)

    def test_set_websocket(self, game_and_players, mock_websocket):
        game_session, alice, bob = game_and_players

        # by default, websockets should be None
        assert game_session.players[alice.id].websocket is None
        assert game_session.players[bob.id].websocket is None

        alice_ws = fastapi.WebSocket()
        game_session.set_websocket(alice, alice_ws)
        assert game_session.players[alice.id].websocket == alice_ws
        assert game_session.players[bob.id].websocket is None

        bob_ws = fastapi.WebSocket()
        game_session.set_websocket(bob, bob_ws)
        assert game_session.players[alice.id].websocket == alice_ws
        assert game_session.players[bob.id].websocket == bob_ws

        # test no error if we try to apply functionality for a user not part of the game
        frank = Player(username="frank")
        game_session.set_websocket(frank, bob_ws)  # helps to get our coverage up to 100%

    def test_clear_websocket(self, game_and_players, mock_websocket):
        game_session, alice, bob = game_and_players

        alice_ws = fastapi.WebSocket()
        game_session.set_websocket(alice, alice_ws)
        bob_ws = fastapi.WebSocket()
        game_session.set_websocket(bob, bob_ws)

        assert game_session.players[alice.id].websocket == alice_ws
        assert game_session.players[bob.id].websocket == bob_ws

        game_session.clear_websocket(alice)
        assert game_session.players[alice.id].websocket is None
        assert game_session.players[alice.id].vote is None
        assert game_session.players[alice.id].is_observing is False
        assert game_session.players[bob.id].websocket == bob_ws

        game_session.clear_websocket(bob)
        assert game_session.players[bob.id].websocket is None
        assert game_session.players[bob.id].vote is None
        assert game_session.players[bob.id].is_observing is False
        assert game_session.players[bob.id].websocket is None

        # test no error if we try to apply functionality for a user not part of the game
        frank = Player(username="frank")
        game_session.clear_websocket(frank)  # helps to get our coverage up to 100%

    def test_is_admin(self, game_and_players):
        game_session, alice, bob = game_and_players

        assert game_session.is_admin(alice) is True
        assert game_session.is_admin(bob) is False

    def test_update_vote(self, game_and_players):
        game_session, alice, bob = game_and_players

        # by default, votes should be None
        assert game_session.players[alice.id].vote is None
        assert game_session.players[bob.id].vote is None

        game_session.update_vote(alice, 5)
        assert game_session.players[alice.id].vote == 5
        assert game_session.players[bob.id].vote is None

        game_session.update_vote(alice, 3)
        assert game_session.players[alice.id].vote == 3
        assert game_session.players[bob.id].vote is None

        game_session.update_vote(bob, 1)
        assert game_session.players[alice.id].vote == 3
        assert game_session.players[bob.id].vote == 1

        # test no error if we try to apply functionality for a user not part of the game
        frank = Player(username="frank")
        game_session.update_vote(frank, 1)  # helps to get our coverage up to 100%

    def test_reset_votes(self, game_and_players):
        game_session, alice, bob = game_and_players

        game_session.update_vote(alice, 3)
        game_session.update_vote(bob, 1)
        assert game_session.players[alice.id].vote == 3
        assert game_session.players[bob.id].vote == 1

        game_session.reset_votes()
        assert game_session.players[alice.id].vote is None
        assert game_session.players[bob.id].vote is None

    def test_toggle_observing(self, game_and_players):
        game_session, alice, bob = game_and_players

        assert game_session.players[alice.id].is_observing is False
        assert game_session.players[bob.id].is_observing is False

        game_session.toggle_observing(alice)

        assert game_session.players[alice.id].is_observing is True
        assert game_session.players[bob.id].is_observing is False

        # test no error if we try to apply functionality for a user not part of the game
        frank = Player(username="frank")
        game_session.toggle_observing(frank)  # helps to get our coverage up to 100%

    def test_votes(self, game_and_players):
        game_session, alice, bob = game_and_players

        votes = game_session.votes
        assert votes == {str(alice.id): None, str(bob.id): None}

        game_session.update_vote(alice, 3)
        votes = game_session.votes
        assert votes == {str(alice.id): 3, str(bob.id): None}

        game_session.update_vote(bob, 1)
        votes = game_session.votes
        assert votes == {str(alice.id): 3, str(bob.id): 1}

    def test_empty(self, game_and_players, mock_websocket, game):
        game_session, alice, bob = game_and_players

        # even though there are 2 players registered, they aren't currently connected, so we consider that empty
        assert game_session.empty is True

        alice_ws = fastapi.WebSocket()
        game_session.set_websocket(alice, alice_ws)

        assert game_session.empty is False

        game_session.clear_websocket(alice)
        assert game_session.empty is True

        # new game sessions will have no players, so they are also considered empty
        gs = GameSession(game)
        assert gs.empty is True

    def test_state(self, game_and_players, mock_websocket):
        game_session, alice, bob = game_and_players

        state = game_session.state
        assert len(state.player_states) == 2
        assert str(alice.id) in state.player_states
        assert str(bob.id) in state.player_states

        assert state.game is not None
        assert state.game.game_settings is not None
        assert state.game.game_settings.round_timer_settings is None
        assert state.ticket_url is None
        assert state.round_start is None
        assert state.round_state == RoundState.INIT

        # initial state of our test game session means no players connected, have voted or are observing
        assert all([ps.is_connected is False for ps in state.player_states.values()])
        assert all([ps.has_voted is False for ps in state.player_states.values()])
        assert all([ps.is_observing is False for ps in state.player_states.values()])

        alice_ws = fastapi.WebSocket()
        game_session.set_websocket(alice, alice_ws)
        game_session.toggle_observing(alice)

        bob_ws = fastapi.WebSocket()
        game_session.set_websocket(bob, bob_ws)
        game_session.update_vote(bob, 3)

        state = game_session.state
        assert len(state.player_states) == 2

        assert str(alice.id) in state.player_states
        alice_state = state.player_states[str(alice.id)]

        assert alice_state.is_observing is True
        assert alice_state.is_admin is True
        assert alice_state.is_connected is True
        assert alice_state.has_voted is False

        assert str(bob.id) in state.player_states
        bob_state = state.player_states[str(bob.id)]

        assert bob_state.is_observing is False
        assert bob_state.is_admin is False
        assert bob_state.is_connected is True
        assert bob_state.has_voted is True

    def test_reset_round(self, game_and_players):
        game_session, alice, bob = game_and_players

        game_session.update_vote(alice, 3)
        game_session.update_vote(bob, 1)
        assert game_session.players[alice.id].vote == 3
        assert game_session.players[bob.id].vote == 1

        game_session.reset_round("https://someurl.com/ticket/1")
        assert game_session.players[alice.id].vote is None
        assert game_session.players[bob.id].vote is None
        assert game_session.ticket_url == "https://someurl.com/ticket/1"
        assert game_session.round_state == "VOTING"
        assert game_session.round_start is not None

        state = game_session.state
        assert state.game is not None
        assert state.game.game_settings is not None
        assert state.game.game_settings.round_timer_settings is None
        assert str(state.ticket_url) == "https://someurl.com/ticket/1"
        assert state.round_start is not None
        assert state.round_state == RoundState.VOTING
