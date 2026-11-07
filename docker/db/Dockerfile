FROM mysql:8.0.33

#ENV MYSQL_ROOT_PASSWORD="vprodbpass"
ENV MYSQL_DATABASE="accounts"

# copy db_backup.sql to docker-entrypoint-initdb.d folder
COPY --chown=mysql:mysql db_backup.sql /docker-entrypoint-initdb.d/db_backup.sql

# run the server as the built-in non-root mysql user
# (/var/lib/mysql and /var/run/mysqld are already owned by mysql in the base image)
USER mysql

# expose on 3306 port
EXPOSE 3306
