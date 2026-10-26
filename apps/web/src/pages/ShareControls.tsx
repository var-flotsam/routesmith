import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, dataOf } from "../api/client";

/** Make or take away a read-only link to this run's result. */
export function ShareControls({ orgId, runId }: { orgId: string; runId: string }) {
  const path = { org_id: orgId, run_id: runId };
  const queryClient = useQueryClient();
  const [link, setLink] = useState<string | null>(null);
  const state = useQuery({
    queryKey: ["share", runId],
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/runs/{run_id}/share-link", { params: { path } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["share", runId] });
  const share = useMutation({
    mutationFn: async () =>
      dataOf(await api.PUT("/orgs/{org_id}/runs/{run_id}/share-link", { params: { path } })),
    onSuccess: (made) => {
      setLink(made.url);
      return refresh();
    },
  });
  const stop = useMutation({
    mutationFn: async () => {
      const answer = await api.DELETE("/orgs/{org_id}/runs/{run_id}/share-link", {
        params: { path },
      });
      if (!answer.response.ok) dataOf(answer);
    },
    onSuccess: () => {
      setLink(null);
      return refresh();
    },
  });
  const failure = share.error ?? stop.error;

  return (
    <div className="share">
      {link !== null ? (
        <p>
          Anyone with this link can see this result, without signing in:{" "}
          <input readOnly value={link} aria-label="Share link" onFocus={(e) => e.target.select()} />{" "}
          <button type="button" onClick={() => void navigator.clipboard?.writeText(link)}>
            Copy
          </button>
        </p>
      ) : (
        state.data?.shared && (
          <p className="muted">
            Shared by link. Make a new link to see it again; the old one then stops working.
          </p>
        )
      )}
      <button type="button" disabled={share.isPending} onClick={() => share.mutate()}>
        {state.data?.shared ? "Make a new share link" : "Share a read-only link"}
      </button>{" "}
      {state.data?.shared && (
        <button
          type="button"
          className="secondary"
          disabled={stop.isPending}
          onClick={() => stop.mutate()}
        >
          Stop sharing
        </button>
      )}
      {failure && <p className="error">{failure.message}</p>}
    </div>
  );
}
