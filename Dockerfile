FROM python:3.10
WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY ./pp /code/pp
COPY ./conf /code/conf
CMD ["uvicorn", "pp.server:api", "--proxy-headers", "--host", "0.0.0.0", "--port", "80"]
