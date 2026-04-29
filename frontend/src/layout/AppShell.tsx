import { useEffect, useMemo } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "@/lib/api";
import { useSessionStore } from "@/stores/sessionStore";

const navItems = [
  { to: "/", label: "仪表盘" },
  { to: "/search", label: "记忆检索" },
];

export function AppShell() {
  const location = useLocation();
  const { apiKey, hydrate, connectionState, setConnectionState, endpoint } = useSessionStore();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!apiKey) {
      setConnectionState("idle");
      return;
    }
    let cancelled = false;
    void api
      .health()
      .then(() => {
        if (!cancelled) setConnectionState("connected");
      })
      .catch(() => {
        if (!cancelled) setConnectionState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [apiKey, location.pathname, setConnectionState]);

  const connectionLabel = useMemo(() => {
    if (connectionState === "connected") return "已连接";
    if (connectionState === "error") return "连接失败";
    return "等待配置";
  }, [connectionState]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">AM</div>
          <div>
            <p className="brand-overline">automem</p>
            <h1 className="brand-title">共享记忆管理</h1>
          </div>
        </div>
        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            >
              <span className="nav-item-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="main-shell">
        <header className="main-header">
          <div>
            <h2 className="page-title">面向运营的 automem 控制台</h2>
          </div>
          <div className="header-actions">
            <span className={`status-badge ${connectionState}`}>{connectionLabel}</span>
            <span className="endpoint-pill">{endpoint || "-"}</span>
          </div>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
