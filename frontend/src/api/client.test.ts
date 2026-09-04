import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelCommitJob,
  commitJobStatus,
  deleteManagedProfile,
  downloadAsFile,
  gapscanConfig,
  gapscanConfigWrite,
  gapscanExportCsv,
  gapscanResults,
  gapscanRun,
  generateFromMetadata,
  generateUpload,
  listAllProfiles,
  listCommitJobs,
  prepareUploadCommit,
  prepareUploadPreview,
  previewGenerate,
  proposeReleaseName,
  sendToTracker,
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

describe("prepareUploadPreview / prepareUploadCommit", () => {
  it("preview envoie local_paths et profile, renvoie la liste de groupes", async () => {
    const groups = [
      {
        release_name: "Movie.2020.1080p.x264-TEAM",
        files: [{ source_path: "/a.mkv", staged_name: "Movie.2020.1080p.x264-TEAM.mkv" }],
        warnings: [],
        blocked: false,
      },
    ];
    vi.mocked(fetch).mockResolvedValue(jsonResponse(groups));

    const result = await prepareUploadPreview(["/a.mkv"]);

    expect(result).toEqual(groups);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/preview");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      local_paths: ["/a.mkv"],
      profile: "c411",
      title_override: undefined,
    });
  });

  it("preview envoie title_override quand fourni", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));

    await prepareUploadPreview(["/a.mkv"], "c411", "Un Gars, Une Fille");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      local_paths: ["/a.mkv"],
      profile: "c411",
      title_override: "Un Gars, Une Fille",
    });
  });

  it("commit envoie release_name/files/profile, renvoie un job_id", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ job_id: "abc123" }));

    const files = [{ source_path: "/a.mkv", staged_name: "Movie.2020.1080p.x264-TEAM.mkv" }];
    const result = await prepareUploadCommit("Movie.2020.1080p.x264-TEAM", files);

    expect(result).toEqual({ job_id: "abc123" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/commit");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      release_name: "Movie.2020.1080p.x264-TEAM",
      files,
      profile: "c411",
    });
  });
});

describe("commitJobStatus / listCommitJobs / cancelCommitJob", () => {
  const JOB = {
    job_id: "abc123", release_name: "Movie.2020.1080p.x264-TEAM", state: "staging", percent: 42,
    started_at: 1000, finished_at: null, error: null, result: null,
  };

  it("commitJobStatus GET le bon chemin, renvoie la tache", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(JOB));

    const result = await commitJobStatus("abc123");

    expect(result).toEqual(JOB);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs/abc123");
  });

  it("listCommitJobs renvoie la liste complete", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([JOB]));

    const result = await listCommitJobs();

    expect(result).toEqual([JOB]);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs");
  });

  it("cancelCommitJob POST vers /cancel", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "cancelling" }));

    const result = await cancelCommitJob("abc123");

    expect(result).toEqual({ status: "cancelling" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs/abc123/cancel");
    expect((init as RequestInit).method).toBe("POST");
  });
});

describe("sendToTracker", () => {
  it("POST le bon corps et renvoie le resultat", async () => {
    const sendResult = { draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(sendResult));

    const result = await sendToTracker({
      releaseName: "Movie.2020.BluRay-TEAM",
      stagedPath: "/staging/Movie.2020.BluRay-TEAM.mkv",
      torrentPath: "/staging/Movie.2020.BluRay-TEAM.torrent",
      nfoPath: "/staging/Movie.2020.BluRay-TEAM.nfo",
      profile: "c411",
      mediaType: "movie",
      radarrMovieId: 42,
      tmdbId: 603,
    });

    expect(result).toEqual(sendResult);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/send");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.release_name).toBe("Movie.2020.BluRay-TEAM");
    expect(body.radarr_movie_id).toBe(42);
    expect(body.tmdb_id).toBe(603);
  });

  it("envoie draft_id quand fourni (mise a jour)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null }),
    );

    await sendToTracker({
      releaseName: "X", stagedPath: "/x", torrentPath: "/x.torrent", nfoPath: "/x.nfo",
      profile: "c411", mediaType: "movie", draftId: 555,
    });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.draft_id).toBe(555);
  });
});

describe("gapscanResults / gapscanExportCsv", () => {
  it("envoie tous les filtres et la pagination, renvoie {items, total}", async () => {
    const page = { items: [], total: 42 };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page));

    const result = await gapscanResults({
      status: "absent", mediaType: "movie", genre: "anime", page: 2, pageSize: 25,
    });

    expect(result).toEqual(page);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("status=absent");
    expect(url).toContain("media_type=movie");
    expect(url).toContain("genre=anime");
    expect(url).toContain("page=2");
    expect(url).toContain("page_size=25");
  });

  it("gapscanResults sans options utilise page=1/page_size=50 par defaut", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0 }));

    await gapscanResults();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("page=1");
    expect(url).toContain("page_size=50");
  });

  it("gapscanExportCsv envoie les filtres media_type/genre", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("a,b\n", { status: 200 }));

    await gapscanExportCsv({ mediaType: "series", genre: "documentaire" });

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("media_type=series");
    expect(url).toContain("genre=documentaire");
  });

  it("gapscanResults passe le parametre profile quand fourni", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0 }));

    await gapscanResults({ profile: "ygg" });

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("profile=ygg");
  });

  it("gapscanExportCsv passe le parametre profile quand fourni", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("a,b\n", { status: 200 }));

    await gapscanExportCsv({ profile: "ygg" });

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("profile=ygg");
  });
});

describe("gapscanConfig / gapscanConfigWrite / gapscanRun", () => {
  it("gapscanConfig sans argument n'ajoute pas de parametre profile", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ profile: "c411", tracker_configured: true }));

    await gapscanConfig();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).not.toContain("profile=");
  });

  it("gapscanConfig passe le profil demande en parametre", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ profile: "ygg", tracker_configured: false }));

    await gapscanConfig("ygg");

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("profile=ygg");
  });

  it("gapscanConfigWrite envoie les champs tracker_* et le profil dans le corps", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ profile: "c411", tracker_configured: true }));

    await gapscanConfigWrite({ tracker_api_key: "k", tracker_base_url: "https://c411.org" }, "c411");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.tracker_api_key).toBe("k");
    expect(body.tracker_base_url).toBe("https://c411.org");
    expect(body.profile).toBe("c411");
  });

  it("gapscanConfigWrite utilise le profil c411 par defaut", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ profile: "c411", tracker_configured: true }));

    await gapscanConfigWrite({ tracker_api_key: "k" });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.profile).toBe("c411");
  });

  it("gapscanRun n'ajoute pas de parametre profile pour le defaut c411", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "started" }));

    await gapscanRun();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).not.toContain("profile=");
  });

  it("gapscanRun passe le profil demande en parametre", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "started" }));

    await gapscanRun(false, undefined, "ygg");

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("profile=ygg");
  });
});
