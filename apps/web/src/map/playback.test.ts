import { pointAlong, truckAt, type Point } from "./playback";

const L: Point[] = [
  [0, 0],
  [0, 1],
  [0, 3],
];

test("a point a share of the way along is measured by length, not by corner", () => {
  expect(pointAlong(L, 0)).toEqual([0, 0]);
  expect(pointAlong(L, 0.5)).toEqual([0, 1.5]);
  expect(pointAlong(L, 1)).toEqual([0, 3]);
  expect(pointAlong(L, 2)).toEqual([0, 3]);
  expect(pointAlong([], 0.5)).toBeNull();
});

test("on one clock, the shorter route's truck is home first", () => {
  expect(truckAt(L, 100, 50)).toEqual([0, 1.5]);
  expect(truckAt(L, 50, 50)).toEqual([0, 3]);
  expect(truckAt(L, 200, 50)).toEqual([0, 0.75]);
});
