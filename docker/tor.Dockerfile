FROM alpine:3.18

RUN apk --update --no-cache --no-progress add tor

USER tor

CMD tor --SocksPort 0.0.0.0:${TOR_SOCKS_PORT} --ControlPort 0.0.0.0:${TOR_CONTROL_PORT} --HashedControlPassword $(tor --quiet --hash-password $TOR_CONTROL_PASSWD)

EXPOSE $TOR_SOCKS_PORT $TOR_CONTROL_PORT
