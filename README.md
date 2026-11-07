# vprofile on Docker

This branch runs the vprofile Java web app as five containers with Docker Compose,
instead of the five VMs used in the `vagrant/` and `ansible/` setups.

```
Browser ──► vproweb (Nginx :80) ──► vproapp (Tomcat :8080) ──┬──► vprodb      (MySQL :3306)
                                                             ├──► vprocache01 (Memcached :11211)
                                                             └──► vpromq01    (RabbitMQ :5672)
```

## Services

| Service       | Image                         | Built from            | Port  | Role                       |
|---------------|-------------------------------|-----------------------|-------|----------------------------|
| `vprodb`      | `vprocontainers/vprofiledb`   | `docker/db/Dockerfile`  | 3306  | MySQL 8.0.33, `accounts` DB  |
| `vprocache01` | `memcached` (Docker Hub)      | –                     | 11211 | Cache for DB queries          |
| `vpromq01`    | `rabbitmq` (Docker Hub)       | –                     | 5672  | Message broker             |
| `vproapp`     | `vprocontainers/vprofileapp`  | `docker/app/Dockerfile` | 8080  | Tomcat 10 running the WAR  |
| `vproweb`     | `vprocontainers/vprofileweb`  | `docker/web/Dockerfile` | 80 → 8080 | Nginx reverse proxy    |

The app finds the other containers by **service name** (`vprodb`, `vprocache01`,
`vpromq01`), so don't rename these services in `docker-compose.yaml`.

## Non-root containers

Every container runs as a non-root user:

| Service       | User (UID)          | How |
|---------------|---------------------|-----|
| `vprodb`      | `mysql` (999)       | `USER mysql` in `docker/db/Dockerfile` |
| `vprocache01` | `memcache` (11211)  | `user: memcache` in `docker-compose.yaml` |
| `vpromq01`    | `rabbitmq` (999)    | `user: rabbitmq` in `docker-compose.yaml` |
| `vproapp`     | `tomcat` (1001)     | user created and `USER tomcat` in `docker/app/Dockerfile` |
| `vproweb`     | `nginx` (101)       | `nginxinc/nginx-unprivileged` base image, `USER nginx` |

A non-root user can't bind ports below 1024, so Nginx listens on **8080 inside the
container**. Compose maps host port 80 to it (`"80:8080"`), so you still browse to
`http://localhost`.

Check it yourself:

```bash
for c in vprodb vproapp vproweb; do docker exec $c id; done
docker compose exec vprocache01 id
docker compose exec vpromq01 id
```

> **Upgrading from the old root images:** the app no longer uses a volume for
> `webapps`. The WAR is built into the image and owned by `tomcat`. Recreate the
> app container and delete the old root-owned volume once:
>
> ```bash
> docker compose up -d --build --force-recreate vproapp
> docker volume rm vprofile-multi-vms_vproappdata
> ```

## Prerequisites

- Docker Engine 20.10+ with the Compose plugin (`docker compose version`)
- About 3 GB free disk space for images and the Maven build
- Free host ports: `80`, `8080`, `3306`, `5672`, `11211`

## Quick start

```bash
git clone -b docker https://github.com/Ahmed363-Essam/vprofile-multi-vms.git
cd vprofile-multi-vms

docker compose build      # build db, app and web images
docker compose up -d      # start all containers in the background
docker compose ps         # all five should be "running"
```

Open **http://localhost** (through Nginx) or **http://localhost:8080** (Tomcat directly).

Login: `admin_vp` / `admin_vp` (seeded by `docker/db/db_backup.sql`).

> The first start can take a minute. MySQL runs `db_backup.sql` on its first boot,
> and the app may try to connect before MySQL is ready. If the login page shows a DB
> error, wait a moment and run `docker compose restart vproapp`.

## Images in detail

### Database: `docker/db/Dockerfile`

```dockerfile
FROM mysql:8.0.33
ENV MYSQL_ROOT_PASSWORD="vprodbpass"
ENV MYSQL_DATABASE="accounts"
COPY --chown=mysql:mysql db_backup.sql /docker-entrypoint-initdb.d/db_backup.sql
USER mysql
EXPOSE 3306
```

- Creates the `accounts` database and loads `db_backup.sql` (tables `user`, `role`,
  `user_role` plus sample users).
