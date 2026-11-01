FROM python:3.12-slim

LABEL org.opencontainers.image.title="Plex Burner" \
      org.opencontainers.image.description="Copy your DVDs into Plex, Jellyfin or Emby from a web dashboard" \
      org.opencontainers.image.source="https://github.com/bhxuk/Plex_burner" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive

# ffmpeg, lsdvd and dvdbackup read DVDs. libdvd-pkg builds libdvdcss so encrypted
# discs can be read. 7zip unpacks data discs. eject opens the tray.
RUN sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
 && echo "libdvd-pkg libdvd-pkg/build boolean true" | debconf-set-selections \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates git eject util-linux ffmpeg lsdvd dvdbackup 7zip libdvd-pkg \
 && dpkg-reconfigure -f noninteractive libdvd-pkg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
 && sha256sum requirements.txt | cut -d' ' -f1 > /usr/local/.plex-burner-req

# The compose file mounts the git checkout over /app so in-app updates work.
# The copy below lets the image also run on its own (without self-update).
COPY app ./app
COPY scripts/docker-entrypoint.sh /usr/local/bin/plex-burner-entrypoint
RUN chmod +x /usr/local/bin/plex-burner-entrypoint

ENV DATA_DIR=/data \
    PORT=9000 \
    INSTALL_METHOD=docker \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 9000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','9000')+'/api/health',timeout=4)"

ENTRYPOINT ["plex-burner-entrypoint"]
