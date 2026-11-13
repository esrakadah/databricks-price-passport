# Two stages: the Dart SDK compiles bin/server.dart to one native binary, which runs on a bare runtime image.
FROM dart:3.12 AS build
WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN dart pub get
COPY . .
RUN dart pub get --offline && dart compile exe bin/server.dart -o /app/server && mkdir -p /app/public

FROM scratch
COPY --from=build /runtime/ /
COPY --from=build /app/server /app/server
# The Flutter web app that deploy.sh builds into public/; empty when the image is built without it.
COPY --from=build /app/public /app/public
# Cloud Run sets PORT; 8080 is the default the server falls back to.
EXPOSE 8080
ENTRYPOINT ["/app/server"]
