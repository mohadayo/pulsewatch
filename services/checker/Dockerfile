FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod ./
COPY *.go ./
RUN go build -o checker .

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /app/checker .

EXPOSE 8080

CMD ["./checker"]
