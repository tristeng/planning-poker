# Planning Poker
![python package](https://github.com/tristeng/planning-poker/actions/workflows/python-package.yml/badge.svg)

This project is a minimalist poker planning web application backend. The companion frontend application can be found
[here](https://github.com/tristeng/planning-poker-ui).

The application has no authentication or authorization, allowing any user to create a planning poker room and invite
guests using a unique code.

## About
Planning poker is a consensus-based estimation technique used to estimate effort or relative size of development goals.

The API supports a small set of HTTP endpoints that allow players to create and join games, as well as endpoints for
fetching the supported decks. The API also supports WebSocket connections for real-time updates to the game state.

The game admin will create a game using the relevant POST endpoint which returns a unique game code. The frontend should
then immediately connect to the WebSocket endpoint using the game code since the first player to join the game will 
become the admin. The admin can then invite other players to join the game using the unique game code.

Players can join the created game using the unique code generated when the game was created. Players can also leave and
rejoin so long as the frontend application stores their unique ID.

The round state machine is as follows:
- `INIT`: a new game has been created but no rounds have been started (players are joining)
- `VOTING`: a round has been started and players are voting
- `REVEALED`: the votes have been revealed and the round is over

The round moves from `INIT` to `VOTING` when the admin starts the round. The round moves from `VOTING` to `REVEALED`
when the admin reveals the votes. The round moves from `REVEALED` to `VOTING` when the admin starts a new round.

### Decks
At the moment, decks are defined in a JSON file in the `conf` directory. The default deck is the Fibonacci sequence
The default deck is always available, but additional decks can be defined in the `conf/decks.json` file. The file 
contains a JSON array of decks, where each deck is an object with the following properties:
- `id`: The unique integer ID of the deck
- `name`: The name of the deck
- `cards`: An array of cards in the deck

Each card supports the following properties:
- `label`: The viewable label of the card (e.g. instead of showing 0.5, show ½)
- `value`: The value of the card - the actual float value that will be used for calculations

The default deck database is an in-memory object that loads the decks from the JSON file on startup. This class is 
called `MemoryDeckDB` and is a child class of `DeckDB`. If you wish to use a different method to store decks, you can
override the `DeckDB` class and implement your own methods.

## Development
This project supports Python 3.11 or greater (currently tested on 3.11, 3.12, and 3.13) and uses 
[FastAPI](https://fastapi.tiangolo.com/) as the web framework.

### Poetry
This project uses [Poetry](https://python-poetry.org/) for dependency management. To install Poetry, follow the 
instructions [here](https://python-poetry.org/docs/#installation).

To install the dependencies, run:
```shell
poetry install
```

To run the application in development mode, run:
```shell
poetry run uvicorn pp.server:app --reload
```

### Testing
To run the tests, run:
```shell
poetry run pytest
```

To run tests with coverage, run:
```shell
poetry run coverage run
```

To see the coverage report, run:
```shell
poetry run coverage report
```

### Linting, Formatting, and Type Checking
This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and 
[mypy](https://www.mypy-lang.org/) for static type checking. To ensure that the code is properly formatted, you can run
checks using each.

To run ruff linter and apply fixes automatically:
```shell
poetry run ruff check --fix .
```

To run ruff formatter and apply fixes automatically:
```shell
poetry run ruff format .
```

To run mypy static type checking:
```shell
poetry run mypy
```

## Docker
To build the Docker image:
```shell
docker build -t planningpoker .
```

To run the image on port 8000:
```shell
docker run -d --name pp -p 8000:80 planningpoker
```

You may also need to set the `PP_CORS_URLS` environment variable if the frontend is making requests from an origin that 
is not the default (i.e. `http://127.0.0.1` or `http://127.0.0.1:5173`):
```shell
docker run -d --name pp -p 8000:80 -e "PP_CORS_URLS=https://someorigin.com,http://someorigin.com:8000" planningpoker
```

You can verify that your additional origins were successfully added by looking at the logs in the container:
```shell
docker logs pp
INFO:pp.server:Attempting to parse and add CORS origins from 'https://someorigin.com,http://someorigin.com:8000'...
INFO:pp.server:Updated CORS origins: https://someorigin.com, http://someorigin.com:8000, http://127.0.0.1:5173, http://127.0.0.1
```
