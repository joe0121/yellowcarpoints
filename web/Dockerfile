FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY web/index.html web/strategy.html web/style.css /srv/
RUN mkdir -p /srv/data
