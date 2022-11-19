import pytest

from fastapi import WebSocket
from fastapi.testclient import TestClient

from pp.model import Deck, Game, Player, GameState, GenericMessage, MessageType, PlayerState, ResetMessage
from pp.server import api, GAME_SESSIONS


@pytest.fixture
def client() -> TestClient:
    return TestClient(api)


@pytest.fixture
def game(client) -> Game:
    response = client.post("/game", json={"name": "My first game", "deck_id": 1})
    return Game.parse_obj(response.json())


@pytest.fixture
def alice(client, game) -> Player:
    response = client.post(f"/join/{game.code}", json={"username": "Alice"})
    return Player.parse_obj(response.json())


@pytest.fixture
def bob(client, game) -> Player:
    response = client.post(f"/join/{game.code}", json={"username": "Bob"})
    return Player.parse_obj(response.json())


class TestServer:
    """Depends on the default MemoryDB"""

    def test_create_game(self, client: TestClient):
        response = client.post("/game", json={"name": "My first game", "deck_id": 1})
        assert response.status_code == 200

        game1 = Game.parse_obj(response.json())
        assert game1.deck_id == 1
        assert game1.name == "My first game"
        assert game1.code is not None

        response = client.post("/game", json={"name": "My first game", "deck_id": 1})
        assert response.status_code == 200

        game2 = Game.parse_obj(response.json())
        assert game1.code != game2.code

    def test_create_game_invalid_deck(self, client: TestClient):
        response = client.post("/game", json={"name": "My first game", "deck_id": 999})
        assert response.status_code == 404

    def test_join_game(self, client: TestClient, game: Game):
        response = client.post(f"/join/{game.code}", json={"username": "Alice"})
        assert response.status_code == 200

        player = Player.parse_obj(response.json())
        assert player.username == "Alice"
        assert player.id is not None

    def test_join_game_not_exists(self, client: TestClient):
        response = client.post("/join/abcd", json={"username": "Alice"})
        assert response.status_code == 404

    def test_decks(self, client: TestClient):
        response = client.get("/decks")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        deck = Deck.parse_obj(data[0])
        assert deck.id == 1
        assert len(deck.cards) > 0

    def test_get_deck(self, client: TestClient):
        response = client.get("/decks/1")
        assert response.status_code == 200

        deck = Deck.parse_obj(response.json())
        assert deck.id == 1
        assert len(deck.cards) > 0

        response = client.get("/decks/2")
        assert response.status_code == 404

    def test_websocket_endpoint_join_and_leave(self, client: TestClient, game: Game, alice: Player):
        assert game.code in GAME_SESSIONS

        with client.websocket_connect(f"/ws/{alice.id}/{game.code}") as websocket:
            # upon connection we should get the game state
            data = websocket.receive_json()
            msg = GenericMessage.parse_obj(data)
            assert msg.type == MessageType.STATE

            # parse the payload and assert that we only have a single player, alice
            payload = GameState.parse_obj(msg.payload)
            assert payload.game == game
            assert len(payload.player_states) == 1
            key = str(alice.id)
            assert key in payload.player_states
            assert payload.player_states[key].player == alice
            assert payload.player_states[key].is_admin is True
            assert payload.player_states[key].is_connected is True
            assert payload.player_states[key].is_observing is False
            assert payload.player_states[key].has_voted is False

            # we should next get a broadcast message alice joined
            data = websocket.receive_json()
            msg = GenericMessage.parse_obj(data)
            assert msg.type == MessageType.CONNECTED

            payload = PlayerState.parse_obj(msg.payload)
            assert payload.player == alice
            assert payload.is_admin is True
            assert payload.is_connected is True
            assert payload.is_observing is False
            assert payload.has_voted is False

        # once alice disconnects, the game should delete itself since it has become empty
        assert game.code not in GAME_SESSIONS

    @staticmethod
    def _assert_upon_join(alice_ws: WebSocket, bob_ws: WebSocket, alice: Player, bob: Player):
        data = alice_ws.receive_json()
        msg = GenericMessage.parse_obj(data)
        assert msg.type == MessageType.STATE

        data = bob_ws.receive_json()
        msg = GenericMessage.parse_obj(data)
        assert msg.type == MessageType.STATE

        # alice should get 2 connected messages, 1 broadcast for her and 1 for bob
        for idx in range(2):
            data = alice_ws.receive_json()
            msg = GenericMessage.parse_obj(data)
            assert msg.type == MessageType.CONNECTED
            player_state = PlayerState.parse_obj(msg.payload)
            if idx == 0:
                assert player_state.player == alice
            else:
                assert player_state.player == bob

        # bob should get a single connected message, 1 broadcast for himself connecting
        data = bob_ws.receive_json()
        msg = GenericMessage.parse_obj(data)
        assert msg.type == MessageType.CONNECTED
        player_state = PlayerState.parse_obj(msg.payload)
        assert player_state.player == bob

    @staticmethod
    def _get_players_from_player_message(
        alice_ws: WebSocket, bob_ws: WebSocket, msg_type: MessageType
    ) -> tuple[Player, Player]:
        msg_a, msg_b = GenericMessage.parse_obj(alice_ws.receive_json()), GenericMessage.parse_obj(
            bob_ws.receive_json()
        )

        assert msg_a.type == msg_type
        player_a = Player.parse_obj(msg_a.payload)

        assert msg_b.type == msg_type
        player_b = Player.parse_obj(msg_b.payload)

        return player_a, player_b

    def test_websocket_vote(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            # bob submits vote
            bob_ws.send_json({"type": "SUBMITVOTE", "payload": 3})

            # both alice and bob should get a broadcast message confirming bob voted
            player_a, player_b = self._get_players_from_player_message(alice_ws, bob_ws, MessageType.PLAYERVOTED)

            assert player_a == bob
            assert player_b == bob

            # ensure the game session recorded it properly
            gs = GAME_SESSIONS[game.code]
            assert gs.players[alice.id].vote is None
            assert gs.players[bob.id].vote == 3

    def test_websocket_observe(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            alice_ws.send_json({"type": "OBSERVE", "payload": None})

            # both alice and bob should get a broadcast message confirming alice is observing
            player_a, player_b = self._get_players_from_player_message(alice_ws, bob_ws, MessageType.OBSERVING)

            assert player_a == alice
            assert player_b == alice

            # ensure the game session recorded it properly
            # ensure the game session recorded it properly
            gs = GAME_SESSIONS[game.code]
            assert gs.players[alice.id].is_observing is True
            assert gs.players[bob.id].is_observing is False

    def test_websocket_sync(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            # send a sync request
            alice_ws.send_json({"type": "SYNC", "payload": None})

            # we should get the game state
            msg = GenericMessage.parse_obj(alice_ws.receive_json())
            assert msg.type == MessageType.STATE

            # make sure its what we expect by parsing it
            GameState.parse_obj(msg.payload)

    def test_websocket_reset(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            gs = GAME_SESSIONS[game.code]
            assert gs.is_admin(alice) is True

            # set some votes on the game session that we can reset
            gs.players[alice.id].vote = 3
            gs.players[bob.id].vote = 5

            # send a reset request by a player
            bob_ws.send_json({"type": "RESET", "payload": None})

            # since bob sent it, nothing should happen
            assert gs.players[alice.id].vote == 3
            assert gs.players[bob.id].vote == 5

            # send a reset request by the admin now
            alice_ws.send_json({"type": "RESET", "payload": "http://127.0.0.1:5137/some/ticket/url"})

            # fetch the broadcast return message
            msg_a, msg_b = ResetMessage.parse_obj(alice_ws.receive_json()), ResetMessage.parse_obj(
                bob_ws.receive_json()
            )
            assert msg_a.type == MessageType.RESETGAME
            assert msg_a.payload == "http://127.0.0.1:5137/some/ticket/url"
            assert msg_b.type == MessageType.RESETGAME
            assert msg_b.payload == "http://127.0.0.1:5137/some/ticket/url"

            # make sure the votes have been reset in the session
            assert gs.players[alice.id].vote is None
            assert gs.players[bob.id].vote is None

    def test_websocket_reveal(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            gs = GAME_SESSIONS[game.code]
            assert gs.is_admin(alice) is True

            # set some votes on the game session that we can reveal
            gs.players[alice.id].vote = 3
            gs.players[bob.id].vote = 5

            # send a reveal request by the admin
            alice_ws.send_json({"type": "REVEAL", "payload": None})

            # fetch the broadcast return message
            msg_a, msg_b = GenericMessage.parse_obj(alice_ws.receive_json()), GenericMessage.parse_obj(
                bob_ws.receive_json()
            )
            assert msg_a.type == MessageType.REVEALGAME
            assert msg_b.type == MessageType.REVEALGAME

            assert msg_a.payload == msg_b.payload

            assert str(alice.id) in msg_a.payload
            assert msg_a.payload[str(alice.id)] == 3

            assert str(bob.id) in msg_a.payload
            assert msg_a.payload[str(bob.id)] == 5

    def test_ws_join_invalid_player(self, client: TestClient, game: Game):
        player = Player(username="Cassie")

        # if a player attempts to open a WS without joining, we should get a message saying it was closed
        with client.websocket_connect(f"/ws/{player.id}/{game.code}") as ws:
            msg = ws.receive()

            assert "type" in msg
            assert msg["type"] == "websocket.close"

            assert "code" in msg
            assert msg["code"] == 4001

            assert "reason" in msg
            assert msg["reason"] == f"Player with ID '{player.id}' not found in game with code '{game.code}'!"

    def test_ws_join_invalid_game(self, client: TestClient):
        player = Player(username="Cassie")

        # if a player attempts to open a WS to a game that doesn't exist, we should get a message saying it was closed
        with client.websocket_connect(f"/ws/{player.id}/abcdefg") as ws:
            msg = ws.receive()

            assert "type" in msg
            assert msg["type"] == "websocket.close"

            assert "code" in msg
            assert msg["code"] == 4000

            assert "reason" in msg
            assert msg["reason"] == "No game with code 'abcdefg' exists!"
