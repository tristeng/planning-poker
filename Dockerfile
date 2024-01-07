FROM python:3.11
RUN pip install poetry==1.7.1
WORKDIR /code
COPY ./pp /code/pp
COPY ./conf /code/conf
COPY ./pyproject.toml /code/pyproject.toml
COPY ./poetry.lock /code/poetry.lock
RUN poetry config virtualenvs.create false && poetry install --no-dev
CMD ["uvicorn", "pp.server:api", "--proxy-headers", "--host", "0.0.0.0", "--port", "80"]
