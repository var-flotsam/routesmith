import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, dataOf, type Schemas } from "../api/client";

/** The caller's organizations, and a form to start one. */
export function Organizations({ me }: { me: Schemas["Me"] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: async (orgName: string) =>
      dataOf(await api.POST("/orgs", { body: { name: orgName } })),
    onSuccess: () => {
      setName("");
      return queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(name);
  }

  return (
    <section>
      <h1>Organizations</h1>
      {me.organizations.length === 0 ? (
        <p>You are not in an organization yet. Start one for your hauling company.</p>
      ) : (
        <ul>
          {me.organizations.map((org) => (
            <li key={org.org_id}>
              {org.name} <span className="muted">({org.role})</span>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit}>
        <label>
          New organization
          <input required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <button type="submit" disabled={create.isPending}>
          Create
        </button>
        {create.isError && <p className="error">{create.error.message}</p>}
      </form>
    </section>
  );
}
