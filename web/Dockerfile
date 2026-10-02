FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY web/index.html web/strategy.html web/about.html web/contact.html web/guestbook.html web/qr.svg web/style.css web/countdown.js web/theme.js web/cards.js web/links.js web/account.js /srv/
COPY web/status.html /srv-status/index.html
RUN mkdir -p /srv/data /srv-status/data
# Cache-bust CSS/JS: Cloudflare gives static assets a 4 h browser cache, so link them with a
# content fingerprint that changes whenever they do (the HTML itself is never cached).
RUN v=$(cat /srv/style.css /srv/countdown.js /srv/theme.js /srv/cards.js /srv/links.js /srv/account.js | md5sum | cut -c1-8) \
 && sed -i "s#href=\"style.css\"#href=\"style.css?v=$v\"#; s#src=\"countdown.js\"#src=\"countdown.js?v=$v\"#; s#src=\"theme.js\"#src=\"theme.js?v=$v\"#; s#src=\"cards.js\"#src=\"cards.js?v=$v\"#; s#src=\"links.js\"#src=\"links.js?v=$v\"#; s#src=\"account.js\"#src=\"account.js?v=$v\"#" /srv/*.html
