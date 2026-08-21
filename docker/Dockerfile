FROM python:3.12-alpine@sha256:78098ea6a3a9c6a7727a5d4674e4a44e57e01fac878ee9cb4d24a86bd93916ff

RUN apk --update --no-cache --no-progress add git gcc libffi-dev musl-dev make openssl g++ autoconf automake libtool

RUN adduser -u 1600 -D service-0net

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
