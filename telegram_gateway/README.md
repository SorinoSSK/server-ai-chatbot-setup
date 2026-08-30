# Telegram Gateway

The Telegram Gateway is the sole interface between the Telegram Bot API and
the rest of the AI agent system. It translates Telegram messages and inline
keyboard button interactions into internal queue messages (and vice versa),
so no other container talks to Telegram directly. It is also responsible for
rendering inline keyboard buttons (Accept / Reject / Request Revision, mode
selection) and for triggering the user's global session reset.

All application code runs inside a Docker container - there is no
standalone (non-Docker) execution path.

## Infrastructure
Python application root is located at
```
telegram_gateway/telegram_gateway_application
```
- Python 3.12 (`python:3.12.4-slim` base image)
- Runs as a Docker container on the project's isolated bridge network (`chatbot-app-network`)
- Depends on RabbitMQ for internal messaging (not yet implemented)
- Depends on the Telegram Bot API via a bot token (not yet implemented)

Under development.

## Getting Started (Development)
The Telegram Gateway container is intended to be managed by the project's
root `./setup.sh` script (run from the `server-ai-chatbot-setup` root
directory) and is not typically invoked directly. You may use the helper
script, `setup.sh`, for standalone `telegram_gateway` development.

### Project Helper Script
Run `setup.sh` from the root directory of the `telegram_gateway` project.
```bash
./setup.sh
```

### Device First-Time Setup
**Step 1:** Run helper script
```bash
./setup.sh
```
**Step 2:** Select option 1 to build and run the project
```
1
```

### Useful Docker Commands
```bash
docker ps
docker images
docker rmi <docker-image-name>
docker start <docker-container-name>
docker stop <docker-container-name>
docker restart <docker-container-name>
```

## Documentation
Under development
