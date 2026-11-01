# Plex Burner

Copy your DVDs into a Plex library, one disc at a time. Insert a disc, name it, and Plex Burner saves it to your media folder, then ejects it for the next one. It runs as a Docker container and you control it from a browser on your network.

**Website:** https://bhxuk.github.io/Plex_burner/

## What it does

- Detects a disc in `/dev/sr0` and suggests a name from the disc title.
- Waits for you to confirm or change the name, or starts by itself after `AUTO_START_SECONDS`.
- Copies DVDs as a `VIDEO_TS` folder that Plex and VLC play directly. Data discs are saved as an `.iso`.
- Ejects the disc when the copy finishes.
- Dashboard on port 9000 with a log, a one-click **Update now** button, and the changelog.

## Install

On a Linux server with Docker, Docker Compose and a DVD drive:

```sh
git clone https://github.com/bhxuk/Plex_burner
cd Plex_burner
sh scripts/update.sh
```

Then open `http://<server-ip>:9000`.

## Settings

Set these as environment variables before running `scripts/update.sh`, or edit `docker-compose.yml`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MEDIA_HOST_DIR` | `/home/bhxuk/data/media/movies` | Folder on the server where discs are saved. Point a Plex library at it. |
| `PB_HOST_DIR` | `/home/bhxuk/Plex_burner` | Where this repo is cloned on the server. The update button needs it. |
| `AUTO_START_SECONDS` | `120` | Seconds to wait for a name before copying. `0` turns auto-start off. |

## Updating

Click **Check for updates** in the dashboard, then **Update now**. It pulls the latest commit from GitHub and rebuilds the container. You can also run `sh scripts/update.sh` on the server.

## Notes

- The update button needs the Docker socket, which gives the container control of Docker on the host. Keep port 9000 on your home network only.
- Audio CDs are not supported yet.
- Copying encrypted DVDs is legal for personal backups in some countries and not others. Check your local rules.
