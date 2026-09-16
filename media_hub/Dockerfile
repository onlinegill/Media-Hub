FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="1.1.2"
ARG BUILD_ARCH="amd64"

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.name="Media Hub"

RUN apk add --no-cache python3 py3-aiohttp

WORKDIR /app
COPY app.py playlists.py /app/
COPY web /app/web
COPY logo.png /app/logo.png
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
