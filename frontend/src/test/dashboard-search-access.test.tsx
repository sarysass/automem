import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import { useSessionStore } from "@/stores/sessionStore";

function mockFetch(payload: unknown) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
}

describe("dashboard, access, and search routes", () => {
  beforeEach(() => {
    sessionStorage.clear();
    useSessionStore.setState({
      apiKey: "",
      connectionState: "idle",
      endpoint: "http://localhost:3000",
    });
    vi.restoreAllMocks();
  });

  it("auto-refreshes dashboard data on entry", async () => {
    sessionStorage.setItem("automem-admin-key", "test-admin");
    useSessionStore.setState({ apiKey: "test-admin" });
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/healthz") {
        return mockFetch({
          ok: true,
          llm_model: "glm-5",
          embed_model: "nomic-embed-text",
          qdrant: "127.0.0.1:6333",
          task_db: "/tmp/tasks.db",
          metrics: { memory_cache: { entries: 7 } },
        });
      }
      if (url === "/v1/metrics") {
        return mockFetch({
          metrics: {
            routes: { long_term: 2, task: 1 },
            events: { memory_route: 3 },
            tasks: { active: 4, archived: 1 },
            memory_cache: { entries: 7 },
          },
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/healthz",
        expect.objectContaining({
          headers: expect.objectContaining({ "X-API-Key": "test-admin" }),
        }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/metrics",
        expect.objectContaining({
          headers: expect.objectContaining({ "X-API-Key": "test-admin" }),
        }),
      );
    });

    expect(await screen.findByText("正常运行")).toBeInTheDocument();
    expect(screen.getByText("活跃任务")).toBeInTheDocument();
  });

  it("shows a dedicated access page when there is no api key", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "进入管理台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进入管理台" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("enters the console from the access page after saving an api key", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/v1/healthz") {
        return mockFetch({
          ok: true,
          llm_model: "glm-5",
          embed_model: "nomic-embed-text",
          qdrant: "127.0.0.1:6333",
          task_db: "/tmp/tasks.db",
          metrics: { memory_cache: { entries: 7 } },
        });
      }
      if (url === "/v1/metrics") {
        return mockFetch({
          metrics: {
            routes: { long_term: 2, task: 1 },
            events: { memory_route: 3 },
            tasks: { active: 4, archived: 1 },
            memory_cache: { entries: 7 },
          },
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/access"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "进入管理台" })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("管理 API Key"), "test-admin");
    await userEvent.click(screen.getByRole("button", { name: "进入管理台" }));

    expect(await screen.findByText("正常运行")).toBeInTheDocument();
    expect(screen.getByText("活跃任务")).toBeInTheDocument();
  });

  it("defaults search page to long_term domain and category dropdowns", async () => {
    sessionStorage.setItem("automem-admin-key", "test-admin");
    useSessionStore.setState({ apiKey: "test-admin" });
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/v1/search") {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({
            query: "我的名字叫什么",
            filters: { domain: "long_term" },
          }),
        );
        return mockFetch({ results: [] });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/search"]}>
        <App />
      </MemoryRouter>,
    );

    await userEvent.clear(screen.getByLabelText("查询词"));
    await userEvent.type(screen.getByLabelText("查询词"), "我的名字叫什么");
    expect(screen.getByLabelText("Domain")).toHaveValue("long_term");
    await userEvent.click(screen.getByRole("button", { name: "查询" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/search",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "X-API-Key": "test-admin" }),
        }),
      );
    });
  });
});
