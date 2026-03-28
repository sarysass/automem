import { DependencyList, useEffect } from "react";

export function useAutoRefresh(refresh: () => Promise<void> | void, deps: DependencyList) {
  useEffect(() => {
    void refresh();
  }, deps);
}
