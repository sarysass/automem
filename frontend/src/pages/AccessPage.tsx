import { FormEvent, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSessionStore } from "@/stores/sessionStore";

function resolveRedirect(search: string) {
  const params = new URLSearchParams(search);
  const target = params.get("redirect");
  if (!target || !target.startsWith("/")) {
    return "/";
  }
  return target;
}

export function AccessPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { apiKey, setApiKey, hydrate } = useSessionStore();
  const [draftKey, setDraftKey] = useState(apiKey);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (apiKey.trim()) {
      navigate(resolveRedirect(location.search), { replace: true });
    }
  }, [apiKey, location.search, navigate]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setApiKey(draftKey.trim());
  }

  return (
    <main className="access-shell">
      <section className="access-card">
        <div className="access-brand">
          <div className="brand-mark">AM</div>
          <div>
            <p className="brand-overline">automem</p>
            <h1 className="brand-title">共享记忆管理</h1>
          </div>
        </div>

        <div className="access-copy">
          <p className="page-eyebrow">管理入口</p>
          <h2 className="page-title">进入管理台</h2>
          <p className="access-description">
            先输入管理员 Key，再进入内部页面。凭证只保存在当前浏览器会话，不会长久留在本机。
          </p>
        </div>

        <form className="access-form" onSubmit={handleSubmit}>
          <label className="access-label">
            管理 API Key
            <input
              aria-label="管理 API Key"
              type="password"
              value={draftKey}
              onChange={(event) => setDraftKey(event.target.value)}
              placeholder="请输入管理员 Key"
            />
          </label>
          <button type="submit">进入管理台</button>
        </form>
      </section>
    </main>
  );
}
