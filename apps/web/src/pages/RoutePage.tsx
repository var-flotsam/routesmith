import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { api, dataOf, postForm, type Schemas } from "../api/client";

// How often an upload the worker is still reading is checked again.
const PROCESSING_POLL_MS = 2000;

function UploadRow({
  orgId,
  upload,
  onSolve,
  solving,
}: {
  orgId: string;
  upload: Schemas["UploadOut"];
  onSolve: (uploadId: string) => void;
  solving: boolean;
}) {
  const solvable =
    upload.state === "ready" && upload.stops_in_review === 0 && upload.stops_snapped > 0;
  return (
    <tr>
      <td>{upload.file_name}</td>
      <td>{upload.state}</td>
      <td>{upload.stops_snapped}</td>
      <td>
        {upload.stops_in_review > 0 ? (
          <Link to={`/orgs/${orgId}/uploads/${upload.id}/review`}>{upload.stops_in_review}</Link>
        ) : (
          0
        )}
      </td>
      <td>{upload.stops_excluded}</td>
      <td>{upload.rows_rejected}</td>
      <td>
        {solvable && (
          <button type="button" disabled={solving} onClick={() => onSolve(upload.id)}>
            Solve
          </button>
        )}
        <span className="error">{upload.failure_reason}</span>
      </td>
    </tr>
  );
}

/** A route: its truck and sites, its uploads, and a form to upload a stop file. */
export function RoutePage() {
  const { orgId = "", routeId = "" } = useParams();
  const path = { org_id: orgId, route_id: routeId };
  const queryClient = useQueryClient();
  const route = useQuery({
    queryKey: ["route", routeId],
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/routes/{route_id}", { params: { path } })),
  });
  const uploads = useQuery({
    queryKey: ["uploads", routeId],
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/routes/{route_id}/uploads", { params: { path } })),
    refetchInterval: (query) =>
      query.state.data?.some((u) => u.state === "processing") ? PROCESSING_POLL_MS : false,
  });
  const runs = useQuery({
    queryKey: ["runs", routeId],
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/routes/{route_id}/runs", { params: { path } })),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.state === "queued" || r.state === "running")
        ? PROCESSING_POLL_MS
        : false,
  });
  const solve = useMutation({
    mutationFn: async (uploadId: string) =>
      dataOf(
        await api.POST("/orgs/{org_id}/routes/{route_id}/runs", {
          params: { path },
          body: { upload_id: uploadId, objective: "balanced-total" }, // the owner's choice (ADR-0003)
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", routeId] }),
  });
  const [file, setFile] = useState<File | null>(null);
  const send = useMutation({
    mutationFn: async (chosen: File) => {
      const form = new FormData();
      form.append("file", chosen);
      return postForm<Schemas["UploadOut"]>(`/orgs/${orgId}/routes/${routeId}/uploads`, form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["uploads", routeId] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (file !== null) send.mutate(file);
  }

  return (
    <section>
      <p>
        <Link to={`/orgs/${orgId}`}>Routes</Link>
      </p>
      {route.isError && <p className="error">{route.error.message}</p>}
      {route.data && (
        <>
          <h1>{route.data.name}</h1>
          <p className="muted">
            {route.data.capacity_carts ?? "No limit on"} carts per load
            {route.data.max_route_hours !== null &&
              `, at most ${route.data.max_route_hours} hours`}
          </p>
        </>
      )}
      <h2>Stop lists</h2>
      {uploads.data?.length === 0 && <p>No stop lists yet.</p>}
      {uploads.data !== undefined && uploads.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>State</th>
              <th>Placed</th>
              <th>In review</th>
              <th>Left out</th>
              <th>Rejected rows</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {uploads.data.map((upload) => (
              <UploadRow
                key={upload.id}
                orgId={orgId}
                upload={upload}
                onSolve={(id) => solve.mutate(id)}
                solving={solve.isPending}
              />
            ))}
          </tbody>
        </table>
      )}
      {solve.isError && <p className="error">{solve.error.message}</p>}
      <h2>Runs</h2>
      {runs.data?.length === 0 && <p>No runs yet. Solve a stop list once its review is clear.</p>}
      <ul>
        {runs.data?.map((run) => (
          <li key={run.id}>
            <Link to={`/orgs/${orgId}/runs/${run.id}`}>
              {new Date(run.created_at).toLocaleString()}: {run.trucks}{" "}
              {run.trucks === 1 ? "truck" : "trucks"}, {run.state}
            </Link>
          </li>
        ))}
      </ul>
      <h2>Upload a stop list</h2>
      <form onSubmit={submit}>
        <label>
          Stop list (CSV: stop_id, current_sequence, and lon and lat or an address)
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={send.isPending || file === null}>
          Upload
        </button>
        {send.isError && <p className="error">{send.error.message}</p>}
      </form>
    </section>
  );
}
