FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY web/index.html web/strategy.html web/style.css /srv/
COPY web/status.html /srv-status/index.html
RUN mkdir -p /srv/data /srv-status/data
