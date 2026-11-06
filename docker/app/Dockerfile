# determine the image you use 
FROM maven:3.9.9-eclipse-temurin-21-jammy AS BUILD_IMAGE
# create an app directory
WORKDIR /app

# clone the repository
RUN git clone https://github.com/hkhcoder/vprofile-project.git


RUN cd vprofile-project && git checkout docker && mvn install

FROM tomcat:10-jdk21

# copy the built war file from the build image to the tomcat webapps directory
COPY --from=BUILD_IMAGE app/vprofile-project/target/vprofile-v2.war /usr/local/tomcat/webapps/ROOT.war


EXPOSE 8080
CMD ["catalina.sh", "run"]