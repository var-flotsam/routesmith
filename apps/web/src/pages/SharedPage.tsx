import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { api, dataOf } from "../api/client";
import { ReportView } from "./ReportView";

/** A result shared by link: read-only, and no sign-in needed. */
export function SharedPage() {
  const { token = "" } = useParams();
  const shared = useQuery({
    queryKey: ["shared", token],
    queryFn: async () =>
      dataOf(await api.GET("/shared/{token}", { params: { path: { token } } })),
  });
  return (
    <div className="shell">
      <header>
        <strong>Starboard Routing</strong>
        <span className="muted">Shared result, read only</span>
      </header>
      <main>
        {shared.isPending && <p>Loading…</p>}
        {shared.isError && (
          <p className="error">This link does not work. It may have been taken away.</p>
        )}
        {shared.data && (
          <section>
            <h1>{shared.data.route_name}</h1>
            {shared.data.finished_at && (
              <p className="muted">
                Solved {new Date(shared.data.finished_at).toLocaleString()}
              </p>
            )}
            <ReportView report={shared.data.report} />
          </section>
        )}
      </main>
    </div>
  );
}
