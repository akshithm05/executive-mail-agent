import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAsync } from "@/hooks/use-async";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsync", () => {
  it("starts in a loading state with no data or error", () => {
    const { result } = renderHook(() => useAsync(() => new Promise<number>(() => {})));
    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("resolves into data and clears the loading state", async () => {
    const fn = vi.fn().mockResolvedValue(42);
    const { result } = renderHook(() => useAsync(fn));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it("captures a thrown error and clears the loading state", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useAsync(fn));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("network down");
    expect(result.current.data).toBeNull();
  });

  it("refetch re-invokes the fetcher and re-enters the loading state", async () => {
    const fn = vi.fn().mockResolvedValue(1);
    const { result } = renderHook(() => useAsync(fn));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fn).toHaveBeenCalledTimes(1);

    fn.mockResolvedValue(2);
    act(() => result.current.refetch());
    await waitFor(() => expect(result.current.data).toBe(2));
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("ignores a stale in-flight response once a newer fetch has started", async () => {
    const first = deferred<number>();
    const second = deferred<number>();
    const fn = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const { result } = renderHook(() => useAsync(fn));
    act(() => result.current.refetch());
    expect(fn).toHaveBeenCalledTimes(2);

    // The second (newer) call resolves first...
    second.resolve(200);
    await waitFor(() => expect(result.current.data).toBe(200));

    // ...then the first (stale) call resolves -- it must not overwrite
    // the newer, already-applied result.
    first.resolve(100);
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.data).toBe(200);
  });
});
