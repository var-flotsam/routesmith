# Starboard Routing

Starboard Routing re-sequences residential waste collection routes for
automated side-loader trucks, whose single arm can only reach carts on the
truck's right. It takes a hauler's current stop list, works out an order of
street passes that keeps every cart on the right, never drives the wrong way
on a one-way street, keeps left turns and U-turns rare, and minimizes total
drive time.

The result is shown as a side-by-side map of the current route and the
optimized one, with a scorecard of distance, drive time, turns, wrong-side
pickups and dead-head distance for both, and exports a printable driver route
sheet, a CSV of stops in the new order, and a GPX/KML path.

## Run it locally

Needs Docker Desktop (with WSL2 on Windows). From the repository root:

1. If the Overpass API is out of reach from your network, put an OpenStreetMap
   extract (a Geofabrik `.osm.pbf` for your state) under `cache/osm/extracts/`
   and name it in a `.env` file at the repository root, for example
   `STARBOARD_OSM_EXTRACT=/app/cache/osm/extracts/connecticut-latest.osm.pbf`.
   `cache/` and `.env` stay out of git.
2. `docker compose up --build` starts the database, Redis, the API, the worker
   and the web app. The first start builds the image and installs the web
   dependencies, which takes a few minutes.
3. In a second terminal, `docker compose run --rm api python -m starboard.api.demo you@example.com`
   preloads the Byram demo route for that email.
4. Open http://localhost:5173 and ask for a sign-in link with the same email.
   Running locally, no email is sent: `docker compose logs api` prints the link.
   Open it in the same browser.
5. Open Demo, then Byram (demo). The stop list is snapped in the background;
   the first time, the worker downloads the street network for the area. Clear
   any stops in review, then press Solve.

`docker compose down` stops everything. Data stays in Docker volumes until
`docker compose down -v`.
