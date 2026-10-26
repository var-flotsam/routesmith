import { render } from "@testing-library/react";
import { vi } from "vitest";

import { RouteMap } from "./RouteMap";
import { BASEMAP_STYLE, PLAIN_STYLE } from "./style";

// A stand-in for MapLibre, which needs WebGL: it records the style it is given and lets
// the test fire the map's events.
const maps = vi.hoisted(() => [] as { style: unknown; fire: (type: string) => void }[]);

vi.mock("maplibre-gl", () => {
  class FakeMap {
    style: unknown;
    handlers: { type: string; listener: (event: unknown) => void; once: boolean }[] = [];
    constructor(options: { style: unknown }) {
      this.style = options.style;
      maps.push(this);
    }
    on(type: string, listener: (event: unknown) => void) {
      this.handlers.push({ type, listener, once: false });
      return this;
    }
    once(type: string, listener: (event: unknown) => void) {
      this.handlers.push({ type, listener, once: true });
      return this;
    }
    fire(type: string) {
      for (const handler of this.handlers.filter((h) => h.type === type)) {
        if (handler.once) this.handlers.splice(this.handlers.indexOf(handler), 1);
        handler.listener({ error: new Error(`${type} in test`) });
      }
    }
    setStyle(style: unknown) {
      this.style = style;
    }
    fitBounds() {}
    remove() {}
    isStyleLoaded() {
      return false;
    }
    getSource() {
      return undefined;
    }
  }
  class LngLatBounds {
    points = 0;
    extend() {
      this.points += 1;
    }
    isEmpty() {
      return this.points === 0;
    }
  }
  return { default: { Map: FakeMap, LngLatBounds } };
});

const PATH: [number, number][] = [
  [-73.65, 41.0],
  [-73.64, 41.01],
];

function drawMap() {
  maps.length = 0;
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <RouteMap current={[PATH]} optimized={[PATH]} shown={new Set(["current"])} view="overlay" />,
  );
  const map = maps[0];
  if (map === undefined) throw new Error("no map was drawn");
  return map;
}

test("when the basemap fails to load, the routes are drawn on a plain background", () => {
  const map = drawMap();
  expect(map.style).toBe(BASEMAP_STYLE);
  map.fire("error");
  expect(map.style).toBe(PLAIN_STYLE);
  expect(console.error).toHaveBeenCalledWith(new Error("error in test"));
});

test("a tile that fails after the basemap has loaded leaves the basemap", () => {
  const map = drawMap();
  map.fire("style.load");
  map.fire("error");
  expect(map.style).toBe(BASEMAP_STYLE);
  expect(console.error).toHaveBeenCalled();
});
