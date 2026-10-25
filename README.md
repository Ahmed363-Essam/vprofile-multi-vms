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
