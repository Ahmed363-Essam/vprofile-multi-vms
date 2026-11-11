# determine the image you use
FROM maven:3.9.9-eclipse-temurin-21-jammy AS BUILD_IMAGE
# create an app directory
WORKDIR /app

# clone the repository
RUN git clone https://github.com/hkhcoder/vprofile-project.git

RUN cd vprofile-project && git checkout docker && mvn install

FROM tomcat:10-jdk21

# create a dedicated non-root user for Tomcat
RUN groupadd --system --gid 1001 tomcat && \
    useradd --system --uid 1001 --gid tomcat --no-create-home --shell /usr/sbin/nologin tomcat

# remove default apps and copy the built war file as ROOT.war
RUN rm -rf /usr/local/tomcat/webapps/*
COPY --from=BUILD_IMAGE --chown=tomcat:tomcat /app/vprofile-project/target/vprofile-v2.war /usr/local/tomcat/webapps/ROOT.war

# enables password-protected JMX for Zabbix monitoring (see setenv.sh)
COPY setenv.sh /usr/local/tomcat/bin/setenv.sh

# Tomcat must be able to write logs, temp files, work dir and unpack the WAR
RUN chown -R tomcat:tomcat /usr/local/tomcat

# run as non-root
USER tomcat

EXPOSE 8080
CMD ["catalina.sh", "run"]
