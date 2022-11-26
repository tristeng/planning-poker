import logging
import os
import pathlib
from http import HTTPStatus
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Path, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from pp.db import MemoryDeckDB
from pp.model import (
    Game,
    CreateGame,
    Deck,
    Player,
    Message,
    MessageType,
    SubmitVoteMessage,
    PlayerMessage,
    VoteDataMessage,
    GameStateMessage,
    PlayerStateMessage,
    ResetMessage,
)
from pp.session import GameSession
from pp.utils import random_code, CODE_RE

logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)

api = FastAPI(
    title="Planning Poker",
    description="A minimalist poker planning web application backend.",
)

origins = [
    "http://127.0.0.1",
    "http://127.0.0.1:5173",  # the default origin when running the frontend dev server
]

# allow the CORS origins to be extended via environment variable
pp_cors_urls = os.getenv("PP_CORS_URLS", None)
if pp_cors_urls is not None:
    log.info(f"Attempting to parse and add CORS origins from '{pp_cors_urls}'...")
    urls = set(map(lambda x: x.strip(), pp_cors_urls.split(",")))
    origins = set(origins) | urls
    log.info(f"Updated CORS origins: {', '.join(origins)}")

api.add_middleware(
    CORSMiddleware,
    allow_origins=list(origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GAME_SESSIONS: dict[str, GameSession] = {}
DB = MemoryDeckDB(pathlib.Path("conf/decks.json"))


@api.post("/api/game", response_model=Game)
async def create_game(game: CreateGame):
    """Create a new planning poker game."""
    # make sure the deck exists
    try:
        deck = await DB.get_deck_by_id(game.deck_id)
    except ValueError as ex:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(ex))

    code = random_code()
    while code in GAME_SESSIONS:  # pragma: no cover
        code = random_code()

    game = Game(code=code, name=game.name, deck_id=deck.id)
    GAME_SESSIONS[code] = GameSession(game=game)
    log.info(f"New game called {game.name} created, using deck {game.deck_id} and unique code '{code}'")
    return game


@api.post("/api/join/{code}", response_model=Player)
async def join_game(player: Player, code: str = Path(regex=CODE_RE)):
    """Join an existing planning poker game."""
    if code not in GAME_SESSIONS:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No existing game found with code '{code}'")

    session = GAME_SESSIONS[code]
    session.add_player(player)
    return player


@api.get("/api/decks", response_model=list[Deck])
async def decks():
    """Returns a list of the available decks."""
    return await DB.get_decks()


@api.get("/api/decks/{deck_id}", response_model=Deck)
async def decks(deck_id: int = Path(gt=0)):
    """Returns a deck by ID"""
    try:
        return await DB.get_deck_by_id(deck_id)
    except ValueError as ex:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(ex))


@api.websocket("/api/ws/{player_id}/{code}")
async def websocket_endpoint(websocket: WebSocket, player_id: UUID, code: str = Path(regex=CODE_RE)):
    await websocket.accept()
    log.info(f"Player with ID '{player_id}' is connecting...")

    # if the session doesn't exist, close the connection and use a custom error code/msg to send back to the client
    if code not in GAME_SESSIONS:
        log.error(f"Player with ID '{player_id}' attempted to join a game that does not exist, using code '{code}'")
        await websocket.close(code=4000, reason=f"No game with code '{code}' exists!")
        return

    # cache the session
    session = GAME_SESSIONS[code]

    # make sure the player has joined this game
    if player_id not in session.players:
        log.error(f"No player with ID '{player_id}' exists in game with code '{code}'")
        await websocket.close(code=4001, reason=f"Player with ID '{player_id}' not found in game with code '{code}'!")
        return

    # cache the player
    player = session.players[player_id].player
    log.info(f"Player with ID '{player_id}' and username {player} has connected")
    session.set_websocket(player=player, websocket=websocket)
    try:
        # send the client the current state of the game
        await websocket.send_text(GameStateMessage(type=MessageType.STATE, payload=session.state).json())

        # let other's know this user has connected
        await session.broadcast(PlayerStateMessage(type=MessageType.CONNECTED, payload=session.player_state(player.id)))

        while True:
            # wait for a message from the client
            data = await websocket.receive_json()

            if log.isEnabledFor(logging.DEBUG):  # pragma: no cover
                log.debug(f"Received raw data from {player}: {data}")

            try:
                # parse/validate the message
                msg = Message.parse_obj(data)

                # handle the message based on its type
                if msg.type == MessageType.SUBMITVOTE:
                    # player submitted a vote, let all other clients know
                    msg = SubmitVoteMessage.parse_obj(data)

                    # should really validate the vote is part of the selected deck...
                    session.update_vote(player=player, vote=msg.payload)

                    await session.broadcast(PlayerMessage(type=MessageType.PLAYERVOTED, payload=player))

                # client's should handle this as a toggle
                if msg.type == MessageType.OBSERVE:
                    session.toggle_observing(player=player)
                    await session.broadcast(PlayerMessage(type=MessageType.OBSERVING, payload=player))

                # clients can request to sync with the current game state
                if msg.type == MessageType.SYNC:
                    await websocket.send_text(GameStateMessage(type=MessageType.STATE, payload=session.state).json())

                if MessageType.is_admin_message(msg.type):
                    if session.is_admin(player):
                        if msg.type == MessageType.RESET:
                            # admin may have passed along the link for the next round, so parse it out
                            msg = ResetMessage.parse_obj(data)

                            # tell all clients to reset, and reset the server side vote data
                            session.reset_votes()

                            # broadcast the message along with the optional payload (link to next ticket)
                            await session.broadcast(ResetMessage(type=MessageType.RESETGAME, payload=msg.payload))

                        if msg.type == MessageType.REVEAL:
                            # broadcast all the user's votes at the same time
                            await session.broadcast(VoteDataMessage(type=MessageType.REVEALGAME, payload=session.votes))
                    else:
                        log.error(f"Player {player} sent an admin message but is not admin!")

            except ValidationError:  # pragma: no cover
                # don't kill the connection on invalid messages, just log it and move on
                log.exception(f"Invalid message received from user {player} - ignoring: {data}")

    except WebSocketDisconnect:
        log.info(f"{player} has disconnected")
        await session.broadcast(PlayerMessage(type=MessageType.DISCONNECTED, payload=player))
        session.clear_websocket(player)

        # check if the game session has become empty, in which case clean up the memory
        if session.empty:
            log.info(f"Last player left game session '{code}' - deleting game session")
            del GAME_SESSIONS[code]
