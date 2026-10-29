# Two stages: the Dart SDK compiles bin/server.dart to one native binary, which runs on a bare runtime image.
FROM dart:3.12 AS build
WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN dart pub get
COPY . .
RUN dart pub get --offline && dart compile exe bin/server.dart -o /app/server

FROM scratch
COPY --from=build /runtime/ /
COPY --from=build /app/server /app/server
# Cloud Run sets PORT; 8081 is the default the server falls back to.
EXPOSE 8081
ENTRYPOINT ["/app/server"]
