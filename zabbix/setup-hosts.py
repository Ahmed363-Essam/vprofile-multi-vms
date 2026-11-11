#!/usr/bin/env python3
"""
Connects the vprofile services to Zabbix. Safe to run again at any time.

  1. Creates read-only monitoring users in MySQL and RabbitMQ.
  2. Changes the Zabbix "Admin" password from the default to
     secrets/zabbix_admin_password.txt.
  3. Creates/updates one Zabbix host per service with the right template:

       vprodb       MySQL by Zabbix agent 2      (via zabbix-agent2)
       vprocache01  Memcached by Zabbix agent 2  (via zabbix-agent2)
       vpromq01     RabbitMQ node by HTTP        (management API :15672)
       vproapp      Apache Tomcat by JMX         (via zabbix-java-gateway, :12345)
       vproweb      Nginx by HTTP                (stub_status on :8081)

Run from the repo root after `docker compose up -d`:
    ./zabbix/setup-hosts.py
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"
API_URL = "http://localhost:8082/api_jsonrpc.php"
GROUP = "vprofile"


def secret(name):
    path = SECRETS / f"{name}.txt"
    if not path.is_file() or not path.read_text().strip():
        sys.exit(f"missing {path} - run ./zabbix/generate-secrets.sh first")
    return path.read_text().strip()


def compose_exec(service, cmd, stdin):
    """Run a command in a service container, passing secrets on stdin
    (so they never show up in a process list)."""
    subprocess.run(
        ["docker", "compose", "exec", "-T", service, *cmd],
        input=stdin, text=True, check=True, cwd=ROOT,
        stdout=subprocess.DEVNULL,
    )


# --------------------------------------------------------------------------
# 1. monitoring users in the services
# --------------------------------------------------------------------------
def create_mysql_monitor_user(password):
    sql = f"""
