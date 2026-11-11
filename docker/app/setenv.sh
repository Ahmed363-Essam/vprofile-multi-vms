#!/bin/sh
# Sourced automatically by catalina.sh on startup.
#
# Enables JMX on port 12345 for Zabbix ("Apache Tomcat by JMX" template), with
# password authentication. The password comes from the Docker secret
# tomcat_jmx_password. Without the secret, JMX stays disabled.

JMX_SECRET=/run/secrets/tomcat_jmx_password

if [ -s "$JMX_SECRET" ]; then
  JMX_DIR="$CATALINA_BASE/temp/jmx"
  mkdir -p "$JMX_DIR"

  # the JVM refuses a password file that other users can read, so build
  # owner-only copies (the mounted secret file itself is world-readable)
  (
    umask 077
    printf 'zabbix %s\n' "$(cat "$JMX_SECRET")" > "$JMX_DIR/jmxremote.password"
    printf 'zabbix readonly\n'                  > "$JMX_DIR/jmxremote.access"
  )

  CATALINA_OPTS="$CATALINA_OPTS \
    -Dcom.sun.management.jmxremote \
    -Dcom.sun.management.jmxremote.port=12345 \
    -Dcom.sun.management.jmxremote.rmi.port=12345 \
    -Dcom.sun.management.jmxremote.authenticate=true \
    -Dcom.sun.management.jmxremote.password.file=$JMX_DIR/jmxremote.password \
    -Dcom.sun.management.jmxremote.access.file=$JMX_DIR/jmxremote.access \
    -Dcom.sun.management.jmxremote.ssl=false \
    -Djava.rmi.server.hostname=vproapp"
  export CATALINA_OPTS
fi
