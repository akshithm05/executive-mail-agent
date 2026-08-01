"use client";

import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";

interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
}

/**
 * Runs an async fetcher on mount (and whenever `deps` changes), exposing
 * loading/error/data state plus a manual `refetch` for post-mutation
 * refreshes. Every dashboard page uses this instead of hand-rolling its own
 * effect, so loading/error/empty handling stays consistent everywhere.
 *
 * Uses `useEffectEvent` (React 19.2) for the "always call the latest `fn`"
 * logic -- the React-blessed replacement for the older manual-ref pattern,
 * and exempt from `react-hooks/set-state-in-effect` because the setState
 * calls live inside the Effect Event, not the Effect body itself.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    isLoading: true,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const generationRef = useRef(0);

  const load = useEffectEvent(() => {
    const generation = ++generationRef.current;
    setState((s) => ({ ...s, isLoading: true, error: null }));
    fn()
      .then((data) => {
        if (generationRef.current === generation) {
          setState({ data, error: null, isLoading: false });
        }
      })
      .catch((error: Error) => {
        if (generationRef.current === generation) {
          setState((s) => ({ ...s, error, isLoading: false }));
        }
      });
  });

  useEffect(() => {
    // Intentional: this is the fetch-on-mount/refetch-on-change entry
    // point every page depends on. `load` sets loading state before
    // resolving `fn()` -- there is no meaningfully different "correct"
    // shape for this without adopting a data-fetching library.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  const refetch = useCallback(() => setReloadToken((t) => t + 1), []);

  return { ...state, refetch };
}