CREATE USER IF NOT EXISTS 'zbx_monitor'@'%' IDENTIFIED BY '{password}';
ALTER USER 'zbx_monitor'@'%' IDENTIFIED BY '{password}';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'zbx_monitor'@'%';
FLUSH PRIVILEGES;
"""
    compose_exec("vprodb",
                 ["sh", "-c", 'mysql -uroot -p"$(cat /run/secrets/db_mysql_root_password)"'],
                 sql)
    print("ok   MySQL user zbx_monitor (read-only status access)")


def create_rabbitmq_monitor_user(password):
    compose_exec("vpromq01", ["rabbitmqctl", "-q", "await_startup", "--timeout", "120"], "")
    exists = subprocess.run(
        ["docker", "compose", "exec", "-T", "vpromq01", "rabbitmqctl", "-q", "list_users"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    ).stdout.split()
    action = "change_password" if "zbx_monitor" in exists else "add_user"
    # rabbitmqctl reads the password from stdin when it isn't given as an argument
    compose_exec("vpromq01", ["rabbitmqctl", "-q", action, "zbx_monitor"], password + "\n")
    compose_exec("vpromq01", ["rabbitmqctl", "-q", "set_user_tags", "zbx_monitor", "monitoring"], "")
    compose_exec("vpromq01", ["rabbitmqctl", "-q", "set_permissions", "-p", "/",
                              "zbx_monitor", "", "", ".*"], "")
    print("ok   RabbitMQ user zbx_monitor (tag: monitoring, read-only)")


# --------------------------------------------------------------------------
# 2. Zabbix API
# --------------------------------------------------------------------------
class Zabbix:
    def __init__(self, url):
        self.url, self.token, self._id = url, None, 0

    def call(self, method, params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "method": method,
                           "params": params, "id": self._id}).encode()
        req = urllib.request.Request(self.url, body,
                                     {"Content-Type": "application/json-rpc"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error'].get('data') or data['error']}")
        return data["result"]

    def wait_ready(self, timeout=300):
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.call("apiinfo.version", {})
                return
            except (urllib.error.URLError, ConnectionError, RuntimeError):
                time.sleep(5)
        sys.exit("Zabbix API not reachable at " + self.url)

    def login(self, user, passwords, retries=6):
        # retry for a short while: right after a password change Zabbix can
        # briefly reject the new password
        for _ in range(retries):
            for pw in passwords:
                try:
                    self.token = self.call("user.login", {"username": user, "password": pw})
                    return pw
                except RuntimeError:
                    continue
            time.sleep(10)
        sys.exit("cannot log in to Zabbix as Admin (wrong password?)")


def macro(name, value, secret_value=False):
    return {"macro": name, "value": value, "type": 1 if secret_value else 0}


def agent_iface(dns, port, iface_type=1):
    # type 1 = Zabbix agent, 4 = JMX; useip 0 = connect by DNS name
    return {"type": iface_type, "main": 1, "useip": 0, "ip": "",
            "dns": dns, "port": str(port)}


def upsert_host(zbx, name, group_id, template, interfaces, macros):
    tpl = zbx.call("template.get", {"output": ["templateid"], "filter": {"host": [template]}})
    if not tpl:
        sys.exit(f"template not found: {template}")
    params = {
        "host": name,
        "groups": [{"groupid": group_id}],
        "templates": [{"templateid": tpl[0]["templateid"]}],
        "macros": macros,
    }
    existing = zbx.call("host.get", {"output": ["hostid"], "filter": {"host": [name]},
                                     "selectInterfaces": ["interfaceid", "type"]})
    if existing:
        host_id = existing[0]["hostid"]
        # keep the existing interface IDs (items are linked to them) and
        # just update their address/port
        old_by_type = {i["type"]: i["interfaceid"] for i in existing[0]["interfaces"]}
        wanted = [dict(i, interfaceid=old_by_type[str(i["type"])])
                  if str(i["type"]) in old_by_type else i
                  for i in interfaces]
        zbx.call("host.update", {"hostid": host_id, **params, "interfaces": wanted})
        print(f"ok   updated host {name:<12} -> {template}")
    else:
        zbx.call("host.create", {**params, "interfaces": interfaces})
        print(f"ok   created host {name:<12} -> {template}")


def main():
    admin_pw = secret("zabbix_admin_password")
    mysql_pw = secret("zbx_mysql_monitor_password")
    rabbit_pw = secret("zbx_rabbitmq_monitor_password")
    jmx_pw = secret("tomcat_jmx_password")

    create_mysql_monitor_user(mysql_pw)
    create_rabbitmq_monitor_user(rabbit_pw)

    zbx = Zabbix(API_URL)
    zbx.wait_ready()
    used = zbx.login("Admin", [admin_pw, "zabbix"])
    if used == "zabbix":
        admin = zbx.call("user.get", {"output": ["userid"], "filter": {"username": "Admin"}})
        zbx.call("user.update", {"userid": admin[0]["userid"], "current_passwd": "zabbix",
                                 "passwd": admin_pw})
        zbx.login("Admin", [admin_pw])
        print("ok   Zabbix Admin password changed from the default")

    group = zbx.call("hostgroup.get", {"output": ["groupid"], "filter": {"name": [GROUP]}})
    group_id = group[0]["groupid"] if group else \
        zbx.call("hostgroup.create", {"name": GROUP})["groupids"][0]

    agent2 = [agent_iface("zabbix-agent2", 10050)]

    upsert_host(zbx, "vprodb", group_id, "MySQL by Zabbix agent 2", agent2, [
        macro("{$MYSQL.DSN}", "tcp://vprodb:3306"),
        macro("{$MYSQL.USER}", "zbx_monitor"),
        macro("{$MYSQL.PASSWORD}", mysql_pw, secret_value=True),
    ])
    upsert_host(zbx, "vprocache01", group_id, "Memcached by Zabbix agent 2", agent2, [
        macro("{$MEMCACHED.CONN.URI}", "tcp://vprocache01:11211"),
    ])
    upsert_host(zbx, "vpromq01", group_id, "RabbitMQ node by HTTP", [], [
        macro("{$RABBITMQ.API.HOST}", "vpromq01"),
        macro("{$RABBITMQ.NODE.NAME}", "vpromq01"),   # node rabbit@vpromq01 (compose hostname)
        macro("{$RABBITMQ.API.USER}", "zbx_monitor"),
        macro("{$RABBITMQ.API.PASSWORD}", rabbit_pw, secret_value=True),
    ])
    upsert_host(zbx, "vproapp", group_id, "Apache Tomcat by JMX",
                [agent_iface("vproapp", 12345, iface_type=4)], [
        macro("{$TOMCAT.USER}", "zabbix"),
        macro("{$TOMCAT.PASSWORD}", jmx_pw, secret_value=True),
    ])
    upsert_host(zbx, "vproweb", group_id, "Nginx by HTTP", [], [
        macro("{$NGINX.STUB_STATUS.HOST}", "vproweb"),
        macro("{$NGINX.STUB_STATUS.PORT}", "8081"),
    ])

    # the built-in "Zabbix server" host points at 127.0.0.1, which is wrong in
    # Docker; point it at the agent container so it stops showing errors
    srv = zbx.call("host.get", {"output": ["hostid"], "filter": {"host": ["Zabbix server"]},
                                "selectInterfaces": ["interfaceid", "type"]})
    if srv:
        for iface in srv[0]["interfaces"]:
            if iface["type"] == "1":
                zbx.call("hostinterface.update", {"interfaceid": iface["interfaceid"],
                                                  "useip": 0, "dns": "zabbix-agent2"})
        print("ok   'Zabbix server' host now uses zabbix-agent2")

    print("\nDone. Open http://localhost:8082  (user: Admin, password: secrets/zabbix_admin_password.txt)")


if __name__ == "__main__":
    main()
