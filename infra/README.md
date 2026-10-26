# infra

`Dockerfile` builds one image for the API, the worker and migrations; the
Compose file at the repository root (`compose.yaml`) runs them with Postgres
(PostGIS) and Redis. Deploy configuration comes with phase 5.
