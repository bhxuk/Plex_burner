FROM python:3.12-slim

ARG APP_COMMIT=unknown
ENV APP_COMMIT=${APP_COMMIT} \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# libdvd-pkg builds libdvdcss, which lets dvdbackup read CSS-encrypted DVDs.
RUN sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's/^deb \(.*\) main$/deb \1 main contrib/' /etc/apt/sources.list 2>/dev/null; \
    echo "libdvd-pkg libdvd-pkg/build boolean true" | debconf-set-selections \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates git eject util-linux dvdbackup libdvd-pkg \
 && dpkg-reconfigure -f noninteractive libdvd-pkg \
 && rm -rf /var/lib/apt/lists/*

# Docker CLI and Compose, used by the in-app update button.
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker/compose:2.34.0 /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000
CMD ["waitress-serve", "--host=0.0.0.0", "--port=9000", "--threads=8", "app:app"]
