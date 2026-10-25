# vprofile services setup

Setup order: MySQL → Memcached → RabbitMQ → Tomcat → Nginx.

# MySQL setup (db01, Ubuntu)

The application connects to MySQL using these settings from
`src/main/resources/application.properties`:

| Setting  | Value                            |
|----------|----------------------------------|
| Host     | `db01`                           |
| Port     | `3306`                           |
| Database | `accounts`                       |
| User     | `admin`                          |
| Password | `admin123`                       |

The steps below must produce exactly this database, user and password.

## 1. Install MySQL

```bash
sudo apt update
sudo apt install mysql-server -y
sudo systemctl start mysql
sudo systemctl enable mysql
sudo systemctl status mysql
```

## 2. Set the root password

On Ubuntu, the MySQL `root` user logs in with `auth_socket` (no password, only via `sudo`).
Switch it to password login first, otherwise `mysql_secure_installation` cannot set a password:

```bash
sudo mysql
```

```sql
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '123456789';
FLUSH PRIVILEGES;
EXIT;
```

## 3. Secure the installation

```bash
sudo mysql_secure_installation
```

Answers:

- Enter password for root: `123456789`
- VALIDATE PASSWORD component: `y`, policy level `0` (LOW). MEDIUM/STRONG will reject `admin123`
- Change the password for root: `n`
- Remove anonymous users: `y`
- Disallow root login remotely: `y`
- Remove test database: `y`
- Reload privilege tables now: `y`

From now on, log in with:

```bash
mysql -u root -p
```

## 4. Create the database and application user

```bash
mysql -u root -p
```

```sql
CREATE DATABASE accounts;

CREATE USER 'admin'@'localhost' IDENTIFIED BY 'admin123';
CREATE USER 'admin'@'%' IDENTIFIED BY 'admin123';

GRANT ALL PRIVILEGES ON accounts.* TO 'admin'@'localhost';
GRANT ALL PRIVILEGES ON accounts.* TO 'admin'@'%';

FLUSH PRIVILEGES;
EXIT;
```

> MySQL 8 no longer supports `GRANT ... IDENTIFIED BY`. Create the user first, then grant.

## 5. Import the initial data

```bash
cd /tmp/
git clone -b manual-vprofile-with-vagrant https://github.com/Ahmed363-Essam/vprofile-multi-vms.git
cd vprofile-multi-vms
mysql -u root -p accounts < src/main/resources/db_backup.sql
```

Verify:

```bash
mysql -u root -p accounts -e "SHOW TABLES;"
```

You should see the `role`, `user` and `user_role` tables.

## 6. Allow remote connections

The Tomcat server (`app01`) connects over the network, but by default MySQL only listens on `127.0.0.1`.
Edit the MySQL config:

```bash
sudo vim /etc/mysql/mysql.conf.d/mysqld.cnf
```

Change:

```ini
bind-address = 127.0.0.1
mysqlx-bind-address = 127.0.0.1
```

to:

```ini
bind-address = 0.0.0.0
mysqlx-bind-address = 0.0.0.0
```

Or do it in one command:

```bash
sudo sed -i 's/^bind-address.*/bind-address = 0.0.0.0/; s/^mysqlx-bind-address.*/mysqlx-bind-address = 0.0.0.0/' /etc/mysql/mysql.conf.d/mysqld.cnf
```

Restart MySQL:

```bash
sudo systemctl restart mysql
```

## 7. Open port 3306 in the firewall

```bash
sudo ufw allow 3306/tcp
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

> Allow OpenSSH before enabling ufw, or you will lose your `vagrant ssh` session.

## 8. Test the setup

On the DB server, confirm MySQL is listening on all interfaces:

```bash
sudo ss -tlnp | grep 3306
```

Expected: `0.0.0.0:3306`.

From another VM (for example `app01`), test the login as the application user:

```bash
mysql -h db01 -u admin -padmin123 accounts -e "SHOW TABLES;"
```

# Memcached setup (mc01, CentOS Stream 9)

The application connects to Memcached using these settings from
`src/main/resources/application.properties`:

| Setting | Value   |
|---------|---------|
| Host    | `mc01`  |
| Port    | `11211` |

Log in to the VM:

```bash
vagrant ssh mc01
```

Check that `/etc/hosts` has entries for the other VMs (`db01`, `app01`, ...):

```bash
cat /etc/hosts
```

## 1. Install Memcached

```bash
sudo dnf update -y
sudo dnf install epel-release -y
sudo dnf install memcached -y
sudo systemctl start memcached
sudo systemctl enable memcached
sudo systemctl status memcached
```

## 2. Configure Memcached

```bash
sudo vim /etc/sysconfig/memcached
```

Set:

```ini
PORT="11211"
USER="memcached"
MAXCONN="1024"
CACHESIZE="64"
OPTIONS="-l 0.0.0.0 -U 0"
```

- `-l 0.0.0.0`: listen on all interfaces. With the default `-l 127.0.0.1`, the Tomcat server (`app01`) cannot reach Memcached.
- `-U 0`: disable UDP. The app only uses TCP, and an open UDP port can be abused for amplification attacks.

Or do it in one command:

```bash
sudo sed -i 's/^OPTIONS=.*/OPTIONS="-l 0.0.0.0 -U 0"/' /etc/sysconfig/memcached
```

Restart Memcached:

```bash
sudo systemctl restart memcached
```

## 3. Open port 11211 in the firewall

```bash
sudo systemctl start firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --zone=public --add-port=11211/tcp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

## 4. Test the setup

On `mc01`, confirm Memcached is listening on all interfaces:

