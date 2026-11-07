# official NGINX image that runs as the non-root "nginx" user (uid 101)
# and listens on 8080, because non-root users can't bind ports below 1024
FROM nginxinc/nginx-unprivileged:1.27

RUN rm /etc/nginx/conf.d/default.conf
COPY default.conf /etc/nginx/conf.d/default.conf

USER nginx
