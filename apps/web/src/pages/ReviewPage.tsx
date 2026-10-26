import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { Link, useParams } from "react-router";

import { api, dataOf, type Schemas } from "../api/client";

// The map library is large and needs WebGL, so it loads only when a map is shown.
const ReviewMap = lazy(async () => ({ default: (await import("../map/ReviewMap")).ReviewMap }));

type Stop = Schemas["StopOut"];
type Side = Schemas["CurbSide"];

// What each review reason means for the planner.
const REASONS: Record<string, string> = {
  outside_network: "No street near enough",
  ambiguous_street: "About as near one street as another",
  side_undetermined: "On the centre line; side of street unclear",
  wrong_side_of_one_way: "On the left of a one-way street",
  address_not_found: "Address not found",
  address_ambiguous: "Address matches more than one place",
  address_inexact: "Address found only after correcting it",
};

const OTHER_SIDE: Record<Side, Side> = { left: "right", right: "left" };

/** Clear an upload's review queue: put each stop on a street, or leave it out. */
export function ReviewPage() {
  const { orgId = "", uploadId = "" } = useParams();
  const path = { org_id: orgId, upload_id: uploadId };
  const queryClient = useQueryClient();
  const upload = useQuery({
    queryKey: ["upload", uploadId],
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/uploads/{upload_id}", { params: { path } })),
  });
  const review = useQuery({
    queryKey: ["review", uploadId],
    queryFn: async () =>
      dataOf(
        await api.GET("/orgs/{org_id}/uploads/{upload_id}/stops", {
          params: { path, query: { state: "review" } },
        }),
      ),
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const stops = review.data ?? [];
  const selected: Stop | undefined = stops.find((s) => s.stop_id === selectedId) ?? stops[0];

  const done = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["review", uploadId] }),
      queryClient.invalidateQueries({ queryKey: ["upload", uploadId] }),
      queryClient.invalidateQueries({ queryKey: ["uploads"] }),
    ]);
  const place = useMutation({
    mutationFn: async (choice: { stopId: string; segmentId: string; side: Side }) => {
      const stopPath = { ...path, stop_id: choice.stopId };
      return dataOf(
        await api.PUT("/orgs/{org_id}/uploads/{upload_id}/stops/{stop_id}/placement", {
          params: { path: stopPath },
          body: { segment_id: choice.segmentId, curb_side: choice.side },
        }),
      );
    },
    onSuccess: done,
  });
  const exclude = useMutation({
    mutationFn: async (stopId: string) =>
      dataOf(
        await api.PUT("/orgs/{org_id}/uploads/{upload_id}/stops/{stop_id}/exclusion", {
          params: { path: { ...path, stop_id: stopId } },
        }),
      ),
    onSuccess: done,
  });
  const failure = place.error ?? exclude.error;
  const back = upload.data && `/orgs/${orgId}/routes/${upload.data.route_id}`;

  return (
    <section>
      {back && (
        <p>
          <Link to={back}>Back to the route</Link>
        </p>
      )}
      <h1>Review {upload.data?.file_name}</h1>
      {review.isPending && <p>Loading…</p>}
      {review.isError && <p className="error">{review.error.message}</p>}
      {review.isSuccess && stops.length === 0 && (
        <p>Nothing left to review. This stop list is ready to solve.</p>
      )}
      {selected && (
        <div className="review">
          <ol className="review-list">
            {stops.map((stop) => (
              <li key={stop.stop_id}>
                <button
                  type="button"
                  aria-current={stop === selected}
                  onClick={() => setSelectedId(stop.stop_id)}
                >
                  {stop.stop_id} <span className="muted">{REASONS[stop.review_reason ?? ""]}</span>
                </button>
              </li>
            ))}
          </ol>
          <div>
            <h2>Stop {selected.stop_id}</h2>
            <p>
              {REASONS[selected.review_reason ?? ""] ?? selected.review_reason}
              {selected.review_detail && <span className="muted"> ({selected.review_detail})</span>}
            </p>
            {selected.lon !== null && (
              <Suspense fallback={<div className="map">Loading the map…</div>}>
                <ReviewMap stop={selected} chosen={hovered} />
              </Suspense>
            )}
            {selected.candidate_streets.length === 0 && (
              <p>There is no street to choose for this stop; leave it out of the routes.</p>
            )}
            <ul className="choices">
              {selected.candidate_streets.map((street) => (
                <li
                  key={street.segment_id}
                  onMouseEnter={() => setHovered(street.segment_id)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <button
                    type="button"
                    disabled={place.isPending}
                    onClick={() =>
                      place.mutate({
                        stopId: selected.stop_id,
                        segmentId: street.segment_id,
                        side: street.curb_side,
                      })
                    }
                  >
                    Collect from {street.name ?? "this street"}
                  </button>{" "}
                  <button
                    type="button"
                    className="secondary"
                    disabled={place.isPending}
                    onClick={() =>
                      place.mutate({
                        stopId: selected.stop_id,
                        segmentId: street.segment_id,
                        side: OTHER_SIDE[street.curb_side],
                      })
                    }
                  >
                    the cart is across {street.name ?? "the street"}
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="secondary"
              disabled={exclude.isPending}
              onClick={() => exclude.mutate(selected.stop_id)}
            >
              Leave this stop out
            </button>
            {failure && <p className="error">{failure.message}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