```bash
sudo ss -tlnp | grep 11211
```

Expected: `0.0.0.0:11211`.

From another VM (for example `app01`), check that the port is reachable:

```bash
sudo dnf install nmap-ncat -y
echo stats | nc mc01 11211
```

You should see a list of `STAT ...` lines.

# RabbitMQ setup (rmq01, CentOS Stream 9)

The application connects to RabbitMQ using these settings from
`src/main/resources/application.properties`:

| Setting  | Value   |
|----------|---------|
| Host     | `rmq01` |
| Port     | `5672`  |
| User     | `test`  |
| Password | `test`  |

Log in to the VM:

```bash
vagrant ssh rmq01
```

Check that `/etc/hosts` has entries for the other VMs (`db01`, `app01`, ...):

```bash
cat /etc/hosts
```

## 1. Install RabbitMQ

RabbitMQ is not in the default CentOS repos. Add the CentOS RabbitMQ repo, then install it:

```bash
sudo dnf update -y
sudo dnf install epel-release -y
sudo dnf install wget -y
sudo dnf install centos-release-rabbitmq-38 -y
sudo dnf --enablerepo=centos-rabbitmq-38 install rabbitmq-server -y
sudo systemctl enable --now rabbitmq-server
sudo systemctl status rabbitmq-server
```

## 2. Create the application user

Create the `test` user, make it an administrator, and give it full permissions on the default virtual host `/`:

```bash
sudo rabbitmqctl add_user test test
sudo rabbitmqctl set_user_tags test administrator
sudo rabbitmqctl set_permissions -p / test ".*" ".*" ".*"
```

> `set_permissions` takes three patterns: configure, write and read. With only one (`".*"`), the command fails.

Check the user:

```bash
sudo rabbitmqctl list_users
sudo rabbitmqctl list_permissions -p /
```

## 3. Open port 5672 in the firewall

```bash
sudo systemctl start firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --zone=public --add-port=5672/tcp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

## 4. Test the setup

On `rmq01`, confirm RabbitMQ is listening on port 5672:

```bash
sudo ss -tlnp | grep 5672
```

Expected: `*:5672` or `0.0.0.0:5672`. RabbitMQ listens on all interfaces by default.

From another VM (for example `app01`), check that the port is reachable:

```bash
sudo dnf install nmap-ncat -y
nc -zv rmq01 5672
```

Expected: `Connected to ...:5672`.

# Tomcat setup (app01, CentOS Stream 9)

Tomcat runs the vprofile application on port `8080`.

Log in to the VM:

```bash
vagrant ssh app01
```

Check that `/etc/hosts` has entries for the other VMs (`db01`, `mc01`, `rmq01`, ...):

```bash
cat /etc/hosts
```

## 1. Install Java and tools

```bash
sudo dnf update -y
sudo dnf install epel-release -y
sudo dnf install java-17-openjdk java-17-openjdk-devel -y
sudo dnf install git wget -y
```

## 2. Download Tomcat

```bash
cd /tmp/
wget https://archive.apache.org/dist/tomcat/tomcat-10/v10.1.26/bin/apache-tomcat-10.1.26.tar.gz
tar xzvf apache-tomcat-10.1.26.tar.gz
```

## 3. Create the tomcat user and copy the files

```bash
sudo useradd --home-dir /usr/local/tomcat --shell /sbin/nologin tomcat
sudo cp -r /tmp/apache-tomcat-10.1.26/* /usr/local/tomcat/
sudo chown -R tomcat:tomcat /usr/local/tomcat
```

> Use `tomcat:tomcat`, not `tomcat.tomcat`. The dot form is deprecated, and `chown` prints `warning: '.' should be ':'`.

## 4. Create the systemd service

```bash
sudo vim /etc/systemd/system/tomcat.service
```

Content:

```ini
[Unit]
Description=Tomcat
After=network.target

[Service]
User=tomcat
Group=tomcat
WorkingDirectory=/usr/local/tomcat
Environment=JAVA_HOME=/usr/lib/jvm/jre
Environment=CATALINA_HOME=/usr/local/tomcat
Environment=CATALINA_BASE=/usr/local/tomcat
ExecStart=/usr/local/tomcat/bin/catalina.sh run
ExecStop=/usr/local/tomcat/bin/shutdown.sh
RestartSec=10
Restart=always

[Install]
WantedBy=multi-user.target
```

> Do not add `Environment=CATALINA_PID=/var/tomcat/%i/run/tomcat.pid` (it is in the course PDF).
> `%i` only works in template units (`tomcat@.service`), `/var/tomcat` does not exist, and `catalina.sh run` never writes a PID file.
> With that line, `shutdown.sh` fails with `Stop aborted` on every stop and systemd has to kill Tomcat instead.

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start tomcat
sudo systemctl enable tomcat
sudo systemctl status tomcat
```

## 5. Open port 8080 in the firewall

firewalld is active on this box and only allows `ssh` by default. Without this step, the browser times out on `http://192.168.56.12:8080/` even though Tomcat is running.

```bash
sudo systemctl start firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --zone=public --add-port=8080/tcp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

## 6. Test the setup

On `app01`, confirm Tomcat is listening and responds:

```bash
sudo ss -tlnp | grep 8080
curl -I http://localhost:8080/
```

Expected: `0.0.0.0:8080` and `HTTP/1.1 200`.

From your computer, open `http://192.168.56.12:8080/`. You should see the Tomcat welcome page.

If the page times out, check the firewall first:

```bash
sudo firewall-cmd --list-all
```

`8080/tcp` must appear under `ports:`.