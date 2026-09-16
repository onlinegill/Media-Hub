#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "Starting Media Hub"
bashio::log.info "Dashboard is available through Home Assistant Ingress."
bashio::log.info "LAN media endpoint is listening on port 8100 for network speakers."

exec python3 /app/app.py
