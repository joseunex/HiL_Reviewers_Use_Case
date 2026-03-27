FROM openjdk:11.0.11-jre-slim
WORKDIR /app
COPY target/*-thorntail.jar app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]
