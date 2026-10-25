FROM python:3.12-slim
LABEL authors="Philippe Westenfelder"

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONWARNINGS="ignore:Unverified HTTPS request"
ENV CONFIG_PATH=/usr/src/app/data/config.yaml

# Config file (config.yaml) is stored here
VOLUME /usr/src/app/data
# Web interface
EXPOSE 4883

CMD [ "python", "-u", "./core/main.py" ]
