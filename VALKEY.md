# Running Valkey with Docker

[Valkey](https://valkey.io/) is an open-source, high-performance key-value store (a fork of Redis) that we can use for reliable session state management and caching across the application.

## Quick Start (Development)

To spin up a local instance of Valkey using Docker and expose it on the standard Redis/Valkey port (`6379`) to your `localhost`, run the following command in your terminal:

```bash
docker run -d \
  --name baasha-valkey \
  -p 6379:6379 \
  valkey/valkey:latest
```

### Explanation:
- `-d`: Runs the container in the background (detached mode).
- `--name baasha-valkey`: Assigns a recognizable name to the container.
- `-p 6379:6379`: Maps port 6379 inside the container to port 6379 on your local host, making it accessible to `mcp_server.py` or `server.py` running locally.
- `valkey/valkey:latest`: Pulls the official, latest Valkey image from Docker Hub.

---

## Verifying the Setup

You can verify that Valkey is running and responding to commands using the `valkey-cli` (or standard `redis-cli`) inside the container:

```bash
docker exec -it baasha-valkey valkey-cli ping
```
*Expected Output:* `PONG`

## Adding to Docker Compose (Optional)

If you'd like to integrate Valkey directly into the production/staging `docker-compose.yml` stack alongside the API and Caddy, you can append the following service block:

```yaml
  valkey:
    image: valkey/valkey:latest
    container_name: valkey
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - valkey_data:/data
    networks:
      - caddy
    command: ["valkey-server", "--save", "60", "1", "--loglevel", "warning"]

volumes:
  valkey_data:
```

## Connecting in Python

Since Valkey is fully compatible with the Redis protocol, you can use the standard Python `redis` library to connect to it in `mcp_server.py`:

```bash
pip install redis
```

```python
import redis

# Connect to the local Valkey instance
session_db = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Usage
session_db.set('my_key', 'my_value')
value = session_db.get('my_key')
```
