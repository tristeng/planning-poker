import asyncio
import dataclasses
import datetime
import logging
import typing
import uuid

from fastapi import WebSocket

from pp.model import Game, Player, GenericMessage, GameState, PlayerState

log = logging.getLogger(__name__)


@dataclasses.dataclass
class PlayerData:
    """Session data for the player"""

    player: Player
    websocket: typing.Optional[WebSocket] = None
    vote: typing.Optional[float] = None
    is_observing: bool = False


class GameSession:
    def __init__(self, game: Game):
        """Creates a new game session.

        :param game: the game data
        """
        self.game = game
        self.players: dict[uuid.UUID, PlayerData] = {}
        self.admin_id: typing.Optional[Player] = None
        self.created: datetime.datetime = datetime.datetime.utcnow()

    async def broadcast(self, payload: GenericMessage) -> int:
        """Broadcasts a message to all players in this game.

        :param payload: the payload data to send to the players
        :return: the number of messages sent
        """
        data = payload.model_dump_json()

        # players join the game before creating a websocket, so only broadcast to players with a websocket
        connected_players: typing.Iterable[PlayerData] = filter(
            lambda x: x.websocket is not None, self.players.values()
        )

        # send the message out async
        tasks = [player.websocket.send_text(data) for player in connected_players]  # type: ignore

        if log.isEnabledFor(logging.DEBUG):  # pragma: no cover
            log.debug(f"Game '{self.game.code}': Broadcasting message to {len(tasks)} player(s): {data}")

        if tasks:
            # don't raise exceptions, return them
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # if there were errors, log them
            errors = filter(lambda x: isinstance(x, Exception), results)
            for err in errors:  # pragma: no cover
                log.error(f"Game '{self.game.code}': Encountered error during broadcast: {err}")

        return len(tasks)

    def add_player(self, player: Player):
        """Adds a player to the session.

        :param player: the player to add
        """
        if self.admin_id is None:
            # assume first player joining is the admin
            # NOTE: this player stays the admin for the life of the session - no other player can elevate to admin
            log.info(f"Game '{self.game.code}': Registering player {player} as the admin")
            self.admin_id = player.id  # type: ignore

        if player.id not in self.players:
            log.info(f"Game '{self.game.code}': Adding player {player} to game")
            self.players[player.id] = PlayerData(player=player)

    def remove_player(self, player: Player):
        """Remove a player from the session.

        :param player: the player data to remove
        """
        if player.id in self.players:
            log.info(f"Game '{self.game.code}': Removing player {player} from game")
            del self.players[player.id]
            if self.is_admin(player):
                log.warning(f"Game '{self.game.code}': The admin player {player} has been removed from the session")

    def set_websocket(self, player: Player, websocket: WebSocket):
        """Attach a websocket to a player.

        :param player: the player
        :param websocket: the websocket
        """
        if player.id in self.players:
            log.info(f"Game '{self.game.code}': Assigning websocket to player {player}")
            self.players[player.id].websocket = websocket

    def clear_websocket(self, player: Player):
        """Detach a websocket from a player - generally when they have disconnected.

        :param player: the player
        """
        if player.id in self.players:
            log.info(f"Game '{self.game.code}': Clearing websocket from player {player}")
            self.players[player.id].websocket = None

            # reset player data state in case they join up again
            self.players[player.id].is_observing = False
            self.players[player.id].vote = None

    def is_admin(self, player: Player) -> bool:
        """Check if a player is the game admin.

        :param player: the player to check
        :return: true if the given player is the admin
        """
        return self.admin_id == player.id

    def update_vote(self, player: Player, vote: float):
        """Update the players vote.

        :param player: the player in question
        :param vote: the value of the vote
        """
        if player.id in self.players:
            log.info(f"Game '{self.game.code}': Updating vote for {player} to {vote}")
            self.players[player.id].vote = vote

    def reset_votes(self):
        """Reset all the players' server side vote data in preparation for the next game."""
        log.info(f"Game '{self.game.code}': Resetting {len(self.players)} players' votes")
        for player_id in self.players.keys():
            self.players[player_id].vote = None

    def toggle_observing(self, player: Player):
        """Toggles if a player is observing or not - initially starts as not observing

        :param player: the player to toggle
        """
        if player.id in self.players:
            log.info(
                f"Game '{self.game.code}': Toggling observer mode for player {player}, "
                f"currently at {'not ' if not self.players[player.id].is_observing else ''}observing"
            )
            self.players[player.id].is_observing = not self.players[player.id].is_observing

    @property
    def votes(self) -> dict[str, typing.Optional[float]]:
        """Fetches the current player votes.

        :return: a dictionary of player id to their vote value
        """
        log.info(f"Game '{self.game.code}': Fetching vote data")
        return {str(k): v.vote for k, v in self.players.items()}

    @property
    def empty(self) -> bool:
        """Returns true if there are no players or if all the players have disconnected

        :return: True if all players have disconnected.
        """
        log.info(f"Game '{self.game.code}': Checking if game is empty")
        return not self.players or all([p.websocket is None for p in self.players.values()])

    @property
    def state(self) -> GameState:
        """Gets the current state of the game.

        :return: the current game state
        """
        log.info(f"Game '{self.game.code}': Fetching the current game state")
        player_states = {
            str(pd.player.id): PlayerState(
                player=pd.player,
                is_connected=pd.websocket is not None,
                is_admin=self.is_admin(pd.player),
                is_observing=pd.is_observing,
                has_voted=pd.vote is not None,
            )
            for pd in self.players.values()
        }
        return GameState(game=self.game, player_states=player_states)

    def player_state(self, key: uuid.UUID) -> PlayerState:
        """Gets the requested players state.

        :param key: the UUID for the player
        :return: the player state
        """
        pd = self.players[key]
        return PlayerState(
            player=pd.player,
            is_connected=pd.websocket is not None,
            is_admin=self.is_admin(pd.player),
            is_observing=pd.is_observing,
            has_voted=pd.vote is not None,
        )
