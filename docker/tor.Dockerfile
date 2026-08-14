FROM alpine:3.18@sha256:de0eb0b3f2a47ba1eb89389859a9bd88b28e82f5826b6969ad604979713c2d4f

RUN apk --update --no-cache --no-progress add tor

USER tor

CMD tor --SocksPort 0.0.0.0:${TOR_SOCKS_PORT} --ControlPort 0.0.0.0:${TOR_CONTROL_PORT} --HashedControlPassword $(tor --quiet --hash-password $TOR_CONTROL_PASSWD)

EXPOSE $TOR_SOCKS_PORT $TOR_CONTROL_PORT
