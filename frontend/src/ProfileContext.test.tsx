import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/client", () => ({
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
}));

import { listAllProfiles, readManagedProfile } from "./api/client";
import { ProfileProvider, useProfile } from "./ProfileContext";

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"], ygg: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
});

function wrapper({ children }: { children: ReactNode }) {
  return <ProfileProvider>{children}</ProfileProvider>;
}

describe("useProfile", () => {
  it("defaults to c411 when nothing was previously chosen", async () => {
    const { result } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.displayName).toBe("C411"));
    expect(result.current.profile).toBe("c411");
  });

  it("loads the profile list", async () => {
    const { result } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.profiles).toEqual({ c411: ["video"], ygg: ["video"] }));
  });

  it("falls back to the profile name when display_name is not declared", async () => {
    vi.mocked(readManagedProfile).mockResolvedValue({ name: "ygg", rules: {}, templates: {} });
    const { result } = renderHook(() => useProfile(), { wrapper });
    act(() => result.current.setProfile("ygg"));
    await waitFor(() => expect(result.current.displayName).toBe("ygg"));
  });

  it("persists the chosen profile across remounts (localStorage)", async () => {
    const { result, unmount } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.profile).toBe("c411"));
    act(() => result.current.setProfile("ygg"));
    unmount();
    const { result: result2 } = renderHook(() => useProfile(), { wrapper });
    expect(result2.current.profile).toBe("ygg");
  });

  it("throws a clear error when used outside the provider", () => {
    expect(() => renderHook(() => useProfile())).toThrow(/ProfileProvider/);
  });
});
