# MySQL setup for vprofile (Ubuntu)

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