- Scripts in `docker-entrypoint-initdb.d` run **only when the data volume is empty**.
  To re-seed the database, remove the volume (see [Reset everything](#reset-everything)).
- Data is kept in the named volume `vprodbdata`.

| Setting  | Value        |
|----------|--------------|
| Host     | `vprodb`     |
| Database | `accounts`   |
| User     | `root`       |
| Password | `vprodbpass` |

### Application: `docker/app/Dockerfile`

This is a multi-stage build:

1. **Build stage** (`maven:3.9.9-eclipse-temurin-21-jammy`): clones
   `https://github.com/hkhcoder/vprofile-project.git`, checks out its `docker`
   branch, and runs `mvn install` to produce `vprofile-v2.war`.
2. **Run stage** (`tomcat:10-jdk21`): creates a `tomcat` user (UID 1001), copies the
   WAR to `/usr/local/tomcat/webapps/ROOT.war` so the app is served at `/`, gives
   `tomcat` ownership of `/usr/local/tomcat`, and switches to it with `USER tomcat`.

> **Note:** the image builds the source from the upstream GitHub repo, **not**
> from the local `src/` folder. Local code changes won't show up in the container
> unless you change the Dockerfile to build from this repo (see below).

The app reads its connection settings from `src/main/resources/application.properties`
in the WAR. For the containers to talk to each other, the hostnames there must match
the compose service names:

```properties
jdbc.url=jdbc:mysql://vprodb:3306/accounts?useUnicode=true&characterEncoding=UTF-8&zeroDateTimeBehavior=convertToNull
jdbc.username=root
jdbc.password=vprodbpass

memcached.active.host=vprocache01
memcached.active.port=11211
memcached.standBy.host=vprocache01
memcached.standBy.port=11211

rabbitmq.address=vpromq01
rabbitmq.port=5672
rabbitmq.username=guest
rabbitmq.password=guest
```

The local `application.properties` in this repo still uses the VM hostnames
(`db01`, `mc01`, `rmq01`). Update it as shown above if you switch to building from
local source.

#### Building from local source (optional)

Run the build with the repo root as the build context:

```dockerfile
FROM maven:3.9.9-eclipse-temurin-21-jammy AS BUILD_IMAGE
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn install -DskipTests

FROM tomcat:10-jdk21
RUN groupadd --system --gid 1001 tomcat && \
    useradd --system --uid 1001 --gid tomcat --no-create-home --shell /usr/sbin/nologin tomcat
RUN rm -rf /usr/local/tomcat/webapps/*
COPY --from=BUILD_IMAGE --chown=tomcat:tomcat /app/target/vprofile-v2.war /usr/local/tomcat/webapps/ROOT.war
RUN chown -R tomcat:tomcat /usr/local/tomcat
USER tomcat
EXPOSE 8080
CMD ["catalina.sh", "run"]
```

```yaml
  vproapp:
    build:
      context: .
      dockerfile: docker/app/Dockerfile
```

### Web: `docker/web/Dockerfile`

```dockerfile
FROM nginxinc/nginx-unprivileged:1.27
RUN rm /etc/nginx/conf.d/default.conf
COPY default.conf /etc/nginx/conf.d/default.conf
USER nginx
EXPOSE 8080
```

`default.conf` forwards all traffic on port 8080 to the app container:

```nginx
upstream vproapp {
  server vproapp:8080;
}
server {
  listen 8080;
  location / {
    proxy_pass http://vproapp;
  }
}
```

## Common commands

```bash
docker compose up -d --build        # rebuild images and start
docker compose ps                   # container status
docker compose logs -f vproapp      # follow Tomcat logs
docker compose logs vprodb          # MySQL init logs
docker compose restart vproapp      # restart a single service
docker compose stop                 # stop without removing
docker compose down                 # stop and remove containers (volumes are kept)
```

Check each service:

```bash
# MySQL: list tables in accounts
docker compose exec vprodb mysql -uroot -pvprodbpass accounts -e "SHOW TABLES;"

# Memcached: should print "STAT ..." lines
docker compose exec vproapp bash -c "exec 3<>/dev/tcp/vprocache01/11211; echo stats >&3; head -5 <&3"

# RabbitMQ
docker compose exec vpromq01 rabbitmq-diagnostics status

# App through Nginx
curl -I http://localhost
```

## Reset everything

```bash
docker compose down -v      # -v also deletes the vprodbdata volume (DB is re-seeded on next start)
docker compose up -d --build
```

## Pushing images to Docker Hub (optional)

```bash
docker login
docker compose build
docker push vprocontainers/vprofiledb
docker push vprocontainers/vprofileapp
docker push vprocontainers/vprofileweb
```

Replace `vprocontainers` in `docker-compose.yaml` with your own Docker Hub username
if you don't have push access to that namespace.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Permission denied` in app or DB logs after upgrading | Old volumes are owned by root. Run `docker compose down -v` and start again. |
| `port is already allocated` | Another service is using 80/8080/3306. Stop it, or change the host side of the port mapping, e.g. `"8081:8080"`. |
| Login page shows a DB / JDBC error | MySQL was still starting up. Run `docker compose restart vproapp`. |
| Tables missing in `accounts` | The volume was created before the SQL file was added. Run `docker compose down -v` and start again. |
| `502 Bad Gateway` from Nginx | Tomcat is still deploying the WAR. Check `docker compose logs -f vproapp`. |
| Code changes not visible | The app image builds the upstream repo. See [Building from local source](#building-from-local-source-optional). |

## Other setups in this repo

- `vagrant/`: multi-VM setup with Vagrant
- `ansible/`: provisioning with Ansible
- `VprofileProjectSetupWindowsAndMacIntel.pdf`: manual VM setup guide
