import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { LoginRoute } from "./routes/login";
import { ConsentRoute } from "./routes/consent";

// Nothing here is worth refetching in the background: a challenge is single-use
// and short-lived, and a stale re-read would replace a form the user is filling.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: Infinity } },
});

const router = createBrowserRouter([
  { path: "/auth/login", element: <LoginRoute /> },
  { path: "/auth/consent", element: <ConsentRoute /> },
  { path: "*", element: <Navigate to="/auth/login" replace /> },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
