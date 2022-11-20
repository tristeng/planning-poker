# Planning Poker
This project is a minimalist poker planning web application backend. The companion frontend application can be found
[here](https://github.com/tristeng/planning-poker-ui).

The application has no authentication or authorization, allowing any user to create a planning poker room and invite
guests using a unique code.

## Docker
To build the Docker image, ensure to update the requirements.txt file first using poetry:
```shell
poetry export -f requirements.txt --output requirements.txt
```

and then build the image:
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