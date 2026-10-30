# vprofile services setup

Setup order: MySQL → Memcached → RabbitMQ → Tomcat → Nginx.

Monitoring: Nagios (`nagios01`).

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

# Stop EPEL from providing Erlang (see the note below)
sudo sed -i '/^\[epel\]$/a excludepkgs=erlang*' /etc/yum.repos.d/epel.repo
sudo sed -i '/^\[epel-next\]$/a excludepkgs=erlang*' /etc/yum.repos.d/epel-next.repo

sudo dnf --enablerepo=centos-rabbitmq-38 install rabbitmq-server -y
sudo systemctl enable --now rabbitmq-server
sudo systemctl status rabbitmq-server
```

Check that RabbitMQ runs on Erlang 24, not 26:

```bash
sudo rabbitmq-diagnostics erlang_version
```

Expected: `Erlang/OTP 24.x`.

> EPEL ships Erlang 26, which is newer than the Erlang 24 in the CentOS RabbitMQ repo, so `dnf` picks EPEL's version.
> RabbitMQ 3.9 does not support Erlang 26: it starts fine, but crashes every client connection
> (`{unexpected_message,{'EXIT',#Port<...>,einval}}` in `/var/log/rabbitmq/rabbit@rmq01.log`),
> and the app logs `Failed to check/redeclare auto-delete queue(s)` every few seconds.
>
> If Erlang 26 is already installed, add the two `excludepkgs` lines above, then:
>
> ```bash
> sudo systemctl stop rabbitmq-server
> sudo dnf distro-sync "erlang*" -y
> sudo systemctl start rabbitmq-server
> ```

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


############################# install maven 
cd /tmp/
wget https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.zip 
unzip apache-maven-3.9.9-bin.zip
cp -r apache-maven-3.9.9 /usr/local/maven3.9
export MAVEN_OPTS="-Xmx512m"

download
git clone -b local https://github.com/hkhcoder/vprofile-project.git
cd vprofile-project

buid code 
/usr/local/maven3.9/bin/mvn install 
systemctl stop tomcat

build path :- /tmp/vprofile-project/target/vprofile-v2.war 

rm -rf /usr/local/tomcat/webapps/ROOT* # cp target/vprofile-v2.war /usr/local/tomcat/webapps/ROOT.war # systemctl start tomcat # chown tomcat.tomcat /usr/local/tomcat/webapps -R # systemctl restart tomcat

# Nagios setup (nagios01, Ubuntu 22.04)

Nagios Core monitors the other VMs. It is built from source and serves its web interface through Apache on port `80`.

| Setting        | Value                          |
|----------------|--------------------------------|
| VM             | `nagios01` (`192.168.56.16`)   |
| Nagios Core    | `4.5.14`                       |
| Nagios Plugins | `2.5`                          |
| Web URL        | `http://192.168.56.16/nagios`  |
| Web user       | `nagiosadmin`                  |

Log in to the VM:

```bash
vagrant ssh nagios01
```

> This VM runs Ubuntu, not CentOS. Use `apt-get`, not `dnf`.
> The course command `sudo dnf install epel-release -y` fails with `sudo: dnf: command not found`.
> EPEL is a CentOS repo and is not needed on Ubuntu.

## 1. Install the build tools and Apache

```bash
sudo apt-get update
sudo apt-get install -y autoconf gcc libc6 make wget unzip \
  apache2 php libapache2-mod-php libgd-dev openssl libssl-dev
```

Check that the compiler is installed:

```bash
gcc --version
```

> If the terminal splits a long `apt-get install` line when you paste it, only the last part runs (here, only `openssl libssl-dev` got installed).
> Step 2 then fails with `configure: error: no acceptable C compiler found in $PATH`.
> Run the install again and check `gcc --version` before you continue.

## 2. Download and compile Nagios Core

```bash
cd /tmp
wget -O nagioscore.tar.gz https://github.com/NagiosEnterprises/nagioscore/archive/nagios-4.5.14.tar.gz
tar xzf nagioscore.tar.gz
cd /tmp/nagioscore-nagios-4.5.14/
sudo ./configure --with-httpd-conf=/etc/apache2/sites-enabled
sudo make all
```

`configure` should end with `*** Configuration summary for nagios 4.5.14 ***`.

## 3. Create the nagios user and group

`make install-groups-users` creates the `nagios` user and group. Add Apache's user to the group so the web interface can send commands to Nagios:

```bash
sudo make install-groups-users
sudo usermod -a -G nagios www-data
id www-data
```

Expected: `nagios` appears in the `groups=` list.

> On Ubuntu, the Apache user is `www-data`. CentOS guides use `apache`, which does not exist here.
>
> Older guides also create a `nagcmd` group (`groupadd nagcmd`, `usermod -a -G nagcmd ...`). Nagios 4 does not need it:
> `make install-commandmode` gives the `nagios` group access to the command file. An existing `nagcmd` group does no harm.

## 4. Install Nagios and the web interface

```bash
sudo make install
sudo make install-daemoninit
sudo make install-commandmode
sudo make install-config
sudo make install-webconf
sudo a2enmod rewrite cgi
```

> The Nagios web interface runs as CGI scripts, and Apache on Ubuntu ships with CGI disabled. Do not skip `a2enmod cgi`.

## 5. Create the web login user

```bash
sudo htpasswd -c /usr/local/nagios/etc/htpasswd.users nagiosadmin
```

Enter a password when asked. You log in to the web interface with it.

> `-c` creates the file. Use it only the first time: running it again overwrites the file and deletes the existing users.
> To add more users later, leave out `-c`.

## 6. Install Nagios Plugins

The plugins are the `check_*` programs (ping, disk, HTTP, ...) that Nagios runs.

```bash
sudo apt-get install -y gcc libc6 make libssl-dev wget bc gawk dc build-essential \
  snmp libnet-snmp-perl gettext automake autopoint
cd /tmp
wget -O nagios-plugins.tar.gz https://github.com/nagios-plugins/nagios-plugins/archive/release-2.5.tar.gz
tar zxf nagios-plugins.tar.gz
cd /tmp/nagios-plugins-release-2.5/
sudo ./tools/setup
sudo ./configure
sudo make
sudo make install
```

Check that the plugins are installed:

```bash
ls /usr/local/nagios/libexec
```

Expected: a list of `check_*` files.

> Without the plugins, Nagios starts and the web interface works, but every check fails with
> `execvp(/usr/local/nagios/libexec/check_ping, ...) failed. errno is 2: No such file or directory`.
>
> Do not create plugin files by hand (for example with `touch check_ping`). An empty file is not executable, so the host shows
> `DOWN` with `Return code of 13 for host 'localhost' was out of bounds` (13 means "permission denied").
> Delete the file (`sudo rm -f /usr/local/nagios/libexec/check_ping`) and run the steps above.

## 7. Start the services

```bash
sudo systemctl restart apache2
sudo systemctl enable --now nagios
sudo systemctl status nagios
```

If `systemctl start nagios` fails and `systemctl status nagios` only shows
`One or more problems was encountered while processing the config files...`, run the config check. Its output names the file and line of every error:

```bash
sudo /usr/local/nagios/bin/nagios -v /usr/local/nagios/etc/nagios.cfg
```

Expected: `Total Warnings: 0` and `Total Errors: 0`.

## 8. Test the setup

On `nagios01`, confirm Apache serves Nagios:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/nagios/
```

Expected: `401`. Apache asks for the Nagios login, so the web interface is installed.

From your computer, open `http://192.168.56.16/nagios` (or `http://nagios01/nagios`) and log in as `nagiosadmin`.
Under **Services**, the `localhost` checks should turn green (`OK`) within a few minutes.

> The `ubuntu/jammy64` box has no swap, so the `localhost` **Swap Usage** check shows `CRITICAL` with
> `SWAP CRITICAL - 0% free (0 MB out of 0 MB) - Swap is either disabled, not present, or of zero size`.
> Add a 1 GB swap file (it also helps this 1 GB RAM VM):
>
> ```bash
> sudo fallocate -l 1G /swapfile
> sudo chmod 600 /swapfile
> sudo mkswap /swapfile
> sudo swapon /swapfile
> echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
> free -m
> ```
>
> Expected: `Swap:` shows about `1023` total. The check turns `OK` at its next run.

> ufw is inactive on this box, so port `80` is open. If you enable ufw later, run `sudo ufw allow OpenSSH` and `sudo ufw allow Apache` first,
> or you will lose your `vagrant ssh` session and the web interface.

## 9. Monitor rmq01

The `config.vm.define "rmq01"` block in the Vagrantfile only creates the VM. Nagios needs its own host definition for it.

Enable the `servers` config folder:

```bash
sudo sed -i 's|^#cfg_dir=/usr/local/nagios/etc/servers|cfg_dir=/usr/local/nagios/etc/servers|' /usr/local/nagios/etc/nagios.cfg
sudo mkdir -p /usr/local/nagios/etc/servers
```

Create the host file:

```bash
sudo vim /usr/local/nagios/etc/servers/rmq01.cfg
```

Content:

```
define host {
    use                     linux-server
    host_name               rmq01
    alias                   RabbitMQ server
    address                 192.168.56.13
}

define service {
    use                     generic-service
    host_name               rmq01
    service_description     PING
    check_command           check_ping!100.0,20%!500.0,60%
}

define service {
    use                     generic-service
    host_name               rmq01
    service_description     SSH
    check_command           check_ssh
}

define service {
    use                     generic-service
    host_name               rmq01
    service_description     RabbitMQ port 5672
    check_command           check_tcp!5672
}
```

Check the config, then restart Nagios:

```bash
sudo /usr/local/nagios/bin/nagios -v /usr/local/nagios/etc/nagios.cfg
sudo systemctl restart nagios
```

Expected: `Checked 2 hosts`, `Total Errors: 0`. Within a few minutes, `rmq01` shows `UP` and its three services show `OK`.

> Nagios only reads files listed in `nagios.cfg` with `cfg_file=`, or files inside a folder listed with `cfg_dir=`.
> A host file saved anywhere else (for example `/usr/local/nagios/etc/objects/hosts.cfg`) is ignored without any error:
> `nagios -v` still says `Checked 1 hosts` and the host never appears in the web interface.
> Either move the file into `servers/`, or register it:
>
> ```bash
> echo "cfg_file=/usr/local/nagios/etc/objects/hosts.cfg" | sudo tee -a /usr/local/nagios/etc/nagios.cfg
> ```
>
> Do one or the other, not both. If the same host is defined in two files that Nagios reads (for example `servers/rmq01.cfg`
> and a registered `objects/hosts.cfg`), Nagios refuses to start and `nagios -v` shows:
>
> ```
> Warning: Duplicate definition found for host 'rmq01' (config file '/usr/local/nagios/etc/objects/hosts.cfg', starting on line 1)
> Error: Could not add object property in file '/usr/local/nagios/etc/objects/hosts.cfg' on line 3.
> Error: Invalid max_check_attempts value for host 'localhost'
> ```
>
> The `localhost` error is a side effect of the duplicate; `localhost.cfg` is fine. Find every file that mentions the host:
>
> ```bash
> sudo grep -rln "host_name *rmq01" /usr/local/nagios/etc/
> ```
>
> Keep one file, then delete the other (or remove its `cfg_file=` line from `nagios.cfg`), run `nagios -v` and restart Nagios.

> The checks run from `nagios01`, so the firewall on `rmq01` must allow them. firewalld allows ping and SSH by default, and port `5672` was opened in the RabbitMQ setup.
>
> To test a check by hand before adding it:
>
> ```bash
> /usr/local/nagios/libexec/check_tcp -H 192.168.56.13 -p 5672
> ```
>
> Expected: `TCP OK`.

Other VMs follow the same pattern with their own file and port: `db01` (`3306`), `mc01` (`11211`), `app01` (`8080`), `web01` (`80`).

# Zabbix setup (zabbix01, Ubuntu 22.04)

Zabbix 7.0 LTS (supported until 2029). The server and web interface run on `zabbix01`;
each monitored VM runs a Zabbix agent that the server polls on port `10050`.

| Item | Value |
|------|-------|
| Server VM | `zabbix01` (`192.168.56.17`) |
| Web interface | http://192.168.56.17/zabbix |
| Web login | `Admin` / `zabbix` (capital A; change it after the first login) |
| Database | MySQL on `zabbix01`, database `zabbix`, user `zabbix` / `zabbix123` |

## Part A: Install the Zabbix server

```bash
vagrant ssh zabbix01
```

### 1. Add the Zabbix 7.0 repository

```bash
cd /tmp
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest_7.0+ubuntu22.04_all.deb
sudo dpkg -i zabbix-release_latest_7.0+ubuntu22.04_all.deb
sudo apt update
```

> Do not skip `sudo apt update`. Without it apt does not know the new repository and step 2 fails with
> `E: Unable to locate package zabbix-apache-conf` (and `zabbix-sql-scripts`, `zabbix-get`).
> Check that apt sees Zabbix 7.0, not Ubuntu's old 5.0:
>
> ```bash
> apt-cache policy zabbix-server-mysql
> ```
>
> `Candidate:` must be `1:7.0.x` from `repo.zabbix.com`.

### 2. Install MySQL, the Zabbix server, web interface and agent

```bash
sudo apt install -y mysql-server
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent zabbix-get
sudo systemctl enable --now mysql
```

`zabbix-get` is a test tool: it asks an agent for a value from the command line (used in Part B).

### 3. Create the database and user

```bash
sudo mysql
```

```sql
CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'zabbix'@'localhost' IDENTIFIED BY 'zabbix123';
GRANT ALL PRIVILEGES ON zabbix.* TO 'zabbix'@'localhost';
SET GLOBAL log_bin_trust_function_creators = 1;
EXIT;
```

### 4. Load the Zabbix tables

This takes 1–2 minutes and prints nothing while it runs.

```bash
zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz | mysql --default-character-set=utf8mb4 -uzabbix -pzabbix123 zabbix
sudo mysql -e "SET GLOBAL log_bin_trust_function_creators = 0;"
sudo mysql zabbix -e "SHOW TABLES;" | wc -l
```

Expected: about 200 tables.

### 5. Give the server the database password

```bash
echo "DBPassword=zabbix123" | sudo tee -a /etc/zabbix/zabbix_server.conf
grep -E "^DB(Name|User|Password)=" /etc/zabbix/zabbix_server.conf
```

### 6. Start the services

```bash
sudo systemctl restart zabbix-server zabbix-agent apache2
sudo systemctl enable zabbix-server zabbix-agent apache2
sudo systemctl status zabbix-server --no-pager
```

`ufw` is inactive on `zabbix01`, so no firewall change is needed here.

### 7. Finish the setup in the browser

Open http://192.168.56.17/zabbix and complete the wizard:

| Screen | Value |
|--------|-------|
| Check of pre-requisites | Every row OK |
| Database type | MySQL |
| Database host / port | `localhost` / `0` (default) |
| Database name / user / password | `zabbix` / `zabbix` / `zabbix123` |
| Zabbix server name | `zabbix01` |
| Default time zone | Your time zone |

Log in as `Admin` / `zabbix`, then change the password in **User settings → Profile**.

### 8. Test the server

```bash
sudo ss -tlnp | grep -E ":80 |:10051 |:10050 "
sudo tail -20 /var/log/zabbix/zabbix_server.log
```

Expected: ports `80` (Apache), `10051` (Zabbix server), `10050` (agent), and no `cannot connect to database` in the log.

## Part B: Monitor app01 with the Zabbix agent

The same steps work for `db01`, `mc01` and `rmq01` (see the table at the end of this part).

### 1. Stop EPEL from providing Zabbix

EPEL has its own, older Zabbix packages. Without this, `dnf` may install EPEL's agent instead of 7.0
(the same kind of conflict as Erlang on `rmq01`).

```bash
vagrant ssh app01
sudo sed -i '/^\[epel\]$/a excludepkgs=zabbix*' /etc/yum.repos.d/epel.repo
grep -A1 '^\[epel\]$' /etc/yum.repos.d/epel.repo
```

> On `rmq01`, which already has `excludepkgs=erlang*`, extend that line instead of adding a second one:
>
> ```bash
> sudo sed -i 's/^excludepkgs=erlang\*$/excludepkgs=erlang*,zabbix*/' /etc/yum.repos.d/epel.repo
> ```

### 2. Install the agent

```bash
sudo rpm -Uvh https://repo.zabbix.com/zabbix/7.0/centos/9/x86_64/zabbix-release-latest-7.0.el9.noarch.rpm
sudo dnf clean all
sudo dnf install -y zabbix-agent
dnf info --installed zabbix-agent | grep -E "^(Version|From repo)"
```

Expected: `Version : 7.0.x` and `From repo : zabbix` (not `epel`).

### 3. Point the agent at zabbix01

```bash
sudo sed -i "s/^Server=127.0.0.1/Server=192.168.56.17/; s/^ServerActive=127.0.0.1/ServerActive=192.168.56.17/; s/^Hostname=Zabbix server/Hostname=$(hostname -s)/" /etc/zabbix/zabbix_agentd.conf
sudo grep -E "^(Server|ServerActive|Hostname)=" /etc/zabbix/zabbix_agentd.conf
```

Expected on `app01`:

```
Server=192.168.56.17
ServerActive=192.168.56.17
Hostname=app01
```

| Setting | Meaning |
|---------|---------|
| `Server` | Which IP may ask this agent for data. Requests from any other IP are rejected. |
| `ServerActive` | Where the agent sends data it collects on its own. |
| `Hostname` | Must match the host name in the web interface exactly (case-sensitive). |

### 4. Start the agent

```bash
sudo systemctl enable --now zabbix-agent
sudo systemctl status zabbix-agent --no-pager
sudo ss -tlnp | grep 10050
```

Expected: `active (running)` and `0.0.0.0:10050`.

> Do not skip this step. With the agent stopped, the test in step 6 fails with
> `cannot connect to [[192.168.56.12]:10050]: connection error (POLLERR,POLLHUP)`, even if the firewall is open.
> After any later change to `zabbix_agentd.conf`, run `sudo systemctl restart zabbix-agent`.

### 5. Open port 10050 in the firewall

```bash
sudo firewall-cmd --zone=public --add-port=10050/tcp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

### 6. Test the agent from zabbix01

```bash
vagrant ssh zabbix01
zabbix_get -s 192.168.56.12 -k agent.ping
zabbix_get -s 192.168.56.12 -k agent.hostname
zabbix_get -s 192.168.56.12 -k system.uname
```

Expected: `1`, `app01`, and a `Linux app01 ...` line. Do not continue until this works.

### 7. Add app01 in the web interface

1. **Data collection → Hosts → Create host** (top right).
2. **Host name:** `app01` (same as `Hostname=` in step 3).
3. **Templates:** **Select** → template group **Templates/Operating systems** → tick **Linux by Zabbix agent** → **Select**.
4. **Host groups:** `Linux servers`.
5. **Interfaces:** **Add → Agent**, IP `192.168.56.12`, **Connect to** IP, port `10050`.
6. Click **Add**.

Within about a minute the **ZBX** icon in the **Availability** column turns green, and
**Monitoring → Latest data** (filter host `app01`) shows CPU, memory, disk and network values.

> Until the host exists in the web interface, the agent log shows `host [app01] not found`. That is expected.

### Other VMs

Repeat steps 1–7 with these values:

| VM | Step 1 | IP (steps 6 and 7) | Host name |
|----|--------|--------------------|-----------|
| db01 | add new line | 192.168.56.15 | `db01` |
| mc01 | add new line | 192.168.56.14 | `mc01` |
| rmq01 | extend existing line | 192.168.56.13 | `rmq01` |

Check all agents at once from `zabbix01`:

```bash
for ip in 192.168.56.12 192.168.56.15 192.168.56.14 192.168.56.13; do
  printf "%-15s " "$ip"; zabbix_get -s "$ip" -k agent.hostname
done
```

## Part C: Monitor Tomcat and the vprofile app on app01

The Linux template watches the VM (CPU, memory, disk), not Tomcat. These two checks watch the application itself.

### 1. Tomcat process check (agent item)

Test it first from `zabbix01`:

```bash
zabbix_get -s 192.168.56.12 -k "proc.num[java,tomcat]"
```

Expected: `1` (one Java process owned by the `tomcat` user).

In the web interface: **Data collection → Hosts → app01 → Items → Create item**:

| Field | Value |
|-------|-------|
| Name | `Tomcat: Java processes` |
| Type | Zabbix agent |
| Key | `proc.num[java,tomcat]` |
| Type of information | Numeric (unsigned) |
| Update interval | `1m` |

Click **Test → Get value and test** (should return `1`), then **Add**.

Then **app01 → Triggers → Create trigger**:

| Field | Value |
|-------|-------|
| Name | `Tomcat is not running on app01` |
| Severity | High |
| Expression | `last(/app01/proc.num[java,tomcat])=0` |

### 2. vprofile login page check (web scenario)

The Zabbix server opens the login page like a browser would and checks the answer.

**Data collection → Hosts → app01 → Web → Create web scenario**:

- **Scenario** tab: **Name** `vprofile login page`, **Update interval** `1m`.
- **Steps** tab → **Add**:

  | Field | Value |
  |-------|-------|
  | Name | `Login page` |
  | URL | `http://192.168.56.12:8080/` |
  | Required string | `Login` |
  | Required status codes | `200` |

Click **Add** (step), then **Add** (scenario).

Then **app01 → Triggers → Create trigger**:

| Field | Value |
|-------|-------|
| Name | `vprofile login page is down` |
| Severity | High |
| Expression | `last(/app01/web.test.fail[vprofile login page])<>0` |

Check the result in **Monitoring → Web**: the scenario should show status **OK** and a response time.

> Why not an agent check on port 8080 (`net.tcp.service[http,127.0.0.1,8080]`)? On CentOS, SELinux blocks the
> agent from connecting to other ports. The check returns `0` even with Tomcat up, and `/var/log/audit/audit.log` shows
> `denied { name_connect } ... comm="zabbix_agentd" dest=8080`. The `zabbix_can_network` boolean does not cover
> the agent. The web scenario runs on `zabbix01` (Ubuntu, no SELinux) and tests what users actually see.

## Part D: vprofile dashboard

**Dashboards → All dashboards → Create dashboard**, **Name** `vprofile app01`, **Apply**.
Then click **Add widget** for each row below, and finish with **Save changes**.

| Widget type | Settings | Shows |
|-------------|----------|-------|
| Problems | **Hosts:** `app01` | Open alerts for app01 |
| Item value | **Item:** `app01: Tomcat: Java processes` | `1` while Tomcat runs |
| Item value | **Item:** `app01: Response time for step "Login page" of scenario "vprofile login page".` | Login page response time |
| Web monitoring | **Host groups:** `Linux servers` | Web scenario status (OK / Failed) |
| Graph (classic) | **Source:** Graph, **Graph:** `app01: Linux: CPU utilization` | CPU graph |
| Graph (classic) | **Source:** Graph, **Graph:** `app01: Linux: Memory utilization` | Memory graph |

## Check that everything works

| Level | Where | Command / place | Expected |
|-------|-------|-----------------|----------|
| 1 | app01 | `sudo systemctl status zabbix-agent` | `active (running)` |
| 2 | zabbix01 | `zabbix_get -s 192.168.56.12 -k agent.ping` | `1` |
| 3 | Web | **Data collection → Hosts** | ZBX icon green |
| 4 | Web | **Monitoring → Latest data**, host `app01` | Values with a recent **Last check** |
| 5 | Web | **Monitoring → Web** | `vprofile login page`: OK |

Then prove the alerts work by breaking things on purpose:

```bash
# on app01
sudo systemctl stop tomcat
```

Within 1–2 minutes **Monitoring → Problems** and the dashboard show `Tomcat is not running on app01`
and `vprofile login page is down`. Start Tomcat again (`sudo systemctl start tomcat`) and both turn **RESOLVED**.

The same works for the agent: `sudo systemctl stop zabbix-agent` makes the ZBX icon red and raises
`Zabbix agent is not available` after about 3 minutes.

## Troubleshooting

Logs: agent `/var/log/zabbix/zabbix_agentd.log` (on the monitored VM), server `/var/log/zabbix/zabbix_server.log`
and web interface `/var/log/apache2/error.log` (on `zabbix01`).

| Symptom | Cause | Fix |
|---------|-------|-----|
| `E: Unable to locate package zabbix-...` | `apt update` skipped after adding the repo | `sudo apt update`, then install again |
| "Zabbix server is not running" in the web interface | Wrong `DBPassword` | Part A step 5, then `sudo systemctl restart zabbix-server` |
| `zabbix_get`: `connection error (POLLERR,POLLHUP)` or `Connection refused` | Agent not running | Part B step 4 |
| `zabbix_get`: `No route to host` | Port 10050 blocked | Part B step 5 |
| Agent log: `connection from "192.168.56.17" rejected, allowed hosts: "127.0.0.1"` | `Server=` not changed or agent not restarted | Part B step 3, then `sudo systemctl restart zabbix-agent` |
| Agent log: `host [app01] not found` | Host missing in the web interface or name mismatch | Part B step 7; name must match `Hostname=` |
| `dnf info` shows `From repo : epel` | EPEL's agent installed | Part B step 1, `sudo dnf remove -y zabbix-agent`, then step 2 |
| Agent port check returns `0` while the service is up | SELinux blocks the agent | Use a web scenario (Part C) instead |