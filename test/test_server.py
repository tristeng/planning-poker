import pytest

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from pp.model import (
    Deck,
    Game,
    Player,
    GameState,
    GenericMessage,
    MessageType,
    PlayerState,
    ResetMessage,
    RoundState,
    GameSettings,
    RoundTimerSettings,
)
from pp.server import api, GAME_SESSIONS


@pytest.fixture
def client() -> TestClient:
    return TestClient(api)


@pytest.fixture
def game_settings() -> GameSettings:
    # the default game settings
    return GameSettings(round_timer_settings=None)


@pytest.fixture
def game(client, game_settings) -> Game:
    response = client.post(
        "/api/game", json={"name": "My first game", "deck_id": 1, "game_settings": game_settings.model_dump()}
    )
    return Game.model_validate(response.json())


@pytest.fixture
def game_settings_with_round_timer() -> GameSettings:
    # game settings with round timer defaults
    return GameSettings(round_timer_settings=RoundTimerSettings())


@pytest.fixture
def game_with_round_timer(client, game_settings_with_round_timer) -> Game:
    response = client.post(
        "/api/game",
        json={"name": "My first game", "deck_id": 1, "game_settings": game_settings_with_round_timer.model_dump()},
    )
    return Game.model_validate(response.json())


@pytest.fixture
def alice(client, game) -> Player:
    response = client.post(f"/api/join/{game.code}", json={"username": "Alice"})
    return Player.model_validate(response.json())


@pytest.fixture
def bob(client, game) -> Player:
    response = client.post(f"/api/join/{game.code}", json={"username": "Bob"})
    return Player.model_validate(response.json())


