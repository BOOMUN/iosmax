# Remote Web deployment

The remote deployment keeps the FastAPI process and its Nginx security proxy
on loopback-only ports:

- FastAPI: `127.0.0.1:18010`
- Nginx: `127.0.0.1:18011`
- Public ingress: Cloudflare Tunnel to the Nginx port

`iosmax.service` runs as the unprivileged `ubuntu` user and reads its settings
from `/home/ubuntu/iosmax-deploy/web/shared/iosmax.env`. Production settings
must include a unique initial administrator password, a dedicated data
directory, secure cookies, and disabled API documentation:

```dotenv
IOSMAX_DATA_DIR=/home/ubuntu/iosmax-deploy/web/shared/data
IOSMAX_ADMIN_USERNAME=admin
IOSMAX_ADMIN_PASSWORD=generate-a-unique-password
IOSMAX_SESSION_HOURS=12
IOSMAX_COOKIE_SECURE=true
IOSMAX_DOCS_ENABLED=false
```

The included Nginx configuration adds security headers, WebSocket forwarding,
connection limits, and login request throttling. A Cloudflare Quick Tunnel can
provide immediate HTTPS access, but its generated hostname is not permanent.
Use a named tunnel and a controlled domain for a stable production URL.

Do not copy a workstation `data/` directory to a public server by default. It
contains the database, encryption key, device credentials, and tunnel profiles.
