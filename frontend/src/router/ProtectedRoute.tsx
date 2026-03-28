import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSessionStore } from "@/stores/sessionStore";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const location = useLocation();
  const apiKey = useSessionStore((state) => state.apiKey);

  if (!apiKey.trim()) {
    const target = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/access?redirect=${encodeURIComponent(target || "/")}`} replace />;
  }

  return <>{children}</>;
}