class TestServer:
    """Depends on the default MemoryDB"""

    def test_create_game(self, client: TestClient, game_settings: GameSettings):
        response = client.post(
            "/api/game", json={"name": "My first game", "deck_id": 1, "game_settings": game_settings.model_dump()}
        )
        assert response.status_code == 200

        game1 = Game.model_validate(response.json())
        assert game1.deck_id == 1
        assert game1.name == "My first game"
        assert game1.code is not None
        assert game1.game_settings is not None
        assert game1.game_settings.round_timer_settings is None

        response = client.post(
            "/api/game", json={"name": "My first game", "deck_id": 1, "game_settings": game_settings.model_dump()}
        )
        assert response.status_code == 200

        game2 = Game.model_validate(response.json())
        assert game1.code != game2.code

    def test_create_game_with_round_timer(self, client: TestClient, game_settings_with_round_timer: GameSettings):
        response = client.post(
            "/api/game",
            json={"name": "My first game", "deck_id": 1, "game_settings": game_settings_with_round_timer.model_dump()},
        )
        assert response.status_code == 200

        game1 = Game.model_validate(response.json())
        assert game1.deck_id == 1
        assert game1.name == "My first game"
        assert game1.code is not None
        assert game1.game_settings is not None
        assert game1.game_settings.round_timer_settings is not None
        assert game1.game_settings.round_timer_settings.maximum == 5
        assert game1.game_settings.round_timer_settings.warning == 4

    def test_create_game_invalid_deck(self, client: TestClient, game_settings: GameSettings):
        response = client.post(
            "/api/game", json={"name": "My first game", "deck_id": 999, "game_settings": game_settings.model_dump()}
        )
        assert response.status_code == 404

    def test_join_game(self, client: TestClient, game: Game):
        response = client.post(f"/api/join/{game.code}", json={"username": "Alice"})
        assert response.status_code == 200

        player = Player.model_validate(response.json())
        assert player.username == "Alice"
        assert player.id is not None

    def test_join_game_not_exists(self, client: TestClient):
        response = client.post("/api/join/abcd", json={"username": "Alice"})
        assert response.status_code == 404

    def test_decks(self, client: TestClient):
        response = client.get("/api/decks")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        deck = Deck.model_validate(data[0])
        assert deck.id == 1
        assert len(deck.cards) > 0

    def test_get_deck(self, client: TestClient):
        response = client.get("/api/decks/1")
        assert response.status_code == 200

        deck = Deck.model_validate(response.json())
        assert deck.id == 1
        assert len(deck.cards) > 0

        response = client.get("/api/decks/2")
        assert response.status_code == 404

    def test_websocket_endpoint_join_and_leave(self, client: TestClient, game: Game, alice: Player):
        assert game.code in GAME_SESSIONS

        with client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as websocket:
            # upon connection we should get the game state
            data = websocket.receive_json()
            msg: GenericMessage = GenericMessage.model_validate(data)
            assert msg.type == MessageType.STATE

            # parse the payload and assert that we only have a single player, alice
            payload = GameState.model_validate(msg.payload)
            assert payload.game == game
            assert len(payload.player_states) == 1
            key = str(alice.id)
            assert key in payload.player_states
            assert payload.player_states[key].player == alice
            assert payload.player_states[key].is_admin is True
            assert payload.player_states[key].is_connected is True
            assert payload.player_states[key].is_observing is False
            assert payload.player_states[key].has_voted is False

            # ensure that the we are in the init state (waiting for players to join)
            gs = GAME_SESSIONS[game.code]
            assert gs.round_state == RoundState.INIT

            # we should next get a broadcast message alice joined
            data = websocket.receive_json()
            msg = GenericMessage.model_validate(data)
            assert msg.type == MessageType.CONNECTED

            ps_payload = PlayerState.model_validate(msg.payload)
            assert ps_payload.player == alice
            assert ps_payload.is_admin is True
            assert ps_payload.is_connected is True
            assert ps_payload.is_observing is False
            assert ps_payload.has_voted is False

        # once alice disconnects, the game should delete itself since it has become empty
        assert game.code not in GAME_SESSIONS

    @staticmethod
    def _assert_upon_join(alice_ws: WebSocketTestSession, bob_ws: WebSocketTestSession, alice: Player, bob: Player):
        data = alice_ws.receive_json()
        msg: GenericMessage = GenericMessage.model_validate(data)
        assert msg.type == MessageType.STATE

        data = bob_ws.receive_json()
        msg = GenericMessage.model_validate(data)
        assert msg.type == MessageType.STATE

        # alice should get 2 connected messages, 1 broadcast for her and 1 for bob
        for idx in range(2):
            data = alice_ws.receive_json()
            msg = GenericMessage.model_validate(data)
            assert msg.type == MessageType.CONNECTED
            player_state = PlayerState.model_validate(msg.payload)
            if idx == 0:
                assert player_state.player == alice
            else:
                assert player_state.player == bob

        # bob should get a single connected message, 1 broadcast for himself connecting
        data = bob_ws.receive_json()
        msg = GenericMessage.model_validate(data)
        assert msg.type == MessageType.CONNECTED
        player_state = PlayerState.model_validate(msg.payload)
        assert player_state.player == bob

    @staticmethod
    def _get_players_from_player_message(
        alice_ws: WebSocketTestSession, bob_ws: WebSocketTestSession, msg_type: MessageType
    ) -> tuple[Player, Player]:
        msg_a: GenericMessage = GenericMessage.model_validate(alice_ws.receive_json())
        msg_b: GenericMessage = GenericMessage.model_validate(bob_ws.receive_json())

        assert msg_a.type == msg_type
        player_a = Player.model_validate(msg_a.payload)

        assert msg_b.type == msg_type
        player_b = Player.model_validate(msg_b.payload)

        return player_a, player_b

    def test_websocket_vote(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
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
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
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
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            # send a sync request
            alice_ws.send_json({"type": "SYNC", "payload": None})

            # we should get the game state
            msg: GenericMessage = GenericMessage.model_validate(alice_ws.receive_json())
            assert msg.type == MessageType.STATE

            # make sure its what we expect by parsing it
            GameState.model_validate(msg.payload)

    def test_websocket_sync_revealed_state(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            gs = GAME_SESSIONS[game.code]
            gs.round_state = RoundState.REVEALED

            # set some votes on the game session that we can reset
            gs.players[alice.id].vote = 3
            gs.players[bob.id].vote = 5

            # send a sync request
            alice_ws.send_json({"type": "SYNC", "payload": None})

            # we should get the game state followed by the vote state
            msg: GenericMessage = GenericMessage.model_validate(alice_ws.receive_json())
            assert msg.type == MessageType.STATE

            # make sure its what we expect by parsing it
            GameState.model_validate(msg.payload)

            # get and validate the vote state
            votes_msg: GenericMessage = GenericMessage.model_validate(alice_ws.receive_json())
            assert votes_msg.type == MessageType.REVEALGAME

            # we should have vote data for both players
            assert str(alice.id) in votes_msg.payload
            assert votes_msg.payload[str(alice.id)] == 3
            assert str(bob.id) in votes_msg.payload
            assert votes_msg.payload[str(bob.id)] == 5

    def test_websocket_reset(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            gs = GAME_SESSIONS[game.code]
            assert gs.is_admin(alice) is True
            assert gs.ticket_url is None
            assert gs.round_state == RoundState.INIT

            # set some votes on the game session that we can reset
            gs.players[alice.id].vote = 3
            gs.players[bob.id].vote = 5

            # send a reset request by a player
            bob_ws.send_json({"type": "RESET", "payload": None})

            # since bob sent it, nothing should happen
            assert gs.players[alice.id].vote == 3
            assert gs.players[bob.id].vote == 5
            assert gs.round_state == RoundState.INIT

            # send a reset request by the admin now along with the next ticket
            alice_ws.send_json({"type": "RESET", "payload": "http://127.0.0.1:5137/some/ticket/url"})

            # fetch the broadcast return message
            msg_a, msg_b = (
                ResetMessage.model_validate(alice_ws.receive_json()),
                ResetMessage.model_validate(bob_ws.receive_json()),
            )
            assert msg_a.type == MessageType.RESETGAME
            assert str(msg_a.payload) == "http://127.0.0.1:5137/some/ticket/url"
            assert msg_b.type == MessageType.RESETGAME
            assert str(msg_b.payload) == "http://127.0.0.1:5137/some/ticket/url"

            assert str(gs.ticket_url) == "http://127.0.0.1:5137/some/ticket/url"
            assert gs.round_state == RoundState.VOTING

            # make sure the votes have been reset in the session
            assert gs.players[alice.id].vote is None
            assert gs.players[bob.id].vote is None

    def test_websocket_reveal(self, client: TestClient, game: Game, alice: Player, bob: Player):
        with (
            client.websocket_connect(f"/api/ws/{alice.id}/{game.code}") as alice_ws,
            client.websocket_connect(f"/api/ws/{bob.id}/{game.code}") as bob_ws,
        ):
            # assert broadcast messages upon joining
            self._assert_upon_join(alice_ws, bob_ws, alice, bob)

            gs = GAME_SESSIONS[game.code]
            assert gs.is_admin(alice) is True
            assert gs.round_state == RoundState.INIT

            # set some votes on the game session that we can reveal
            gs.players[alice.id].vote = 3
            gs.players[bob.id].vote = 5

            # send a reveal request by the admin
            alice_ws.send_json({"type": "REVEAL", "payload": None})

            # fetch the broadcast return message
            msg_a: GenericMessage = GenericMessage.model_validate(alice_ws.receive_json())
            msg_b: GenericMessage = GenericMessage.model_validate(bob_ws.receive_json())

            assert msg_a.type == MessageType.REVEALGAME
            assert msg_b.type == MessageType.REVEALGAME

            assert msg_a.payload == msg_b.payload

            assert str(alice.id) in msg_a.payload
            assert msg_a.payload[str(alice.id)] == 3

            assert str(bob.id) in msg_a.payload
            assert msg_a.payload[str(bob.id)] == 5

            assert gs.round_state == RoundState.REVEALED

    def test_ws_join_invalid_player(self, client: TestClient, game: Game):
        player = Player(username="Cassie")

        # if a player attempts to open a WS without joining, we should get a message saying it was closed
        with client.websocket_connect(f"/api/ws/{player.id}/{game.code}") as ws:
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
        with client.websocket_connect(f"/api/ws/{player.id}/abcdefg") as ws:
            msg = ws.receive()

            assert "type" in msg
            assert msg["type"] == "websocket.close"

            assert "code" in msg
            assert msg["code"] == 4000

            assert "reason" in msg
            assert msg["reason"] == "No game with code 'abcdefg' exists!"
