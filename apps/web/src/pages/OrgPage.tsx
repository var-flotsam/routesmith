import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { api, dataOf, type Schemas } from "../api/client";
import { describe } from "./places";

type Place = Schemas["PlaceOut"];
type SiteKey = "yard" | "disposal";

const SITE_NAMES: Record<SiteKey, string> = { yard: "yard", disposal: "disposal site" };
// The longest address the geocoder takes (the API's limit too).
const ADDRESS_MAX_CHARACTERS = 100;

function number(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

/** The text of an address as it is looked up: spaces collapsed, as the API does. */
function asked(text: string): string {
  return text.trim().split(/\s+/).join(" ");
}

/** The places an address could be. An address does not move, so an answer is kept. */
function placesQuery(orgId: string, address: string) {
  return {
    queryKey: ["places", orgId, address],
    queryFn: async () =>
      dataOf(
        await api.GET("/orgs/{org_id}/places", {
          params: { path: { org_id: orgId }, query: { address } },
        }),
      ),
    staleTime: Infinity,
  };
}

/** The place for a site's address: the only one found, or the one the planner picked. */
async function siteFor(
  client: QueryClient,
  orgId: string,
  key: SiteKey,
  text: string,
  picked: number | null,
): Promise<Place> {
  const name = SITE_NAMES[key];
  if (asked(text) === "") throw new Error(`Give the ${name}'s address.`);
  const places = await client.fetchQuery(placesQuery(orgId, asked(text)));
  const [only, ...others] = places;
  if (only === undefined) throw new Error(`No place found for the ${name}'s address.`);
  if (others.length === 0) return only;
  const place = picked === null ? undefined : places[picked];
  if (place === undefined) throw new Error(`Several places fit the ${name}'s address; pick one.`);
  return place;
}

/**
 * A route's yard or disposal site: an address (or lat, lon), looked up when the field is
 * left or the form is sent. What the lookup found is announced to screen readers.
 */
function SiteField(props: {
  orgId: string;
  label: string;
  text: string;
  lookedUp: string;
  picked: number | null;
  onText: (text: string) => void;
  onLookUp: () => void;
  onPick: (index: number) => void;
}) {
  const { orgId, label, text, lookedUp, picked, onText, onLookUp, onPick } = props;
  const found = useId();
  const places = useQuery({ ...placesQuery(orgId, lookedUp), enabled: lookedUp !== "" });
  const current = lookedUp !== "" && lookedUp === asked(text);
  const failed = current && (places.isError || places.data?.length === 0);
  function leave() {
    // Leaving the field again after a failed lookup asks again.
    if (current && places.isError) void places.refetch();
    else onLookUp();
  }
  return (
    <div className="site">
      <label>
        {label}
        <input
          required
          maxLength={ADDRESS_MAX_CHARACTERS}
          placeholder="1 Main St, Greenwich, CT, or 41.0171, -73.6463"
          value={text}
          aria-describedby={found}
          aria-invalid={failed}
          onChange={(event) => onText(event.target.value)}
          onBlur={leave}
        />
      </label>
      <div id={found} role="status">
        {current && places.isFetching && <p className="muted">Looking it up…</p>}
        {current && places.isError && (
          <p className="error">
            The address service did not answer ({places.error.message}). Leave the field to try
            again.
          </p>
        )}
        {current && places.data?.length === 0 && (
          <p className="error">
            No place found for that address. Check it, or give the latitude and longitude, such
            as 41.0171, -73.6463.
          </p>
        )}
        {current && places.data?.length === 1 && places.data[0] && (
          <p className="muted">Found: {describe(places.data[0])}</p>
        )}
      </div>
      {current && places.data !== undefined && places.data.length > 1 && (
        <fieldset>
          <legend>Several places fit the {label.toLowerCase()}. Which one?</legend>
          {places.data.map((place, index) => (
            <label key={index} className="inline">
              <input
                type="radio"
                name={label}
                checked={picked === index}
                onChange={() => onPick(index)}
              />
              {describe(place)}
            </label>
          ))}
        </fieldset>
      )}
    </div>
  );
}

const EMPTY = { name: "", yard: "", disposal: "", capacity: "", hours: "" };
const NONE_PICKED: Record<SiteKey, number | null> = { yard: null, disposal: null };
const NONE_LOOKED_UP: Record<SiteKey, string> = { yard: "", disposal: "" };

/** An organization's routes, and a form to add one. */
export function OrgPage() {
  const { orgId = "" } = useParams();
  const path = { org_id: orgId };
  const queryClient = useQueryClient();
  const routes = useQuery({
    queryKey: ["routes", orgId],
    queryFn: async () => dataOf(await api.GET("/orgs/{org_id}/routes", { params: { path } })),
  });
  const [form, setForm] = useState(EMPTY);
  const [picked, setPicked] = useState(NONE_PICKED);
  const [lookedUp, setLookedUp] = useState(NONE_LOOKED_UP);
  const create = useMutation({
    mutationFn: async () => {
      const yard = await siteFor(queryClient, orgId, "yard", form.yard, picked.yard);
      const disposal = await siteFor(
        queryClient,
        orgId,
        "disposal",
        form.disposal,
        picked.disposal,
      );
      const body = {
        name: form.name,
        yard,
        disposal,
        capacity_carts: number(form.capacity),
        max_route_hours: number(form.hours),
      };
      return dataOf(await api.POST("/orgs/{org_id}/routes", { params: { path }, body }));
    },
    onSuccess: () => {
      setForm(EMPTY);
      setPicked(NONE_PICKED);
      setLookedUp(NONE_LOOKED_UP);
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

  function site(key: SiteKey) {
    return {
      orgId,
      text: form[key],
      lookedUp: lookedUp[key],
      picked: picked[key],
      onText: (text: string) => {
        setForm({ ...form, [key]: text });
        setPicked({ ...picked, [key]: null });
      },
      onLookUp: () => setLookedUp({ ...lookedUp, [key]: asked(form[key]) }),
      onPick: (index: number) => setPicked({ ...picked, [key]: index }),
    };
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    // Enter sends the form without leaving the field: show what each site was found as.
    setLookedUp({ yard: asked(form.yard), disposal: asked(form.disposal) });
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
        <SiteField label="Yard address" {...site("yard")} />
        <SiteField label="Disposal site address" {...site("disposal")} />
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
        {create.isError && (
          <p className="error" role="alert">
            {create.error.message}
          </p>
        )}
      </form>
    </section>
  );
}
