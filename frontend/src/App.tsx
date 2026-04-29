import { Navigate, useRoutes } from "react-router-dom";
import { AppShell } from "@/layout/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { SearchPage } from "@/pages/SearchPage";
import { AccessPage } from "@/pages/AccessPage";
import { ProtectedRoute } from "@/router/ProtectedRoute";

export default function App() {
  return useRoutes([
    {
      path: "/access",
      element: <AccessPage />,
    },
    {
      path: "/",
      element: (
        <ProtectedRoute>
          <AppShell />
        </ProtectedRoute>
      ),
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "search", element: <SearchPage /> },
        { path: "*", element: <Navigate to="/" replace /> },
      ],
    },
  ]);
}
