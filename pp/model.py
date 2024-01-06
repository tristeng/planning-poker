import enum
import typing
import uuid

from pydantic import ConfigDict, BaseModel, Field, AnyHttpUrl, field_serializer


class CreateGame(BaseModel):
    """The body of a POST to create a new game."""

    name: str = Field(title="A name for the game", max_length=100)
    deck_id: int = Field(title="The ID of the deck to use")


class Game(CreateGame):
    """The return value from a POST to create a game."""

    code: str = Field(title="The game ID", max_length=8)


class Card(BaseModel):
    """The card model - contains labels and values."""

    label: str = Field(title="The display label for the card")
    value: float = Field(title="The numeric value for the card")


class Deck(BaseModel):
    """The deck model - contains an integer ID and a list of cards."""

    id: int = Field(title="The unique ID for this deck")
    name: str = Field(title="A name for this deck")
    cards: list[Card] = Field(title="The cards defined for this deck")


class Player(BaseModel):
    """The player model - a unique ID and username."""

    id: uuid.UUID = Field(title="Univerisally Unique ID for this player", default_factory=uuid.uuid4)
    username: str

    @field_serializer("id")
    def serialize_id(self, val: uuid.UUID, _info: typing.Any) -> str:
        return str(val)

    def __str__(self):
        return f"{self.username} ({self.id})"


class MessageType(str, enum.Enum):
    """The types of messages sent and received."""

    # client messages
    SUBMITVOTE = "SUBMITVOTE"  # submits a vote for the current story
    OBSERVE = "OBSERVE"  # puts client into observation mode (no voting)
    SYNC = "SYNC"  # requests game state

    # admin-only messages, in addition to above
    RESET = "RESET"  # resets the game - everyone's votes are cleared, in preparation for the next story
    REVEAL = "REVEAL"  # reveals all the cards

    # server messages to a single client
    STATE = "STATE"  # sends out the current game state - useful if the client becomes out-of-sync or has just joined

    # broadcast messages
    CONNECTED = "CONNECTED"  # broadcasts that a player has joined
    DISCONNECTED = "DISCONNECTED"  # broadcasts that a player has left
    PLAYERVOTED = "PLAYERVOTED"  # broadcasts that a particular player has submitted their vote
    RESETGAME = "RESETGAME"  # tells clients to reset the game
    REVEALGAME = "REVEALGAME"  # tells clients to show votes - vote data is sent with this message
    OBSERVING = "OBSERVING"  # tells clients that a particular player is observing and won't be voting

    @staticmethod
    def is_admin_message(msg_type: "MessageType") -> bool:
        return msg_type in [MessageType.RESET, MessageType.REVEAL]


class PlayerState(BaseModel):
    """The current state of a player."""

    player: Player
    is_connected: bool = False
    is_admin: bool = False
    is_observing: bool = False
    has_voted: bool = False


class GameState(BaseModel):
    """The current state of a game."""

    game: Game
    player_states: dict[str, PlayerState]
    ticket_url: typing.Optional[AnyHttpUrl] = None


Payload = typing.TypeVar("Payload")


class GenericMessage(BaseModel, typing.Generic[Payload]):
    """The generic message we use to communicate with clients - has a type and a payload."""

    type: MessageType
    payload: Payload
    model_config = ConfigDict(use_enum_values=True)


# define some concrete messages
Message = GenericMessage[typing.Any]  # the base message we expect from a client
PlayerMessage = GenericMessage[Player]  # provides generic information related to a player
PlayerStateMessage = GenericMessage[PlayerState]  # provides generic information on the player's state
SubmitVoteMessage = GenericMessage[float]  # a vote submission from a player
VoteDataMessage = GenericMessage[dict[str, typing.Optional[float]]]  # reveals the votes to all other players
GameStateMessage = GenericMessage[GameState]  # a message sent to clients to sync the game state from the server
ResetMessage = GenericMessage[typing.Optional[AnyHttpUrl]]  # a message to indicate the game should be reset
