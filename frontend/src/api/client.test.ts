import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteManagedProfile,
  downloadAsFile,
  generateFromMetadata,
  generateUpload,
  listAllProfiles,
  previewGenerate,
  proposeReleaseName,
  writeManagedProfile,
} from "./client";
import { ApiError } from "./types";

function jsonResponse(body: unknown, init: ResponseInit & { headers?: HeadersInit } = {}): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  return new Response(JSON.stringify(body), { status: 200, ...init, headers });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => vi.unstubAllGlobals());

describe("request() (via listAllProfiles)", () => {
  it("GETs with credentials included and parses JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ c411: ["video", "audio"] }));

    const result = await listAllProfiles();

    expect(result).toEqual({ c411: ["video", "audio"] });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/profiles");
    expect((init as RequestInit).credentials).toBe("include");
  });

  it("throws ApiError with the server detail on a non-ok JSON response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Profil inconnu." }, { status: 400 }));

    await expect(listAllProfiles()).rejects.toMatchObject(
      new ApiError(400, "Profil inconnu."),
    );
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("not json", { status: 500, statusText: "Internal Server Error" }),
    );

    await expect(listAllProfiles()).rejects.toMatchObject(new ApiError(500, "Internal Server Error"));
  });

  it("wraps a network failure in ApiError(0, ...)", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("network error"));

    await expect(listAllProfiles()).rejects.toBeInstanceOf(ApiError);
    await expect(listAllProfiles()).rejects.toMatchObject({ status: 0 });
  });

  it("returns text for a non-JSON content-type", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("Films & Videos\n...", { status: 200, headers: { "content-type": "text/plain" } }),
    );

    const result = await listAllProfiles();
    expect(result).toBe("Films & Videos\n...");
  });
});

describe("writeManagedProfile / deleteManagedProfile", () => {
  it("PUTs rules+templates as JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));

    await writeManagedProfile("mon_tracker", { game: { filename_template: "{title}.nfo" } }, { game: "x" });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/profiles/store/mon_tracker");
    const request = init as RequestInit;
    expect(request.method).toBe("PUT");
    expect(JSON.parse(request.body as string)).toEqual({
      rules: { game: { filename_template: "{title}.nfo" } },
      templates: { game: "x" },
    });
  });

  it("URL-encodes the profile name", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));

    await deleteManagedProfile("un tracker/etrange");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/profiles/store/un%20tracker%2Fetrange");
    expect((init as RequestInit).method).toBe("DELETE");
  });
});

describe("proposeReleaseName", () => {
  it("maps titleHints to title_hints in the request body", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ name: "X.S01-TEAM", fields: {}, warnings: [] }));

    await proposeReleaseName({
      profile: "c411",
      category: "video",
      filenames: ["a.mkv"],
      titleHints: ["Some Title", null],
    });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      profile: "c411",
      category: "video",
      filenames: ["a.mkv"],
      title_hints: ["Some Title", null],
    });
  });
});

describe("previewGenerate", () => {
  it("parses X-Nfogen-Warnings and returns filename: null", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("General\n...", {
        status: 200,
        headers: { "X-Nfogen-Warnings": "langue manquante | equipe absente" },
      }),
    );

    const result = await previewGenerate("c411", "video", { release_name: "x" });

    expect(result).toEqual({
      nfo: "General\n...",
      warnings: ["langue manquante", "equipe absente"],
      filename: null,
    });
  });

  it("throws ApiError on failure, warnings header still parsed first", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: "release_name non conforme." }, { status: 400 }),
    );

    await expect(previewGenerate("c411", "video", {})).rejects.toMatchObject(
      new ApiError(400, "release_name non conforme."),
    );
  });
});

describe("generateFromMetadata / generateUpload", () => {
  it("extracts the filename from Content-Disposition", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("General\n...", {
        status: 200,
        headers: { "content-disposition": 'attachment; filename="Show.S01.nfo"' },
      }),
    );

    const result = await generateFromMetadata({ profile: "c411", category: "video", data: {} });
    expect(result.filename).toBe("Show.S01.nfo");
  });

  it("returns filename: null when Content-Disposition is absent", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("General\n...", { status: 200 }));

    const result = await generateFromMetadata({ profile: "c411", category: "video", data: {} });
    expect(result.filename).toBeNull();
  });

  it("builds a multipart form with profile/category/data/files", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("General\n...", { status: 200 }));
    const file = new File(["binary"], "film.mkv", { type: "video/x-matroska" });

    await generateUpload({ profile: "c411", category: "video", data: { x: 1 }, files: [file] });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/generate?download=1");
    const form = (init as RequestInit).body as FormData;
    expect(form.get("profile")).toBe("c411");
    expect(form.get("category")).toBe("video");
    expect(form.get("data")).toBe(JSON.stringify({ x: 1 }));
    expect(form.get("files")).toBe(file);
  });

  it("omits category from the form when absent", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("x", { status: 200 }));

    await generateUpload({ profile: "c411", data: {}, files: [] });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const form = (init as RequestInit).body as FormData;
    expect(form.has("category")).toBe(false);
  });
});

describe("downloadAsFile", () => {
  it("creates a temporary anchor, clicks it, and revokes the object URL", () => {
    const createUrl = vi.fn(() => "blob:fake-url");
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    downloadAsFile("General\n...", "film.nfo");

    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalledWith("blob:fake-url");

    clickSpy.mockRestore();
  });
});
