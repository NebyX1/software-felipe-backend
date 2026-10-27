FROM golang:1.24.6-alpine AS build
RUN apk add --no-cache git build-base
WORKDIR /src
RUN git clone --depth 1 --branch RELEASE.2025-04-22T22-12-26Z https://github.com/minio/minio.git .
RUN CGO_ENABLED=0 go build -trimpath -o /minio .
FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl
COPY --from=build /minio /usr/bin/minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
