FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

RUN apt-get update
RUN apt-get -y install git openssl pkg-config libffi-dev python3-pip python3-dev build-essential libtool

RUN useradd -u 1600 -m service-0net

USER service-0net:service-0net

WORKDIR /home/service-0net

COPY requirements.lock .

RUN python3 -m pip install --require-hashes --no-cache-dir -r requirements.lock

# the part below is updated with source updates

COPY . .

ENTRYPOINT python3 zeronet.py --ui-ip "*" --fileserver-port 26552 \
    --tor $TOR_ENABLED --tor-controller tor:$TOR_CONTROL_PORT \
    --tor-proxy tor:$TOR_SOCKS_PORT --tor-password $TOR_CONTROL_PASSWD

CMD main

EXPOSE 43110 26552
