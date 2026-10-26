import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { api, dataOf } from "../api/client";

function number(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

/** An organization's routes, and a form to add one. */
export function OrgPage() {
  const { orgId = "" } = useParams();
  const path = { org_id: orgId };
  const queryClient = useQueryClient();
  const routes = useQuery({
    queryKey: ["routes", orgId],
    queryFn: async () => dataOf(await api.GET("/orgs/{org_id}/routes", { params: { path } })),
  });
  const [form, setForm] = useState({
    name: "",
    yard: "",
    disposal: "",
    capacity: "",
    hours: "",
  });
  const create = useMutation({
    mutationFn: async () => {
      const point = (text: string) => {
        const [lon, lat] = text.split(",").map((part) => Number(part.trim()));
        return { lon: lon ?? NaN, lat: lat ?? NaN };
      };
      const body = {
        name: form.name,
        yard: point(form.yard),
        disposal: point(form.disposal),
        capacity_carts: number(form.capacity),
        max_route_hours: number(form.hours),
      };
      return dataOf(await api.POST("/orgs/{org_id}/routes", { params: { path }, body }));
    },
    onSuccess: () => {
      setForm({ name: "", yard: "", disposal: "", capacity: "", hours: "" });
      return queryClient.invalidateQueries({ queryKey: ["routes", orgId] });
    },
  });

  function field(key: keyof typeof form) {
    return {
      value: form[key],
      onChange: (event: { target: { value: string } }) =>
        setForm({ ...form, [key]: event.target.value }),
    };
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <section>
      <p>
        <Link to="/">Organizations</Link>
      </p>
      <h1>Routes</h1>
      {routes.isPending && <p>Loading…</p>}
      {routes.isError && <p className="error">{routes.error.message}</p>}
      {routes.data?.length === 0 && <p>No routes yet. Add the first one below.</p>}
      <ul>
        {routes.data?.map((route) => (
          <li key={route.id}>
            <Link to={`/orgs/${orgId}/routes/${route.id}`}>{route.name}</Link>
          </li>
        ))}
      </ul>
      <h2>New route</h2>
      <form onSubmit={submit}>
        <label>
          Name
          <input required {...field("name")} />
        </label>
        <label>
          Yard (lon, lat)
          <input required placeholder="-73.6463, 41.0171" {...field("yard")} />
        </label>
        <label>
          Disposal site (lon, lat)
          <input required placeholder="-73.6463, 41.0171" {...field("disposal")} />
        </label>
        <label>
          Carts per load
          <input type="number" min={1} {...field("capacity")} />
        </label>
        <label>
          Longest route, hours
          <input type="number" min={0} step="any" {...field("hours")} />
        </label>
        <button type="submit" disabled={create.isPending}>
          Add route
        </button>
        {create.isError && <p className="error">{create.error.message}</p>}
      </form>
    </section>
  );
}
