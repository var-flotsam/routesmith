import { useQuery } from "@tanstack/react-query";
import { Route, Routes } from "react-router";

import { api, ApiError, dataOf } from "./api/client";
import { Organizations } from "./pages/Organizations";
import { SignIn } from "./pages/SignIn";

/** Who is signed in; a 401 means nobody, which is not an error. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return dataOf(await api.GET("/me"));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
}

export function App() {
  const me = useMe();
  if (me.isPending) return <p className="status">Loading…</p>;
  if (me.isError) return <p className="status error">{me.error.message}</p>;
  if (me.data === null) return <SignIn />;
  return (
    <div className="shell">
      <header>
        <strong>Starboard Routing</strong>
        <span>{me.data.email}</span>
      </header>
      <main>
        <Routes>
          <Route path="*" element={<Organizations me={me.data} />} />
        </Routes>
      </main>
    </div>
  );
}
