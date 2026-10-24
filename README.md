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
