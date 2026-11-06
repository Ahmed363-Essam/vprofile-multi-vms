FROM mysql:8.0.33

ENV MYSQL_ROOT_PASSWORD="vprodbpass"
ENV MYSQL_DATABASE="accounts"


# copy db_backup.sql to docker-entrypoint-initdb.d folder

ADD db_backup.sql docker-entrypoint-initdb.d/db_backup.sql

# expose on 3306 port
EXPOSE 3306