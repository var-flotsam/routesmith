import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, dataOf } from "../api/client";

/** Ask for a sign-in link by email. The API answers the same for any address. */
export function SignIn() {
  const [email, setEmail] = useState("");
  const send = useMutation({
    mutationFn: async (address: string) =>
      dataOf(await api.POST("/auth/magic-link", { body: { email: address } })),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    send.mutate(email);
  }

  if (send.isSuccess) {
    return (
      <main className="narrow">
        <h1>Check your email</h1>
        <p>We sent a sign-in link to {email}. It works once, for 15 minutes.</p>
      </main>
    );
  }
  return (
    <main className="narrow">
      <h1>Sign in to Starboard Routing</h1>
      <form onSubmit={submit}>
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <button type="submit" disabled={send.isPending}>
          Email me a sign-in link
        </button>
        {send.isError && <p className="error">{send.error.message}</p>}
      </form>
    </main>
  );
}
