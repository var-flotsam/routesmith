import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { api, dataOf } from "../api/client";
import { Downloads } from "./Downloads";
import { ReportView } from "./ReportView";
import { ShareControls } from "./ShareControls";
import { StopTable } from "./StopTable";

// How often a run that is still solving is checked again.
const RUNNING_POLL_MS = 3000;

/** One run: its state while solving, then current against optimized for the area. */
export function RunPage() {
  const { orgId = "", runId = "" } = useParams();
  const path = { org_id: orgId, run_id: runId };
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: async () => dataOf(await api.GET("/orgs/{org_id}/runs/{run_id}", { params: { path } })),
    refetchInterval: (query) =>
      query.state.data?.state === "queued" || query.state.data?.state === "running"
        ? RUNNING_POLL_MS
        : false,
  });
  const succeeded = run.data?.state === "succeeded";
  const report = useQuery({
    queryKey: ["result", runId],
    enabled: succeeded,
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/runs/{run_id}/result", { params: { path } })),
  });

  return (
    <section>
      {run.data && (
        <p>
          <Link to={`/orgs/${orgId}/routes/${run.data.route_id}`}>Back to the route</Link>
        </p>
      )}
      <h1>Run</h1>
      {run.isError && <p className="error">{run.error.message}</p>}
      {run.data && !succeeded && (
        <p>
          {run.data.state === "failed"
            ? `The run failed: ${run.data.failure_reason ?? "no reason given"}`
            : `Solving for ${run.data.trucks} trucks (${run.data.state})…`}
        </p>
      )}
      {report.isError && <p className="error">{report.error.message}</p>}
      {report.data && (
        <>
          <ShareControls orgId={orgId} runId={runId} />
          <Downloads orgId={orgId} runId={runId} />
          <ReportView report={report.data}>
            {run.data && (
              <>
                <h2>Stops</h2>
                <StopTable orgId={orgId} uploadId={run.data.upload_id} report={report.data} />
              </>
            )}
          </ReportView>
        </>
      )}
    </section>
  );
}
