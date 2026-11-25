import { addEventListener, definePlugin, openFilePicker, FileSelectionType, removeEventListener, toaster } from "@decky/api";
import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Router,
  SliderField,
  ToggleField,
} from "@decky/ui";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { MdAutoAwesome } from "react-icons/md";
import {
  AnrInfo,
  applyPathAll,
  BenchState,
  cancelBenchmark,
  checkUpdates,
  deleteBenchmarkKit,
  getBenchmark,
  getLegacyInfo,
  startBenchmark,
  GameEntry,
  GameStatus,
  getAnrInfo,
  getAutoUpdateAnr,
  setAutoUpdateAnr,
  getUiLanguage,
  getGameStatus,
  getPerformance,
  getUpscaler,
  getOptiSettings,
  setOptiSetting,
  copyProfile,
  resetProfile,
  setRenderQuality,
  setUpscaler,
  UpscalerInfo,
  PerfSession,
  installBundled,
  listGames,
  recommendedLaunchOptions,
  setDxgiFix,
  setOptiscalerCore,
  updateNightlyOptiscaler,
  syncShortcuts,
  listOutdatedGames,
  patchGame,
  readGameLog,
  setActiveVersion,
  setGameSetting,
  setGeneratorMode,
  getLsfgStatus,
  installLsfg,
  importLsfgLibrary,
  refreshFsr4Dlls,
  getFsr4Library,
  importFsr4Libraries,
  extractFsr4Driver,
  Fsr4Library,
  LsfgProfile,
  LsfgStatus,
  unpatchGame,
  updateAllGames,
  updateFromGithub,
  UpdateInfo,
  getNpuSr,
  setNpuSr,
  setNpuSrModel,
  setNpuCapture,
  setNpuSharpness,
  setNpuAa,
  setNpuFg,
  setNpuFgEngine,
  getNpuPackage,
  importNpuPackage,
  installNpuFromGithub,
  importAllInOneBundle,
  findLocalBundle,
  NpuPackage,
  type NpuSrStatus,
} from "./api";
import { registerFocusRoot, withSettingFocus, openMenuWithFocus } from "./focus";
import { t, translateMessage, initializeLanguage, subscribeLanguage, getLanguage } from "./i18n";
import { copyText, getLaunchOptions, setLaunchOptions, getNonSteamShortcuts, getResolutionOverride, setResolutionOverride } from "./steam";

declare const SteamClient: any;

const TITLE = "Decky FrameGen Hub";
const toast = (body: string) => toaster.toast({ title: TITLE, body: translateMessage(body) });
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

const PATH_OPTIONS = ["auto", "coopmat", "packed", "dp4a", "portable", "portable-linalg", "portable-xmx"];
const AUTO_DIR = "__auto__";

const small: React.CSSProperties = { fontSize: "12px", lineHeight: "16px", opacity: 0.8, wordBreak: "break-word" };

let rememberedAppId = "";

// ─── ANR FG package section ──────────────────────────────────────────────────

declare const DeckyBackend: { call: (route: string, ...args: unknown[]) => Promise<unknown> };
const INSTALL_TYPE_UPDATE = 2;

const banner = (color: string): React.CSSProperties => ({
  ...small,
  opacity: 1,
  padding: "8px",
  borderRadius: "6px",
  background: color,
});

function PackageSection({ info, reload }: { info: AnrInfo | null; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [updates, setUpdates] = useState<UpdateInfo | null>(null);
  const [autoAnr, setAutoAnr] = useState(true);
  useEffect(() => { void getAutoUpdateAnr().then((r) => setAutoAnr(r.enabled)).catch(() => {}); }, []);
  const [outdated, setOutdated] = useState<{ appid: string; name: string; version: string }[]>([]);

  const loadUpdates = useCallback(async (force: boolean) => {
    try {
      setUpdates(await checkUpdates(force));
    } catch (e) {
      setUpdates({ status: "error", message: errorText(e) });
    }
    try {
      setOutdated((await listOutdatedGames()).games || []);
    } catch {
      setOutdated([]);
    }
  }, []);

  useEffect(() => void loadUpdates(false), [loadUpdates, info?.version]);
  const [lsfg, setLsfg] = useState<LsfgStatus | null>(null);
  const loadLsfg = useCallback(async () => {
    try { setLsfg(await getLsfgStatus("")); } catch { setLsfg(null); }
  }, []);
  useEffect(() => void loadLsfg(), [loadLsfg]);

  const run = withSettingFocus(async (label: string, fn: () => Promise<{ status: string; message?: string }>) => {
    setBusy(label);
    try {
      const r = await fn();
      toast(r.message || (r.status === "success" ? t("Done.") : t("Failed.")));
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(null);
      await reload();
      await loadUpdates(false);
    }
  });

  const updatePlugin = async () => {
    if (!updates?.plugin_url) return;
    try {
      // Decky shows its own confirmation and reloads the plugin after installing.
      await DeckyBackend.call(
        "utilities/install_plugin",
        updates.plugin_url,
        TITLE,
        updates.plugin_latest,
        updates.plugin_hash || false,
        INSTALL_TYPE_UPDATE
      );
    } catch (e) {
      toast(t("Plugin update failed: {0}", errorText(e)));
    }
  };

  const checkedAt = updates?.checked_at ? new Date(updates.checked_at).toLocaleString(getLanguage() === "ru" ? "ru-RU" : "en-US") : null;

  return (
    <PanelSection title={t("Updates and components")}>
      <PanelSectionRow>
        <ToggleField label={t("Automatically update ANR FG")}
          description={t("Checks every 6 hours, verifies SHA-256, and updates closed games. Running games update after closing. Profiles and generator choice are preserved.")}
          checked={autoAnr} disabled={busy !== null}
          onChange={async (enabled: boolean) => {
            await run("auto-anr", () => setAutoUpdateAnr(enabled));
            setAutoAnr((await getAutoUpdateAnr()).enabled);
          }} />
      </PanelSectionRow>
      {updates?.plugin_update && (
        <>
          <PanelSectionRow>
            <div style={banner("rgba(88,166,255,0.18)")}>
              <b>{TITLE} {updates.plugin_latest}</b> {" "}{t("is out (you have")}{" "}{updates.plugin_current}).
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={updatePlugin}>
              {" "}{t("Update the plugin to")}{" "}{updates.plugin_latest}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      {updates?.xefg_update && (
        <PanelSectionRow>
          <div style={banner("rgba(88,166,255,0.12)")}>
            <b>XeFG {updates.xefg_latest}</b> {" "}{t("is out (the plugin has")}{" "}{updates.xefg_current}{t("). XeFG builds are checked and pinned per plugin release: it arrives with the next plugin update.")}{" "}</div>
        </PanelSectionRow>
      )}

      {updates?.fsr4_update_games && updates.fsr4_update_games.length > 0 && (
        <>
          <PanelSectionRow>
            <div style={banner("rgba(255,216,102,0.12)")}>
              {" "}{t("Proton has a newer FSR 4 DLL (")}{updates.fsr4_latest}{t(") than")}{" "}{updates.fsr4_update_games.join(", ")}.
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => run("fsr4", refreshFsr4Dlls)}>
              {" "}{t("Update the FSR 4 DLL in these games")}{" "}</ButtonItem>
          </PanelSectionRow>
        </>
      )}

      {updates?.anr_update && (
        <PanelSectionRow>
          <div style={banner("rgba(255,216,102,0.18)")}>
            <b>{t("New ANR FG")}{" "}{updates.anr_latest}</b> {" "}{t("is out (you have")}{" "}{info?.version ?? t("not installed")}{t("). Download it below, then update your games.")}{" "}</div>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <Field label={t("ANR FG package")} focusable>
          {info === null ? "…" : info.installed ? info.version : <span style={{ color: "#ffd866" }}>{t("not set up")}</span>}
        </Field>
      </PanelSectionRow>
      {!info?.installed && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy !== null} onClick={() => run("setup", installBundled)}>
            {busy === "setup" ? t("Setting up…") : t("Set up bundled ANR FG")}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== null} onClick={() => run("update", updateFromGithub)}>
          {busy === "update"
            ? t("Downloading…")
            : updates?.anr_update
            ? t("Download ANR FG {0}", updates.anr_latest)
            : t("Get the newest release")}
        </ButtonItem>
      </PanelSectionRow>

      {outdated.length > 0 && (
        <>
          <PanelSectionRow>
            <div style={banner("rgba(255,216,102,0.12)")}>
              {outdated.length === 1 ? t("1 game uses") : t("{0} games use", outdated.length)} {" "}{t("an older ANR FG:")}{" "}
              {outdated.map((g) => `${g.name} (${g.version})`).join(", ")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => run("games", updateAllGames)}>
              {busy === "games" ? t("Updating games…") : t("Update {0} to {1}", outdated.length === 1 ? t("it") : t("all"), info?.version)}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      <PanelSectionRow>
        <Field label="Lossless Scaling (lsfg-vk)" focusable>
          {lsfg === null ? "…" : lsfg.installed ? lsfg.version : t("not installed")}
        </Field>
      </PanelSectionRow>
      {lsfg && lsfg.installed && lsfg.dll_state !== "ok" && (
        <PanelSectionRow>
          <div style={{ ...small, color: "#ffd866" }}>
            {lsfg.dll_state === "wrong_branch"
              ? t("Lossless Scaling is on its default branch, which lacks what lsfg-vk 2 needs. In Steam: Lossless Scaling → Properties → Betas → lsfg-vk.")
              : t("lsfg-vk needs your Lossless Scaling: install it from Steam and pick the beta branch \"lsfg-vk\" (Properties → Betas).")}
            {" "}{t("Or import your own lsfg-vk.dll or ZIP below.")}{" "}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== null}
          description={lsfg?.dll_state === "ok"
            ? lsfg.dll_source === "imported" ? t("Using your imported lsfg-vk.dll. Import a newer DLL or ZIP to update it.")
              : t("Using lsfg-vk.dll from your Steam library. You can also import your own file.")
            : t("Select lsfg-vk.dll from your own Lossless Scaling copy, or a ZIP containing it. Lossless.dll from the default branch is not compatible.")}
          onClick={async () => {
            let path: string;
            try {
              const file = await openFilePicker(FileSelectionType.FILE, lsfg?.home || "/home", true, true, undefined, ["dll", "zip"], false, false);
              path = file.realpath || file.path;
            } catch { return; }
            await run("lsfg-import", () => importLsfgLibrary(path));
            await loadLsfg();
          }}>
          {busy === "lsfg-import" ? t("Importing library…") : t("Import Lossless Scaling library (DLL / ZIP)")}
        </ButtonItem>
      </PanelSectionRow>
      {(!lsfg?.installed || updates?.lsfg_update) && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy !== null}
            onClick={async () => { await run("lsfg", installLsfg); await loadLsfg(); }}>
            {busy === "lsfg" ? t("Installing lsfg-vk…")
              : lsfg?.installed ? t("Update lsfg-vk to {0}", updates?.lsfg_latest) : t("Install lsfg-vk (frame generation for any game)")}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {info?.versions && info.versions.length > 1 && (
        <PanelSectionRow>
          <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
            label={t("Version for new patches")}
            selectedOption={info.version}
            rgOptions={[...info.versions].reverse().map((v) => ({ data: v, label: v }))}
            onChange={(o) => run("version", () => setActiveVersion(String(o.data)))}
          />
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== null} onClick={() => run("check", async () => {
          const r = await checkUpdates(true);
          setUpdates(r);
          if (r.status !== "success") return r;
          const parts = [
            r.anr_update ? t("ANR FG {0} is out", r.anr_latest) : t("ANR FG: {0} is the newest", r.anr_latest ?? "?"),
            r.plugin_update ? t("plugin {0} is out", r.plugin_latest) : t("plugin is up to date"),
          ];
          return { status: "success", message: parts.join("; ") + (r.errors?.length ? ` (${r.errors.join("; ")})` : "") };
        })}>
          {busy === "check" ? t("Checking…") : t("Check for updates")}
        </ButtonItem>
      </PanelSectionRow>
      {checkedAt && (
        <PanelSectionRow>
          <div style={small}>
            {" "}{t("Checked")}{" "}{checkedAt}{t("; automatic check every 6 hours.")}{" "}{updates?.errors?.length ? t(" Last error: {0}", updates.errors[0]) : ""}
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// ─── Lossless Scaling (lsfg-vk) per-game controls ───────────────────────────

function LsfgControls({ profile, busy, onChange }: {
  profile: LsfgProfile | null; busy: boolean; onChange: (p: Partial<LsfgProfile>) => void;
}) {
  const m = profile?.multiplier ?? 2;
  const flow = Math.round((profile?.flow_scale ?? 1.0) * 100);
  return (
    <>
      <PanelSectionRow>
        <div style={{ ...small, opacity: 1, fontWeight: 700 }}>{t("Lossless Scaling settings")}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label={t("Performance mode")} description={t("Lighter model: cheaper on the GPU, a little less accurate.")}
          checked={Boolean(profile?.performance_mode)} disabled={busy}
          onChange={(on: boolean) => onChange({ performance_mode: on })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label={t("Lossless multiplier")} description={t("{0}X: {1} generated frame(s) per real frame.", m, m - 1)}
          value={m} min={2} max={4} step={1} showValue notchTicksVisible disabled={busy}
          onChange={(v: number) => onChange({ multiplier: v })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label={t("Flow scale")} description={t("Lower = faster, softer motion estimation (recommended 50–75% on handhelds).")}
          value={flow} min={25} max={100} step={5} showValue valueSuffix="%" disabled={busy}
          onChange={(v: number) => onChange({ flow_scale: v / 100 })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={small}>
          {" "}{t("Turn the game's own frame generation off. Applies at the game's next start")}{profile?.active_in?.length ? ` (${profile.active_in.join(", ")})` : ""}.
        </div>
      </PanelSectionRow>
    </>
  );
}

// ─── Game section ────────────────────────────────────────────────────────────

function GameSection({ info }: { info: AnrInfo | null }) {
  const [games, setGames] = useState<GameEntry[]>([]);
  const [loadingGames, setLoadingGames] = useState(true);
  const [appid, setAppid] = useState<string>(() => rememberedAppId);
  const [status, setStatus] = useState<GameStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [busy, setBusy] = useState<"patch" | "unpatch" | "generator" | "compat" | null>(null);
  const [dirChoice, setDirChoice] = useState<string>(AUTO_DIR);
  const [log, setLog] = useState<string>("");
  const [perf, setPerf] = useState<{
    sessions: PerfSession[];
    summary?: { path: string; sessions: number; total_ms: number; real_fps: number | null }[];
  } | null>(null);
  const [launchOptions, setLaunchOptionsState] = useState<string>("");
  const [upscaler, setUpscalerInfo] = useState<UpscalerInfo | null>(null);
  const [opti, setOpti] = useState<Record<string, string>>({});
  const [copyFrom, setCopyFrom] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showLaunchDetails, setShowLaunchDetails] = useState(false);
  const generatorQueue = useRef<Promise<unknown>>(Promise.resolve());
  const generatorPending = useRef(0);
  const [generatorSaving, setGeneratorSaving] = useState(false);
  const lsfgDraft = useRef<Partial<LsfgProfile> | null>(null);

  const loadGames = useCallback(async () => {
    setLoadingGames(true);
    try {
      await syncShortcuts(await getNonSteamShortcuts());
      const r = await listGames();
      const list = (r.games || []).filter((g) => g.installed);
      setGames(list);
      setAppid((current) => {
        const running = String(Router.MainRunningApp?.appid ?? "");
        const pick =
          [current, running].find((id) => id && list.some((g) => g.appid === id)) || list[0]?.appid || "";
        rememberedAppId = pick;
        return pick;
      });
    } catch (e) {
      toast(errorText(e));
    } finally {
      setLoadingGames(false);
    }
  }, []);

  const selectedApp = useRef(appid);
  selectedApp.current = appid;
  const statusRequest = useRef(0);
  // Fetch independent views together and commit once. Silent refreshes keep the current controls mounted.
  const loadStatus = useCallback(async (id: string, silent = false) => {
    const request = ++statusRequest.current;
    if (!id) return setStatus(null);
    if (!silent) setLoadingStatus(true);
    const views = await Promise.allSettled([
      getGameStatus(id), getUpscaler(id), getOptiSettings(id),
      silent ? Promise.resolve(undefined) : getLaunchOptions(Number(id)),
    ]);
    if (request !== statusRequest.current || selectedApp.current !== id) return;
    const [gameView, upscaleView, optiView, launchView] = views;
    if (gameView.status === "fulfilled" && gameView.value.status === "success") setStatus(gameView.value);
    else if (!silent) setStatus({ status: "error", message: gameView.status === "rejected" ? errorText(gameView.reason) : gameView.value.message });
    // An unpatched game has no OptiScaler upscaler: drop the previous game state instead of keeping it.
    if (upscaleView.status === "fulfilled" && upscaleView.value.status === "success") setUpscalerInfo(upscaleView.value);
    else setUpscalerInfo(null);
    if (optiView.status === "fulfilled" && optiView.value.status === "success") setOpti(optiView.value.settings);
    if (launchView.status === "fulfilled" && launchView.value !== undefined) setLaunchOptionsState(launchView.value);
    setLoadingStatus(false);
  }, []);

  useEffect(() => void loadGames(), [loadGames]);
  useEffect(() => {
    setDirChoice(AUTO_DIR);
    lsfgDraft.current = null;
    setLog("");
    setPerf(null);
    void loadStatus(appid);
  }, [appid, loadStatus]);

  const game = useMemo(() => games.find((g) => g.appid === appid) ?? null, [games, appid]);

  const doPatch = async () => {
    if (!game) return;
    setBusy("patch");
    try {
      const current = await getLaunchOptions(Number(appid));
      const r = await patchGame(appid, current, dirChoice === AUTO_DIR ? "" : dirChoice);
      if (r.status !== "success") throw new Error(r.message || t("Patch failed."));
      if (r.launch_options !== undefined && r.launch_options !== current) {
        setLaunchOptions(Number(appid), r.launch_options);
      }
      toast(r.message || t("Patched."));
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(null);
      await loadStatus(appid);
      await loadGames();
    }
  };

  const doUnpatch = async () => {
    if (!game) return;
    setBusy("unpatch");
    try {
      const current = await getLaunchOptions(Number(appid));
      const r = await unpatchGame(appid, current);
      if (r.status !== "success") throw new Error(r.message || t("Unpatch failed."));
      if (r.launch_options !== undefined && r.launch_options !== current) {
        setLaunchOptions(Number(appid), r.launch_options);
      }
      if (npu?.enabled) {  // a restored game also runs without the NPU upscaler
        const now = await getLaunchOptions(Number(appid));
        const n = await setNpuSr(appid, false, now);
        if (n.status === "success" && n.launch_options !== undefined) setLaunchOptions(Number(appid), n.launch_options);
        void loadNpu(appid);
      }
      toast(r.message || t("Unpatched."));
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(null);
      await loadStatus(appid);
      await loadGames();
    }
  };

  const syncLaunchMode = async (id: string) => {
    const current = await getLaunchOptions(Number(id));
    const r = await recommendedLaunchOptions(id, current);
    if (r.status === "success" && r.launch_options !== undefined && r.launch_options !== current) {
      setLaunchOptions(Number(id), r.launch_options);
    }
    return r;
  };

  const changeOptiscalerCore = withSettingFocus(async (core: string) => {
    if (busy !== null) return;
    const id = appid;
    setBusy("compat");
    try {
      const current = await getLaunchOptions(Number(id));
      const result = await setOptiscalerCore(id, core, current);
      if (result.status === "success" && result.launch_options !== undefined) setLaunchOptions(Number(id), result.launch_options);
      toast(result.message || result.status);
    } catch (error) { toast(errorText(error)); }
    finally { setBusy(null); await loadStatus(id, true); }
  });

  const updateOptiscaler = withSettingFocus(async () => {
    if (busy !== null) return;
    const id = appid;
    setBusy("compat");
    try {
      const result = await updateNightlyOptiscaler(id);
      toast(result.message || result.status);
    } catch (error) { toast(errorText(error)); }
    finally { setBusy(null); await loadStatus(id, true); }
  });

  const [npu, setNpu] = useState<NpuSrStatus | null>(null);
  const [resOverride, setResOverride] = useState<string>("");
  const loadNpu = useCallback(async (id: string) => {
    if (!id) { setResOverride(""); return setNpu(null); }
    void getResolutionOverride(Number(id)).then((res) => {
      if (selectedApp.current === id) setResOverride(res || "");
    });
    try {
      const r = await getNpuSr(id);
      if (selectedApp.current === id) setNpu(r.status === "success" ? r : null);
      // Games set up before the layer became opt-in lack NPU_SR_ENABLE=1: add it once, silently.
      // Best effort: a failure here must never hide the NPU controls.
      if (r.status === "success" && r.enabled && r.available) {
        try {
          const current = await getLaunchOptions(Number(id));
          // Empty means Steam did not answer (or nothing to heal): never rewrite options from an empty read.
          if (typeof current === "string" && current.trim() && !/(^|\s)NPU_SR_ENABLE=1(\s|$)/.test(current)) {
            const n = await setNpuSr(id, true, current);
            if (n.status === "success" && n.launch_options !== undefined) setLaunchOptions(Number(id), n.launch_options);
          }
        } catch (e) {
          console.warn("[FrameGen Hub] NPU launch option heal failed", e);
        }
      }
    } catch {
      if (selectedApp.current === id) setNpu(null);
    }
  }, []);
  useEffect(() => {
    void loadNpu(appid);
    const timer = setInterval(() => void loadNpu(appid), 3000);
    return () => clearInterval(timer);
  }, [appid, loadNpu]);
  const changeNpuSharpness = async (v: number) => {
    setNpu((cur) => cur ? { ...cur, sharpness: v } : cur);
    const r = await setNpuSharpness(v);
    if (r.status !== "success") toast(r.message || r.status);
  };
  const changeNpuAa = async (v: number) => {
    setNpu((cur) => cur ? { ...cur, aa: v } : cur);
    const r = await setNpuAa(v);
    if (r.status !== "success") toast(r.message || r.status);
  };
  const changeNpuFg = async (v: number) => {
    setNpu((cur) => cur ? { ...cur, fg: v } : cur);
    const r = await setNpuFg(v);
    if (r.status !== "success") toast(r.message || r.status);
  };
  const changeNpuFgEngine = withSettingFocus(async (engine: string) => {
    setNpu((cur) => cur ? { ...cur, fg_engine: engine } : cur);
    const r = await setNpuFgEngine(engine);
    if (r.status !== "success") toast(r.message || r.status);
  });
  const changeResOverride = withSettingFocus(async (res: string) => {
    setResOverride(res);
    const ok = setResolutionOverride(Number(appid), res);
    if (!ok) {
      toast(t("Steam resolution override is unavailable in this session; change resolution in Steam Properties or in-game."));
    } else if (status?.running) {
      toast(t("Saved for next launch. To switch right now without restarting, change resolution in the game's graphics menu — NPU adapts live."));
    } else {
      toast(res ? t("Render resolution set to {0}.", res) : t("Render resolution reset to Default."));
    }
  });
  useEffect(() => {
    if (!appid || !npu?.enabled || !status?.running) return;
    const timer = window.setInterval(() => {
      void getNpuSr(appid).then((r) => {
        if (selectedApp.current === appid && r.status === "success") setNpu(r);
      }).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [appid, npu?.enabled, status?.running]);
  const toggleNpuHybrid = withSettingFocus(async (on: boolean) => {
    const current = await getLaunchOptions(Number(appid));
    const r = await setNpuSr(appid, on, current);
    if (r.status === "success" && r.launch_options !== undefined) setLaunchOptions(Number(appid), r.launch_options);
    toast(r.message || r.status);
    await loadNpu(appid);
  });
  const changeNpuCapture = withSettingFocus(async (on: boolean) => {
    const r = await setNpuCapture(on);
    toast(r.message || r.status);
    await loadNpu(appid);
  });
  const changeNpuModel = withSettingFocus(async (model: string) => {
    const r = await setNpuSrModel(model);
    toast(r.message || r.status);
    await loadNpu(appid);
  });
  const npuLine = !npu?.enabled ? "" : npu.live
    ? t("NPU {0} ms · {1} → {2} · {3}", (npu.live.npu_ms ?? 0).toFixed(1), npu.live.in ?? "?", npu.live.out ?? "?",
        npu.live.connected ? t("NPU active") : t("GPU fallback (bilinear)"))
    : t("Service: {0} · model: {1}", npu.service ?? "?", npu.model ?? t("default"));

  const changeDxgiFix = withSettingFocus(async (enabled: boolean) => {
    const current = await getLaunchOptions(Number(appid));
    const result = await setDxgiFix(appid, enabled, current);
    if (result.status === "success" && result.launch_options !== undefined) setLaunchOptions(Number(appid), result.launch_options);
    toast(result.message || result.status);
    await loadStatus(appid, true);
  });

  const changeGenerator = withSettingFocus(async (choice: string, lsfg?: Partial<LsfgProfile>) => {
    if (busy !== null) return;
    const requestApp = appid;
    setLog("");
    setPerf(null);
    const cur = { ...(lsfgDraft.current || status?.lsfg || { multiplier: 2, flow_scale: 1.0, performance_mode: false }), ...(lsfg || {}) };
    if (choice === "lsfg") {
      lsfgDraft.current = cur;
      if (status?.lsfg) setStatus((previous) => previous ? { ...previous, lsfg: { ...previous.lsfg, ...cur } as LsfgProfile } : previous);
    }
    generatorPending.current++;
    setGeneratorSaving(true);
    const saved = generatorQueue.current.catch(() => {}).then(() =>
      setGeneratorMode(requestApp, choice, cur.multiplier ?? 2, cur.flow_scale ?? 1.0, Boolean(cur.performance_mode)));
    generatorQueue.current = saved;
    try {
      const r = await saved;
      if (r.status === "success") await syncLaunchMode(requestApp);
      toast(r.message || r.status);
    } catch (e) {
      toast(errorText(e));
    } finally {
      generatorPending.current--;
      if (!generatorPending.current && selectedApp.current === requestApp) {
        await loadStatus(requestApp, true);
        lsfgDraft.current = null;
      }
      if (!generatorPending.current) setGeneratorSaving(false);
    }
  });

  const changeSetting = withSettingFocus(async (key: string, value: string) => {
    try {
      const r = await setGameSetting(appid, key, value);
      toast(r.message || r.status);
    } catch (e) {
      toast(errorText(e));
    }
    await loadStatus(appid, true);
  });

  const changeUpscaler = withSettingFocus(async (choice: string, watermark: boolean) => {
    if (busy !== null) return;
    try {
      const r = await setUpscaler(appid, choice, watermark);
      if (r.status === "success") await syncLaunchMode(appid);
      toast(r.message || r.status);
    } catch (e) {
      toast(errorText(e));
    }
    await loadStatus(appid, true);
  });

  // Upscaler dropdown with the NPU folded in: "npu" = OptiScaler upscaling off + NPU 720p -> 1080p.
  // NPU mode = the clean game + NPU: removes OptiScaler and turns frame generation off. Anything else is opt-in.
  const enableNpuClean = async (): Promise<string> => {
    const parts: string[] = [];
    if (patched) {
      const current = await getLaunchOptions(Number(appid));
      const u = await unpatchGame(appid, current);
      if (u.status !== "success") throw new Error(u.message || t("Unpatch failed."));
      if (u.launch_options !== undefined && u.launch_options !== current) setLaunchOptions(Number(appid), u.launch_options);
      parts.push(t("OptiScaler and frame generation removed from the game."));
    } else if (status?.lsfg) {
      const g = await setGeneratorMode(appid, "off", 2, 1.0, false);
      if (g.status !== "success") throw new Error(g.message || t("Failed."));
      await syncLaunchMode(appid);
      parts.push(t("Lossless Scaling turned off."));
    }
    const now = await getLaunchOptions(Number(appid));
    const n = await setNpuSr(appid, true, now);
    if (n.status !== "success") throw new Error(n.message || t("Failed."));
    if (n.launch_options !== undefined) setLaunchOptions(Number(appid), n.launch_options);
    parts.push(n.message || "");
    parts.push(t("Add Lossless Scaling yourself if you want frame generation."));
    return parts.filter(Boolean).join(" ");
  };

  // FSR 4 / Lite, ANR FG and XeFG run through OptiScaler: turn the NPU off, install the Hub, then apply the choice.
  const installHubThen = async (apply: () => Promise<{ status: string; message?: string }>): Promise<string> => {
    const parts: string[] = [];
    if (npu?.enabled) {
      const before = await getLaunchOptions(Number(appid));
      const n = await setNpuSr(appid, false, before);
      if (n.status !== "success") throw new Error(n.message || t("Failed."));
      if (n.launch_options !== undefined) setLaunchOptions(Number(appid), n.launch_options);
    }
    const current = await getLaunchOptions(Number(appid));
    const r = await patchGame(appid, current, dirChoice === AUTO_DIR ? "" : dirChoice);
    if (r.status !== "success") throw new Error(r.message || t("Patch failed."));
    if (r.launch_options !== undefined && r.launch_options !== current) setLaunchOptions(Number(appid), r.launch_options);
    parts.push(r.message || "");
    const a = await apply();
    if (a.status !== "success") throw new Error(a.message || t("Failed."));
    await syncLaunchMode(appid);
    parts.push(a.message || "");
    return parts.filter(Boolean).join(" ");
  };

  // Unpatched game: one Upscaler list and one Frame generator list; OptiScaler is installed only when a choice needs it.
  const changeCleanChoice = withSettingFocus(async (kind: "upscaler" | "generator", choice: string) => {
    if (busy !== null) return;
    setBusy("patch");
    try {
      if (kind === "upscaler" && choice === "npu") toast(await enableNpuClean());
      else if (kind === "upscaler" && choice === "off") {
        if (npu?.enabled) {
          const current = await getLaunchOptions(Number(appid));
          const n = await setNpuSr(appid, false, current);
          if (n.status === "success" && n.launch_options !== undefined) setLaunchOptions(Number(appid), n.launch_options);
          toast(n.message || n.status);
        }
      } else if (kind === "upscaler") toast(await installHubThen(() => setUpscaler(appid, choice, false)));
      else if (choice === "anr" || choice === "xefg") toast(await installHubThen(() => setGeneratorMode(appid, choice, 2, 1.0, false)));
      else {
        const g = await setGeneratorMode(appid, choice, 2, 1.0, false);
        if (g.status === "success") await syncLaunchMode(appid);
        toast(g.message || g.status);
      }
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(null);
    }
    await loadStatus(appid, true);
    await loadGames();
    await loadNpu(appid);
  });

  const changeUpscalerChoice = withSettingFocus(async (choice: string, watermark: boolean) => {
    if (busy !== null) return;
    if (choice === "npu") {
      setBusy("unpatch");
      try { toast(await enableNpuClean()); } catch (e) { toast(errorText(e)); }
      finally { setBusy(null); }
      await loadStatus(appid, true);
      await loadGames();
      await loadNpu(appid);
      return;
    }
    const npuWanted = false;
    const optiChoice = choice === "npu" ? "off" : choice;
    try {
      const r = await setUpscaler(appid, optiChoice, watermark);
      if (r.status === "success") await syncLaunchMode(appid);
      let msg = r.message || r.status;
      if (r.status === "success" && npu?.available && Boolean(npu.enabled) !== npuWanted) {
        const current = await getLaunchOptions(Number(appid));
        const n = await setNpuSr(appid, npuWanted, current);
        if (n.status === "success" && n.launch_options !== undefined) setLaunchOptions(Number(appid), n.launch_options);
        msg = `${msg} ${n.message || ""}`.trim();
      }
      toast(msg);
    } catch (e) {
      toast(errorText(e));
    }
    await loadStatus(appid, true);
    await loadNpu(appid);
  });

  const changeOpti = withSettingFocus(async (key: string, value: string) => {
    if (busy !== null) return;
    const before = opti[key];
    setOpti((cur) => ({ ...cur, [key]: value }));
    let ok = false;
    try {
      const r = await setOptiSetting(appid, key, value);
      ok = r.status === "success";
      if (ok) await syncLaunchMode(appid);
      if (!ok) toast(r.message || t("Failed."));
      else if (r.message && (r.message.includes(t("Turned off")) || status?.running)) toast(r.message);
      if (ok) {
        // other settings may have been turned off with this one
        const o = await getOptiSettings(appid);
        if (o.status === "success") setOpti(o.settings);
      }
    } catch (e) {
      toast(errorText(e));
    }
    if (!ok) setOpti((cur) => ({ ...cur, [key]: before ?? "auto" }));
  });

  const profileAction = withSettingFocus(async (fn: () => Promise<{ status: string; message?: string }>) => {
    try {
      const r = await fn();
      toast(r.message || r.status);
    } catch (e) {
      toast(errorText(e));
    }
    await loadStatus(appid, true);
  });

  const changeRenderQuality = withSettingFocus(async (choice: string) => {
    if (busy !== null) return;
    try {
      const r = await setRenderQuality(appid, choice);
      if (r.status === "success") await syncLaunchMode(appid);
      toast(r.message || r.status);
    } catch (e) {
      toast(errorText(e));
    }
    await loadStatus(appid, true);
  });

  const renderSize = (ratio: number | null | undefined) => {
    const out = upscaler?.output || [1920, 1080];
    if (!ratio) return null;
    return `${Math.round(out[0] / ratio)}×${Math.round(out[1] / ratio)}`;
  };

  const addFfx4Upgrade = async () => {
    const current = await getLaunchOptions(Number(appid));
    if (current.includes("PROTON_FFX4_UPGRADE")) {
      toast(t("PROTON_FFX4_UPGRADE is already set: start the game once, then choose FSR 4."));
      return;
    }
    const next = current.includes("%command%")
      ? `PROTON_FFX4_UPGRADE=1 ${current}`
      : `PROTON_FFX4_UPGRADE=1 %command% ${current}`.trim();
    setLaunchOptions(Number(appid), next);
    toast(t("Added PROTON_FFX4_UPGRADE=1. Start the game once (proton-cachyos or GE-Proton), then choose FSR 4."));
    window.setTimeout(() => void loadStatus(appid, true), 500);
  };

  const showPerf = async () => {
    try {
      const r = await getPerformance(appid, 8);
      if (r.status !== "success") throw new Error(r.message || t("No data."));
      setPerf({ sessions: r.sessions || [], summary: r.summary });
      if (!r.sessions?.length) toast(t("No sessions with frame generation yet: play with DLSS FG on."));
    } catch (e) {
      toast(errorText(e));
    }
  };

  const showLog = async () => {
    try {
      const r = await readGameLog(appid, 30);
      setLog(r.log || r.message || "");
    } catch (e) {
      setLog(errorText(e));
    }
  };

  const patched = Boolean(status?.patched);
  const isXefg = status?.generator?.choice === "xefg";
  const genChoice = status?.generator?.choice || "anr";
  const generatorLabel =
    genChoice === "xefg" ? t("XeFG XMX Port · Build 10 beta")
    : genChoice === "lsfg" ? "Lossless Scaling (lsfg-vk)"
    : genChoice === "off" ? t("No frame generation")
    : genChoice === "custom" ? status?.generator?.provider || "custom"
    : "ANR FG";
  const proxyBase = (status?.proxy || "dxgi.dll").replace(/\.dll$/i, "");
  const proxyMode = status?.optiscaler_required === false ? "b" : "n,b";
  const anrLaunchLine = `WINEDLLOVERRIDES="${proxyBase}=${proxyMode}" %command%`;
  const launchHasOverride = launchOptions.includes(`${proxyBase}=${proxyMode}`);

  const copyLaunch = async () => {
    toast((await copyText(anrLaunchLine)) ? t("Copied: {0}", anrLaunchLine) : t("Could not copy to the clipboard."));
  };

  const applyLaunch = async () => {
    const r = await syncLaunchMode(appid);
    if (r.status !== "success") toast(r.message || r.status);
    else toast(t("Launch options: {0}", r.launch_options || launchOptions));
    window.setTimeout(() => void loadStatus(appid, true), 500);
  };
  const outdated =
    patched && status?.game_version && status?.active_version && status.game_version !== status.active_version;
  const settings = status?.settings || {};
  const maxGenerated = Number(settings.max_generated || 1);

  const statusText = (() => {
    if (!game) return "—";
    if (loadingStatus) return "…";
    if (!status || status.status === "error") return status?.message || "—";
    if (!patched) return t("Not patched");
    const how = status.mode === "addon" ? t("add-on to OptiScaler") : t("OptiScaler as {0}", status.proxy);
    return t("{0} · Hub files {1} ({2})", generatorLabel, status.game_version ?? "?", how);
  })();

  return (
    <PanelSection title={t("Game")}>
      <PanelSectionRow>
        <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
          layout="below"
          label={t("Steam game")}
          strDefaultLabel={loadingGames ? t("Loading…") : t("Choose a game")}
          disabled={loadingGames || games.length === 0}
          selectedOption={appid}
          rgOptions={games.map((g) => ({ data: g.appid, label: g.patched ? `★ ${g.name}` : g.name }))}
          onChange={(o) => {
            rememberedAppId = String(o.data);
            setAppid(String(o.data));
          }}
        />
      </PanelSectionRow>

      {game && (
        <>
          <PanelSectionRow>
            <div style={{ padding: "12px", borderRadius: "10px", background: "rgba(103,160,220,0.10)", border: "1px solid rgba(137,184,229,0.20)", width: "100%", boxSizing: "border-box" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginBottom: "10px" }}>
                <b style={{ fontSize: "13px" }}>{t("Current setup")}</b>
                <span style={{ fontSize: "11px", color: status?.running ? "#e9c46a" : "#86dca5", borderRadius: "12px", padding: "2px 7px", background: "rgba(255,255,255,0.06)" }}>
                  {status?.running ? t("Running") : t("Ready to configure")}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "8px", fontSize: "12px" }}>
                <span style={{ opacity: 0.7 }}>{t("Image upscaling")}</span>
                <b>{(() => {
                  const base = upscaler?.choice ? upscaler.options?.find(o => o.value === upscaler.choice)?.label || upscaler.choice : t("Package defaults");
                  if (!npu?.enabled) return base;
                  return !upscaler?.choice || upscaler.choice === "off" ? t("Game TAA → NPU 1080p") : t("{0} → NPU 1080p", base);
                })()}</b>
                <span style={{ opacity: 0.7 }}>{t("Frame generation")}</span>
                <b style={{ textAlign: "right", color: npu?.enabled && (npu.fg ?? 1) !== 1 ? "#86dca5" : undefined }}>{
                  status?.lsfg ? "LSFG"
                  : patched ? generatorLabel
                  : npu?.enabled && (npu.fg ?? 1) !== 1
                    ? (npu.fg === 0 ? t("NPU FG · Auto") : `NPU FG · ${npu.fg}×`)
                  : t("Off")
                }</b>
                {npu && <>
                  <span style={{ opacity: 0.7 }}>{t("NPU upscaling")}</span>
                  <b style={{ textAlign: "right", color: npu.enabled ? "#86dca5" : undefined }}>
                    {npu.enabled ? (npu.models?.find((m) => m.file === npu.model)?.label?.split(" (")[0] || t("On")) : t("Off")}</b>
                </>}
              </div>
              {status?.status === "error" && <div style={{ ...small, color: "#ff9b91", marginTop: "8px" }}>{status.message}</div>}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below"
              description={status?.running ? t("Close the game to restore it.")
                : patched || status?.lsfg || status?.managed || npu?.enabled
                ? t("Removes this plugin's patches and launch options, disables its Lossless Scaling profile and the NPU upscaler, and restores backed-up files. Other mods and shared imported libraries are kept.")
                : t("This game has no changes managed by this plugin.")}
              disabled={busy !== null || generatorSaving || loadingStatus || status?.running || !(patched || status?.lsfg || status?.managed || npu?.enabled)}
              onClick={doUnpatch}>
              {busy === "unpatch" ? t("Restoring game…") : t("Restore game (remove plugin patches)")}
            </ButtonItem>
          </PanelSectionRow>

          {npu && !patched && (
            <>
              <PanelSectionRow>
                <div style={{ ...small, opacity: 1, fontWeight: 700, marginTop: "6px" }}>{t("NPU upscaling & frame generation (Ryzen AI)")}</div>
              </PanelSectionRow>
              {npu.enabled && (
                <PanelSectionRow>
                  {(() => {
                    const live = npu.live;
                    const npuOn = Boolean(live?.connected && (live.npu_frames ?? 0) > 0);
                    const fgActive = (live?.fg_active ?? 1) > 1;
                    const fgWant = (npu.fg ?? 1) !== 1;
                    const baseFps = live?.fg_free_fps ?? 0;
                    const outFps = fgActive && baseFps > 0 ? Math.round(baseFps * (live?.fg_active ?? 1)) : 0;
                    const engLabel = (live?.fg_engine || npu.fg_engine || "npu") === "npu" ? "NPU FlowNet" : "CPU";
                    const boxStyle: React.CSSProperties = {
                      padding: "8px 10px",
                      borderRadius: "6px",
                      background: npuOn ? "rgba(134,220,165,0.12)" : "rgba(255,216,102,0.10)",
                      border: `1px solid ${npuOn ? "rgba(134,220,165,0.35)" : "rgba(255,216,102,0.30)"}`,
                      fontSize: "12px",
                      lineHeight: "17px",
                    };
                    return (
                      <div style={boxStyle}>
                        <div style={{ fontWeight: 700, color: npuOn ? "#86dca5" : "#ffd866" }}>
                          {npuOn
                            ? t("● NPU active: {0} → {1} ({2} ms)", live?.in ?? "?", live?.out ?? "?", (live?.npu_ms ?? 0).toFixed(1))
                            : status?.running
                              ? t("● Waiting for 900p / 720p / 576p frame")
                              : t("○ NPU ready ({0})", npu.service ?? "?")}
                        </div>
                        <div style={{ marginTop: "2px", color: fgActive ? "#86dca5" : fgWant ? "#ffd866" : "rgba(255,255,255,0.75)" }}>
                          {fgActive
                            ? t("● Frame Gen {0}× ({1}): ~{2} FPS · flow {3} ms", String(live?.fg_active ?? 2), engLabel, String(outFps || "?"), (live?.fg_flow_ms ?? 0).toFixed(1))
                            : fgWant
                              ? (npuOn ? t("◐ Frame Gen standby ({0})", npu.fg === 0 ? t("Auto") : `${npu.fg}×`) : t("○ Frame Gen armed ({0} · {1})", npu.fg === 0 ? t("Auto") : `${npu.fg}×`, engLabel))
                              : t("○ Frame Gen off (1×)")}
                        </div>
                      </div>
                    );
                  })()}
                </PanelSectionRow>
              )}
              <PanelSectionRow>
                <DropdownItem
                  onMenuWillOpen={openMenuWithFocus}
                  label={t("Upscaler")}
                  description={npu.enabled
                    ? t("Supports 1600×900, 1280×720, and 1024×576 → 1080p on the Ryzen AI NPU with built-in AA and Async Frame Generation. Keeps game files clean.")
                    : npu.available
                    ? t("FSR 4 and FSR 4 Lite install OptiScaler into the game automatically. NPU and Off keep the game clean.")
                    : t("Not installed on this device: {0}. Import the NPU package in Tools → Libraries and updates.", (npu.missing ?? []).map((m) => t(m)).join(", "))}
                  selectedOption={npu.enabled ? "npu" : "off"}
                  disabled={busy !== null || Boolean(status?.running) || status?.installed === false}
                  rgOptions={[
                    { data: "off", label: t("Off (game's own)") },
                    ...(npu.available ? [{ data: "npu", label: t("NPU (900p / 720p / 576p → 1080p)") }] : []),
                    { data: "fsr4", label: t("FSR 4 · installs OptiScaler") },
                    { data: "fsr4lite", label: t("FSR 4 Lite · installs OptiScaler") },
                  ]}
                  onChange={(o: { data: string }) => void changeCleanChoice("upscaler", String(o.data))} />
              </PanelSectionRow>
              {npu.available && npu.enabled && (
                <>
                  <PanelSectionRow>
                    <DropdownItem
                      onMenuWillOpen={openMenuWithFocus}
                      label={t("Render resolution (Steam)")}
                      description={t("Sets Steam's Game Resolution for this game (applies on next launch). To switch live without restarting, change resolution in the game's graphics menu — NPU adapts automatically.")}
                      selectedOption={["", "1600x900", "1280x720", "1024x576"].includes(resOverride) ? resOverride : ""}
                      rgOptions={[
                        { data: "", label: t("Default (game decides)") },
                        { data: "1600x900", label: t("1600×900 · Quality (×1.2)") },
                        { data: "1280x720", label: t("1280×720 · Balanced (×1.5)") },
                        { data: "1024x576", label: t("1024×576 · Performance (×2)") },
                      ]}
                      onChange={(o: { data: string }) => void changeResOverride(String(o.data))} />
                  </PanelSectionRow>
                  <PanelSectionRow>
                    <SliderField label={t("NPU Frame Generation")}
                      value={npu.fg === 0 ? 1 : npu.fg === 2 ? 2 : npu.fg === 3 ? 3 : 0}
                      min={0} max={3} step={1}
                      notchCount={4} notchLabels={[
                        { notchIndex: 0, label: t("Off (1×)"), value: 0 },
                        { notchIndex: 1, label: t("Auto"), value: 1 },
                        { notchIndex: 2, label: "2×", value: 2 },
                        { notchIndex: 3, label: "3×", value: 3 },
                      ]}
                      description={t("Async frame generator (Off, Auto, 2×, 3×). Auto picks 2×/3× from real FPS and caps Gamescope to refresh/multiplier. Applies within a second.")}
                      onChange={(idx: number) => {
                        const fgMap = [1, 0, 2, 3];
                        void changeNpuFg(fgMap[Math.max(0, Math.min(3, Math.round(idx)))]);
                      }} />
                  </PanelSectionRow>
                  {(npu.fg ?? 1) !== 1 && (
                    <PanelSectionRow>
                      <DropdownItem
                        onMenuWillOpen={openMenuWithFocus}
                        label={t("Frame Generation engine")}
                        description={t("Choose where optical flow runs: NPU (FlowNet v2 80×48 + occlusion mask, ~1 ms on NPU) or CPU (fast block-matching, 0 NPU load). Switches live in 1s.")}
                        selectedOption={npu.fg_engine ?? "npu"}
                        rgOptions={[
                          { data: "npu", label: t("NPU (FlowNet v2 · ~1 ms)") },
                          { data: "cpu", label: t("CPU (fast · 0 NPU load)") },
                        ]}
                        onChange={(o: { data: string }) => void changeNpuFgEngine(String(o.data))} />
                    </PanelSectionRow>
                  )}
                  <PanelSectionRow>
                    <SliderField label={t("NPU anti-aliasing")} value={npu.aa ?? 0.5} min={0} max={1} step={0.1}
                      showValue notchCount={11} notchTicksVisible={false}
                      description={t("Directional edge smoothing (removes stair-steps on diagonal edges without blurring textures). 0 = off. Applies within a second.")}
                      onChange={(v: number) => void changeNpuAa(Math.round(v * 10) / 10)} />
                  </PanelSectionRow>
                  <PanelSectionRow>
                    <SliderField label={t("NPU sharpness")} value={npu.sharpness ?? 0} min={0} max={1} step={0.1}
                      showValue notchCount={11} notchTicksVisible={false}
                      description={t("Extra edge and texture detail after the NPU, without halos. 0 = off. Applies to a running game within a second.")}
                      onChange={(v: number) => void changeNpuSharpness(Math.round(v * 10) / 10)} />
                  </PanelSectionRow>
                </>
              )}
              {npu.available && npu.enabled && (npu.models_900p?.length ?? 0) > 0 && (
                <PanelSectionRow>
                  <DropdownItem
                    onMenuWillOpen={openMenuWithFocus}
                    label={t("NPU model for 1600×900 (×1.2)")}
                    description={t("Used automatically when the game runs at 1600×900: near-native 1080p clarity in ~3.5 ms on the NPU.")}
                    selectedOption={npu.model_900p ?? ""}
                    rgOptions={(npu.models_900p ?? []).map((m) => ({ data: m.file, label: m.label }))}
                    onChange={(o: { data: string }) => void changeNpuModel(o.data)} />
                </PanelSectionRow>
              )}
              {npu.available && npu.enabled && (npu.models?.length ?? 0) > 0 && (
                <PanelSectionRow>
                  <DropdownItem
                    onMenuWillOpen={openMenuWithFocus}
                    label={t("NPU model (720p)")}
                    description={npu.models?.find((m) => m.file === npu.model)?.note || t("Shared by all NPU games. 900p model is selected automatically.")}
                    selectedOption={npu.model ?? ""}
                    rgOptions={(npu.models ?? []).map((m) => ({ data: m.file, label: m.label }))}
                    onChange={(o: { data: string }) => void changeNpuModel(o.data)} />
                </PanelSectionRow>
              )}
              {npu.available && npu.enabled && (npu.models_x2?.length ?? 0) > 0 && (
                <PanelSectionRow>
                  <DropdownItem
                    onMenuWillOpen={openMenuWithFocus}
                    label={t("NPU model for 1024×576 (×2)")}
                    description={t("Used automatically when the game runs at 1024×576 (Steam game resolution): the GPU renders 36% fewer pixels than at 720p, the NPU doubles it.")}
                    selectedOption={npu.model_x2 ?? ""}
                    rgOptions={(npu.models_x2 ?? []).map((m) => ({ data: m.file, label: m.label }))}
                    onChange={(o: { data: string }) => void changeNpuModel(o.data)} />
                </PanelSectionRow>
              )}
              {npuLine && <PanelSectionRow><div style={small}>{npuLine}</div></PanelSectionRow>}
            </>
          )}





          {status?.running && (
            <PanelSectionRow>
              <div style={{ ...small, color: "#ffd866" }}>{t("The game is running: close it to patch or unpatch.")}</div>
            </PanelSectionRow>
          )}



          {!patched && status?.installed !== false && (
            <>
              <PanelSectionRow>
                <DropdownItem
                  onMenuWillOpen={openMenuWithFocus}
                  label={t("Frame generator")}
                  description={npu?.enabled
                    ? t("With the NPU only Lossless Scaling helps: it needs no OptiScaler. ANR FG and XeFG turn the NPU off and install OptiScaler.")
                    : t("Lossless Scaling works in any game without OptiScaler (needs your Lossless Scaling, Steam branch lsfg-vk). ANR FG and XeFG install OptiScaler automatically and replace the game's DLSS Frame Generation.")}
                  selectedOption={status?.lsfg ? "lsfg" : "off"}
                  disabled={busy !== null || Boolean(status?.running)}
                  rgOptions={[
                    { data: "off", label: t("Off") },
                    { data: "lsfg", label: "Lossless Scaling" },
                    { data: "anr", label: t("ANR FG · installs OptiScaler") },
                    { data: "xefg", label: t("XeFG · installs OptiScaler") },
                  ]}
                  onChange={(o: { data: string }) => void changeCleanChoice("generator", String(o.data))} />
              </PanelSectionRow>
              {status?.lsfg && (
                <LsfgControls profile={status.lsfg} busy={(busy === "patch" || busy === "unpatch") || Boolean(status?.running)}
                  onChange={(p) => void changeGenerator("lsfg", p)} />
              )}
            </>
          )}

          {!patched && status?.conflict && (
            <PanelSectionRow>
              <div style={{ ...small, color: "#ffd866" }}>{status.conflict}</div>
            </PanelSectionRow>
          )}

          {!patched && status?.candidates && status.candidates.length > 1 && (
            <PanelSectionRow>
              <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                layout="below"
                label={t("Game .exe")}
                selectedOption={dirChoice}
                rgOptions={[
                  { data: AUTO_DIR, label: t("Auto: {0}", status.candidates[0].exe) },
                  ...status.candidates.map((c) => ({ data: c.dir, label: c.exe })),
                ]}
                onChange={(o) => setDirChoice(String(o.data))}
              />
            </PanelSectionRow>
          )}

          {!patched && npu?.enabled && (
            <PanelSectionRow>
              <div style={{ ...small, opacity: 1 }}>
                {t("NPU mode: the game runs clean, without OptiScaler. Nothing to install. For frame generation turn on Lossless Scaling below: it does not need OptiScaler. FSR 4, ANR FG and XeFG only lower FPS with the NPU.")}
              </div>
            </PanelSectionRow>
          )}
          {(!patched || outdated) && !(npu?.enabled && !patched) && <>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={!info?.installed || busy !== null || generatorSaving || loadingStatus || status?.running}
              onClick={doPatch}
            >
              {busy === "patch"
                ? t("Installing…")
                : patched
                ? outdated
                  ? t("Update to {0}", status?.active_version)
                  : t("Reinstall Hub files")
                : t("Install Hub")}
            </ButtonItem>
          </PanelSectionRow>

          </>}





          {patched && (
            <>
              <PanelSectionRow><div style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.07em", opacity: 0.65, marginTop: "14px" }}>{t("1 · Image quality")}</div></PanelSectionRow>
              {upscaler?.options && (
                <>
                  <PanelSectionRow>
                    <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                      label={t("Upscaler")}
                      description={
                        npu?.enabled && (!upscaler.choice || upscaler.choice === "off")
                          ? t("The game renders at 1600×900, 1280×720, or 1024×576 with its own TAA; the Ryzen AI NPU upscales to 1080p without using the GPU. Turn DLSS/FSR off in the game.")
                          : upscaler.signed_sdk && ["fsr4", "fsr4lite"].includes(upscaler.choice || "")
                          ? t("Official FSR 4 SDK with signed OptiScaler. DLSS in the game is the input; FSR 4 is the output. INT8 is enabled for this GPU when needed.")
                          : upscaler.choice === "fsr4lite"
                          ? t("INT8 Lite from your imported libraries. Enable the watermark to verify FSR4L-i8 after launch.")
                          : upscaler.choice === "fsr4"
                          ? t("FSR 4 {0} model{1}{2}", upscaler.rdna4 ? "FP8" : "INT8", upscaler.fsr4_source
                                ? t(", AMD FidelityFX {0} from {1}", upscaler.fsr4_source.version, upscaler.fsr4_source.source || "Proton")
                                : "", upscaler.gpu_family === "rdna2" ? t(". Slow on RDNA 2 (Steam Deck): FSR 3.1 is usually better.") : "")
                          : upscaler.gpu_family === "rdna2"
                          ? t("OptiScaler's upscaler. On RDNA 2 (Steam Deck) FSR 3.1 is the fast choice.")
                          : t("OptiScaler's upscaler. The game's DLSS option drives it.")
                      }
                      selectedOption={npu?.enabled
                        ? (!upscaler.choice || upscaler.choice === "off" ? "npu" : upscaler.choice)
                        : (upscaler.choice || "package")}
                      rgOptions={(() => {
                        const list = upscaler.options.map((o) => ({
                          data: o.value,
                          label:
                            o.value === "fsr4lite" && !upscaler.fsr4_lite_available ? t("{0} (import ZIP first)", o.label)
                            : o.value === "fsr4" && !upscaler.fsr4_source ? t("{0} (needs Proton Experimental)", o.label)
                            : o.value === "fsr4" && upscaler.gpu_family === "rdna2" ? t("{0} · slow on this GPU", o.label)
                            : o.label,
                        }));
                        if (!npu?.available) return list;
                        return [{ data: "npu", label: t("NPU (900p / 720p / 576p → 1080p)") }, ...list];
                      })()}
                      onChange={(o) => void changeUpscalerChoice(String(o.data), Boolean(upscaler.watermark))}
                    />
                  </PanelSectionRow>
                  {npu?.available && (
                    <PanelSectionRow>
                      <ToggleField
                        label={t("NPU layer on top (900p / 720p → 1080p + NPU FG)")}
                        description={t("Combine FSR 4 Lite / OptiScaler (internal temporal upscale to 900p or 720p) with Ryzen AI NPU upscaling to 1080p and NPU Frame Generation. Keep in-game/OptiScaler frame generation Off.")}
                        checked={Boolean(npu.enabled)}
                        disabled={busy !== null || Boolean(status?.running)}
                        onChange={(on: boolean) => void toggleNpuHybrid(on)}
                      />
                    </PanelSectionRow>
                  )}
                  {npu?.enabled && npu.available && (
                    <>
                      <PanelSectionRow>
                        {(() => {
                          const live = npu.live;
                          const npuOn = Boolean(live?.connected && (live.npu_frames ?? 0) > 0);
                          const fgActive = (live?.fg_active ?? 1) > 1;
                          const fgWant = (npu.fg ?? 1) !== 1;
                          const baseFps = live?.fg_free_fps ?? 0;
                          const outFps = fgActive && baseFps > 0 ? Math.round(baseFps * (live?.fg_active ?? 1)) : 0;
                          const engLabel = (live?.fg_engine || npu.fg_engine || "npu") === "npu" ? "NPU FlowNet" : "CPU";
                          const boxStyle: React.CSSProperties = {
                            padding: "8px 10px",
                            borderRadius: "6px",
                            background: npuOn ? "rgba(134,220,165,0.12)" : "rgba(255,216,102,0.10)",
                            border: `1px solid ${npuOn ? "rgba(134,220,165,0.35)" : "rgba(255,216,102,0.30)"}`,
                            fontSize: "12px",
                            lineHeight: "17px",
                          };
                          return (
                            <div style={boxStyle}>
                              <div style={{ fontWeight: 700, color: npuOn ? "#86dca5" : "#ffd866" }}>
                                {npuOn
                                  ? t("● NPU active: {0} → {1} ({2} ms)", live?.in ?? "?", live?.out ?? "?", (live?.npu_ms ?? 0).toFixed(1))
                                  : status?.running
                                    ? t("● Waiting for 900p / 720p / 576p frame")
                                    : t("○ NPU ready ({0})", npu.service ?? "?")}
                              </div>
                              <div style={{ marginTop: "2px", color: fgActive ? "#86dca5" : fgWant ? "#ffd866" : "rgba(255,255,255,0.75)" }}>
                                {fgActive
                                  ? t("● Frame Gen {0}× ({1}): ~{2} FPS · flow {3} ms", String(live?.fg_active ?? 2), engLabel, String(outFps || "?"), (live?.fg_flow_ms ?? 0).toFixed(1))
                                  : fgWant
                                    ? (npuOn ? t("◐ Frame Gen standby ({0})", npu.fg === 0 ? t("Auto") : `${npu.fg}×`) : t("○ Frame Gen armed ({0} · {1})", npu.fg === 0 ? t("Auto") : `${npu.fg}×`, engLabel))
                                    : t("○ Frame Gen off (1×)")}
                              </div>
                            </div>
                          );
                        })()}
                      </PanelSectionRow>
                      <PanelSectionRow>
                        <DropdownItem
                          onMenuWillOpen={openMenuWithFocus}
                          label={t("Render resolution (Steam)")}
                          description={t("Sets Steam's Game Resolution for this game (applies on next launch). To switch live without restarting, change resolution in the game's graphics menu — NPU adapts automatically.")}
                          selectedOption={["", "1600x900", "1280x720", "1024x576"].includes(resOverride) ? resOverride : ""}
                          rgOptions={[
                            { data: "", label: t("Default (game decides)") },
                            { data: "1600x900", label: t("1600×900 · Quality (×1.2)") },
                            { data: "1280x720", label: t("1280×720 · Balanced (×1.5)") },
                            { data: "1024x576", label: t("1024×576 · Performance (×2)") },
                          ]}
                          onChange={(o: { data: string }) => void changeResOverride(String(o.data))} />
                      </PanelSectionRow>
                      <PanelSectionRow>
                        <SliderField label={t("NPU Frame Generation")}
                          value={npu.fg === 0 ? 1 : npu.fg === 2 ? 2 : npu.fg === 3 ? 3 : 0}
                          min={0} max={3} step={1}
                          notchCount={4} notchLabels={[
                            { notchIndex: 0, label: t("Off (1×)"), value: 0 },
                            { notchIndex: 1, label: t("Auto"), value: 1 },
                            { notchIndex: 2, label: "2×", value: 2 },
                            { notchIndex: 3, label: "3×", value: 3 },
                          ]}
                          description={t("Async frame generator (Off, Auto, 2×, 3×). Auto picks 2×/3× from real FPS and caps Gamescope to refresh/multiplier. Applies within a second.")}
                          onChange={(idx: number) => {
                            const fgMap = [1, 0, 2, 3];
                            void changeNpuFg(fgMap[Math.max(0, Math.min(3, Math.round(idx)))]);
                          }} />
                      </PanelSectionRow>
                      {(npu.fg ?? 1) !== 1 && (
                        <PanelSectionRow>
                          <DropdownItem
                            onMenuWillOpen={openMenuWithFocus}
                            label={t("Frame Generation engine")}
                            description={t("Choose where optical flow runs: NPU (FlowNet v2 80×48 + occlusion mask, ~1 ms on NPU) or CPU (fast block-matching, 0 NPU load). Switches live in 1s.")}
                            selectedOption={npu.fg_engine ?? "npu"}
                            rgOptions={[
                              { data: "npu", label: t("NPU (FlowNet v2 · ~1 ms)") },
                              { data: "cpu", label: t("CPU (fast · 0 NPU load)") },
                            ]}
                            onChange={(o: { data: string }) => void changeNpuFgEngine(String(o.data))} />
                        </PanelSectionRow>
                      )}
                      <PanelSectionRow>
                        <SliderField label={t("NPU anti-aliasing")} value={npu.aa ?? 0.5} min={0} max={1} step={0.1}
                          showValue notchCount={11} notchTicksVisible={false}
                          description={t("Directional edge smoothing (removes stair-steps on diagonal edges without blurring textures). 0 = off. Applies within a second.")}
                          onChange={(v: number) => void changeNpuAa(Math.round(v * 10) / 10)} />
                      </PanelSectionRow>
                      <PanelSectionRow>
                        <SliderField label={t("NPU sharpness")} value={npu.sharpness ?? 0} min={0} max={1} step={0.1}
                          showValue notchCount={11} notchTicksVisible={false}
                          description={t("Extra edge and texture detail after the NPU, without halos. 0 = off. Applies to a running game within a second.")}
                          onChange={(v: number) => void changeNpuSharpness(Math.round(v * 10) / 10)} />
                      </PanelSectionRow>
                      {(npu.models_900p?.length ?? 0) > 0 && (
                        <PanelSectionRow>
                          <DropdownItem
                            onMenuWillOpen={openMenuWithFocus}
                            label={t("NPU model for 1600×900 (×1.2)")}
                            description={t("Used automatically when the game runs at 1600×900: near-native 1080p clarity in ~3.5 ms on the NPU.")}
                            selectedOption={npu.model_900p ?? ""}
                            rgOptions={(npu.models_900p ?? []).map((m) => ({ data: m.file, label: m.label }))}
                            onChange={(o: { data: string }) => void changeNpuModel(o.data)} />
                        </PanelSectionRow>
                      )}
                      {(npu.models?.length ?? 0) > 0 && (
                        <PanelSectionRow>
                          <DropdownItem
                            onMenuWillOpen={openMenuWithFocus}
                            label={t("NPU model (720p)")}
                            description={npu.models?.find((m) => m.file === npu.model)?.note || t("Shared by all NPU games. 900p model is selected automatically.")}
                            selectedOption={npu.model ?? ""}
                            rgOptions={(npu.models ?? []).map((m) => ({ data: m.file, label: m.label }))}
                            onChange={(o: { data: string }) => void changeNpuModel(o.data)} />
                        </PanelSectionRow>
                      )}
                    </>
                  )}
                  {upscaler.render_options && (
                    <PanelSectionRow>
                      <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                        label={t("Render quality")}
                        description={(() => {
                          const cur = upscaler.render_options.find((o) => o.value === (upscaler.render_quality || "game"));
                          const out = upscaler.output || [1920, 1080];
                          return cur?.ratio
                            ? t("Renders at {0}, upscaled to {1}×{2}. Lower = faster.", renderSize(cur.ratio), out[0], out[1])
                            : t("Follows the DLSS mode chosen in the game (keep NVIDIA DLSS selected there).");
                        })()}
                        selectedOption={upscaler.render_quality || "game"}
                        rgOptions={upscaler.render_options.map((o) => ({
                          data: o.value,
                          label: o.ratio ? `${o.label} · ${renderSize(o.ratio)}` : o.label,
                        }))}
                        onChange={(o) => void changeRenderQuality(String(o.data))}
                      />
                    </PanelSectionRow>
                  )}
                  {!upscaler.fsr4_source && (
                    <>
                      {!upscaler.proton_experimental && (
                        <PanelSectionRow>
                          <ButtonItem layout="below"
                            description={t("Valve's Proton Experimental carries AMD's FSR 4 library; the plugin uses it from there.")}
                            onClick={() => {
                              try {
                                SteamClient.URL.ExecuteSteamURL("steam://install/1493710");
                              } catch {
                                toast(t("Install Proton Experimental from the Steam library (Tools)."));
                              }
                            }}>
                            {" "}{t("Install Proton Experimental (for FSR 4)")}{" "}</ButtonItem>
                        </PanelSectionRow>
                      )}
                      <PanelSectionRow>
                        <ButtonItem layout="below" onClick={addFfx4Upgrade}>
                          {" "}{t("Or: FSR 4 through proton-cachyos / GE-Proton (PROTON_FFX4_UPGRADE)")}{" "}</ButtonItem>
                      </PanelSectionRow>
                    </>
                  )}
                  {["fsr4", "fsr4lite"].includes(upscaler.choice || "") && (
                    <PanelSectionRow>
                      <ToggleField
                        label={t("Show the FSR watermark")}
                        description={t("Shows which FSR runs, to check FSR 4 is active.")}
                        checked={Boolean(upscaler.watermark)}
                        onChange={(on: boolean) => void changeUpscaler(upscaler.choice as string, on)}
                      />
                    </PanelSectionRow>
                  )}
                </>
              )}
              {npu?.capture?.available && (
                <PanelSectionRow>
                  <ToggleField label={t("Collect frames to train the NPU model")}
                    description={t("Saves native game frames (no upscaling) every few seconds to retrain the NPU models. Use Upscaler Off, native resolution and no frame generation; upscaled frames are skipped. Collected: {0}.", npu.capture.frames ?? 0)}
                    checked={Boolean(npu.capture.active)}
                    onChange={(on: boolean) => void changeNpuCapture(on)} />
                </PanelSectionRow>
              )}
              <PanelSectionRow><div style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.07em", opacity: 0.65, marginTop: "14px" }}>{t("2 · Smoothness")}</div></PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                  label={t("Frame generator")}
                  description={busy === "generator"
                    ? t("Preparing generator… First XeFG setup downloads about 75 MB.")
                    : genChoice === "lsfg"
                    ? t("Lossless Scaling is selected. Performance mode, multiplier and motion scale are below. Close the game to change settings.")
                    : t("Close the game to switch. XeFG is a beta for DirectX 12 games; Proton compatibility is experimental.")}
                  disabled={busy !== null || status?.running}
                  selectedOption={status?.generator?.choice || "anr"}
                  rgOptions={[
                    ...(status?.fg_available !== false ? [{ data: "anr", label: npu?.enabled ? t("{0} (not recommended with NPU)", "ANR FG") : "ANR FG" }] : []),
                    ...(status?.fg_available !== false && status?.generator?.available !== false ? [{ data: "xefg", label: npu?.enabled ? t("{0} (not recommended with NPU)", t("XeFG XMX Port · Build 10 (beta)")) : t("XeFG XMX Port · Build 10 (beta)") }] : []),
                    { data: "lsfg", label: "Lossless Scaling (lsfg-vk)" },
                    { data: "off", label: "Off" },
                    ...(status?.generator?.choice === "custom" ? [{ data: "custom", label: status.generator.provider }] : []),
                  ]}
                  onChange={(o) => { if (o.data !== "custom") void changeGenerator(String(o.data)); }}
                />
              </PanelSectionRow>
              {npu?.enabled && ["anr", "xefg"].includes(genChoice) && (
                <PanelSectionRow>
                  <div style={{ ...small, opacity: 1, color: "#ffd866", padding: "8px 10px", borderRadius: "8px", background: "rgba(255,216,102,0.10)" }}>
                    {t("With NPU upscaling, ANR FG and XeFG lower FPS: they run on the same GPU, which is the bottleneck at low TDP. Choose Lossless Scaling or Off.")}
                  </div>
                </PanelSectionRow>
              )}
              {isXefg && (
                <PanelSectionRow>
                  <div style={small}>
                    {" "}{t("XeFG needs DirectX 12 and SDR or HDR10. Start with 2X. The ANR compute settings below are hidden; the frame multiplier and upscaler still apply.")}{" "}</div>
                </PanelSectionRow>
              )}
              {genChoice === "lsfg" && (
                <LsfgControls profile={status?.lsfg || null} busy={(busy === "patch" || busy === "unpatch") || Boolean(status?.running)}
                  onChange={(p) => void changeGenerator("lsfg", p)} />
              )}

              <PanelSectionRow><div style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.07em", opacity: 0.65, marginTop: "14px" }}>{t("3 · Compatibility")}</div></PanelSectionRow>
              {status?.mode === "full" && (
                <PanelSectionRow>
                  <DropdownItem label={t("OptiScaler version")}
                    description={busy === "compat"
                      ? t("Preparing OptiScaler… The first download may take a few minutes.")
                      : ["lsfg", "off"].includes(genChoice)
                      ? t("Core for Lossless Scaling and no frame generation. Remembered separately from the ANR FG / XeFG core and swapped automatically when you change the frame generator. FSR 4 Lite: 0.9.5-pre5 (signed) or 0.10 Nightly.")
                      : t("Core for ANR FG and XeFG. Remembered separately from the Lossless Scaling core and swapped automatically when you change the frame generator. The Lite cores do not support ANR FG / XeFG.")}
                    selectedOption={status.optiscaler_core || (status.signed_optiscaler ? "signed" : "package")}
                    rgOptions={[
                      { data: "package", label: t("ANR package (original)") },
                      { data: "signed", label: t("OptiScaler 0.9.4 (signed)") },
                      ...(status.signed095_available && ["lsfg", "off"].includes(genChoice) ? [{ data: "signed095", label: t("OptiScaler 0.9.5-pre5 (signed, Lite test)") }] : []),
                      ...(["lsfg", "off"].includes(genChoice) && (!status.requires_signed_core || status.optiscaler_core === "nightly") ? [{ data: "nightly", label: t("OptiScaler 0.10 Nightly (FSR 4 Lite)") }] : []),
                    ]}
                    disabled={Boolean(status.running) || busy !== null}
                    onChange={(o) => void changeOptiscalerCore(String(o.data))} />
                </PanelSectionRow>
              )}
              {status?.mode === "full" && (
                <PanelSectionRow>
                  <ToggleField label={t("Fix DXGI (10DD hook error)")}
                    description={t("Disables global GPU spoofing for this game. Keeps the selected OptiScaler core, FSR 4 Lite and frame generator. Restart to test; if DLSS disappears, switch this fix off.")}
                    checked={opti.dxgi_spoofing === "false"}
                    disabled={Boolean(status.running) || busy !== null}
                    onChange={(enabled: boolean) => void changeOpti("dxgi_spoofing", enabled ? "false" : "auto")} />
                </PanelSectionRow>
              )}
              {status?.optiscaler_core === "nightly" && (
                <PanelSectionRow>
                  <ButtonItem layout="below" disabled={Boolean(status.running) || busy !== null}
                    onClick={() => void updateOptiscaler()}>
                    {t("Update OptiScaler")}
                  </ButtonItem>
                  <div style={small}>{t("Updates only this game's Nightly core. The plugin and other games stay on their current versions.")}</div>
                </PanelSectionRow>
              )}
          {patched && (
            <PanelSectionRow>
              <div style={{ ...small, opacity: 1, padding: "10px 12px", borderRadius: "8px", background: "rgba(255,255,255,0.045)" }}>
                <b>{t("What to set in the game")}</b><br />
                {npu?.enabled && (!upscaler?.choice || upscaler.choice === "off") && <>
                  {t("NPU: set game resolution to 1600×900, 1280×720, or 1024×576 (via Render resolution above or in-game settings). DLSS/FSR off, TAA on.")}<br /></>}
                {genChoice === "lsfg"
                  ? t("LSFG: turn off the game's own frame generation.")
                  : genChoice === "off"
                  ? t("Frame generation: off.")
                  : t("ANR / XeFG: enable DLSS Frame Generation in the game. The selected generator replaces it.")}
                {game?.name === "Diablo IV" && <><br />{t("Battle.net: close an already-running client, then launch this game's Steam shortcut to apply its launch options.")}</>}
              </div>
            </PanelSectionRow>
          )}

              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => setShowLaunchDetails(value => !value)}>
                  {showLaunchDetails ? t("Hide launch options") : t("Show launch options")}
                </ButtonItem>
              </PanelSectionRow>
              {showLaunchDetails && <>
          {patched && status?.mode === "full" && (
            <>
              <PanelSectionRow>
                <Field label={t("Launch options")} focusable bottomSeparator="none">
                  <span style={{ color: launchHasOverride ? "#3fb950" : "#ffd866" }}>
                    {launchHasOverride ? t("Set") : t("Missing")}
                  </span>
                </Field>
              </PanelSectionRow>
              <PanelSectionRow>
                <div style={small}>{launchOptions || t("(empty)")}</div>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={copyLaunch}>
                  {" "}{t("Copy launch options")}{" "}</ButtonItem>
              </PanelSectionRow>
              {!launchHasOverride && (
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={applyLaunch}>
                    {" "}{t("Apply launch options to the game")}{" "}</ButtonItem>
                </PanelSectionRow>
              )}
            </>
          )}              </>}
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => setShowAdvanced(value => !value)}
                  description={t("Fine tuning, diagnostics and restoring original game files.")}>
                  {showAdvanced ? t("Hide advanced settings") : t("Advanced settings")}
                </ButtonItem>
              </PanelSectionRow>
              {showAdvanced && <>
              {patched && !outdated && (
                <PanelSectionRow>
                  <ButtonItem layout="below"
                    description={t("Re-copies OptiScaler and the frame generator files into this game (after a game update, or if something stopped working). Settings are kept.")}
                    disabled={!info?.installed || busy !== null || generatorSaving || loadingStatus || status?.running}
                    onClick={doPatch}>
                    {busy === "patch" ? t("Installing…") : t("Reinstall Hub files")}
                  </ButtonItem>
                </PanelSectionRow>
              )}

              {status?.proxy === "dxgi.dll" && status.mode === "full" && (
                <PanelSectionRow>
                  <ToggleField label={t("LSFG only: bypass OptiScaler")}
                    description={status.dxgi_fix_available
                      ? t("For this game only. Bypasses OptiScaler for LSFG-only use. This is a crash workaround, not an FPS boost.")
                      : t("Not applied while FSR 4, another OptiScaler upscaler, ANR or XeFG is selected. Those features keep OptiScaler enabled.")}
                    checked={Boolean(status.dxgi_fix_enabled && status.dxgi_fix_available)}
                    disabled={Boolean(status.running) || busy !== null || !status.dxgi_fix_available || Boolean(status.signed_optiscaler)}
                    onChange={(enabled: boolean) => void changeDxgiFix(enabled)} />
                </PanelSectionRow>
              )}

              <PanelSectionRow><div style={small}>{statusText}</div></PanelSectionRow>
          {status?.proton && (
            <PanelSectionRow>
              <div style={{ ...small, color: status.proton.native ? "#ffd866" : undefined }}>
                {status.proton.native
                  ? t("Native Linux build (no .exe): the Hub needs the Windows version under Proton.")
                  : `Proton: ${status.proton.tool ?? t("Steam default")}${
                      status.proton.source === "default" ? t(" (default)") : ""
                    }${status.proton.prefix ? t(", prefix {0}", status.proton.prefix) : ""}`}
              </div>
            </PanelSectionRow>
          )}
          {patched && status?.target_rel && (
            <PanelSectionRow>
              <div style={small}>{t("Folder:")}{" "}{status.target_rel}</div>
            </PanelSectionRow>
          )}
              <PanelSectionRow>
                <div style={{ ...small, opacity: 1, fontWeight: 700, marginTop: "6px" }}>
                  {" "}{t("Game profile · tuning (OptiScaler). Close the game, change, start it again.")}{" "}</div>
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                  label={t("Frame generation multiplier")}
                  description={t("Overrides what the game asks for (many games only offer 2X on non-RTX 50 GPUs).")}
                  selectedOption={opti.fg_multiplier || "auto"}
                  rgOptions={[
                    { data: "auto", label: t("As the game asks") },
                    { data: "1", label: "2X" },
                    { data: "2", label: "3X" },
                    { data: "3", label: "4X" },
                    { data: "4", label: "5X" },
                    { data: "5", label: "6X" },
                  ]}
                  onChange={(o) => void changeOpti("fg_multiplier", String(o.data))}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label={t("Dynamic multiplier (DMFG) · experimental")}
                  description={t("Picks the lowest multiplier that reaches the target FPS (Streamline 2.11 games). Caused a GPU hang in Forza Horizon 6 on a Radeon 890M while switching multipliers: prefer a fixed multiplier.")}
                  checked={opti.dynamic_mfg === "true"}
                  onChange={(on: boolean) => void changeOpti("dynamic_mfg", on ? "true" : "auto")}
                />
              </PanelSectionRow>
              {opti.dynamic_mfg === "true" && (
                <PanelSectionRow>
                  <SliderField
                    label={t("DMFG target FPS")}
                    description={t("0 = the display's refresh rate.")}
                    value={Number(opti.dmfg_target && opti.dmfg_target !== "auto" ? opti.dmfg_target : 0)}
                    min={0}
                    max={120}
                    step={10}
                    notchTicksVisible
                    showValue
                    onChange={(v: number) => void changeOpti("dmfg_target", String(v))}
                  />
                </PanelSectionRow>
              )}
              {opti.dynamic_mfg === "true" ? (
                <PanelSectionRow>
                  <div style={small}>{t("FPS limit and a fixed multiplier are off while Dynamic MFG holds its own target.")}</div>
                </PanelSectionRow>
              ) : (
              <PanelSectionRow>
                <SliderField
                  label={t("FPS limit")}
                  description={t("0 = off. FPS on screen, in steps of 10. Steadier pacing and less battery drain.")}
                  value={Number(opti.fps_limit && opti.fps_limit !== "auto" ? opti.fps_limit : 0)}
                  min={0}
                  max={120}
                  step={10}
                  notchTicksVisible
                  showValue
                  onChange={(v: number) => void changeOpti("fps_limit", String(v))}
                />
              </PanelSectionRow>
              )}
              <PanelSectionRow>
                <ToggleField
                  label={t("Sharpening (RCAS)")}
                  description={t("Override the sharpening strength; useful with Performance render quality.")}
                  checked={opti.sharpness_override === "true"}
                  onChange={(on: boolean) => void changeOpti("sharpness_override", on ? "true" : "auto")}
                />
              </PanelSectionRow>
              {opti.sharpness_override === "true" && (
                <PanelSectionRow>
                  <SliderField
                    label={t("Sharpening strength")}
                    value={Math.round(Number(opti.sharpness && opti.sharpness !== "auto" ? opti.sharpness : 0.3) * 10)}
                    min={0}
                    max={13}
                    step={1}
                    showValue
                    valueSuffix=" /10"
                    onChange={(v: number) => void changeOpti("sharpness", String(v / 10))}
                  />
                </PanelSectionRow>
              )}
              <PanelSectionRow>
                <ToggleField
                  label={t("OptiScaler FPS counter")}
                  checked={opti.show_fps === "true"}
                  onChange={(on: boolean) => void changeOpti("show_fps", on ? "true" : "auto")}
                />
              </PanelSectionRow>
              {games.filter((g) => g.patched && g.appid !== appid).length > 0 && (
                <>
                  <PanelSectionRow>
                    <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                      label={t("Copy the profile from")}
                      strDefaultLabel={t("Choose a game")}
                      selectedOption={copyFrom}
                      rgOptions={games
                        .filter((g) => g.patched && g.appid !== appid)
                        .map((g) => ({ data: g.appid, label: g.name }))}
                      onChange={(o) => setCopyFrom(String(o.data))}
                    />
                  </PanelSectionRow>
                  {copyFrom && (
                    <PanelSectionRow>
                      <ButtonItem layout="below" onClick={() => profileAction(() => copyProfile(appid, copyFrom))}>
                        {" "}{t("Copy the profile")}{" "}</ButtonItem>
                    </PanelSectionRow>
                  )}
                </>
              )}
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => profileAction(() => resetProfile(appid))}>
                  {" "}{t("Reset the profile")}{" "}</ButtonItem>
              </PanelSectionRow>
              {genChoice === "anr" && (<>
              <PanelSectionRow>
                <SliderField
                  label={t("Generated frames")}
                  description={t("Up to {0}X. Restart the game after a change.", maxGenerated + 1)}
                  value={maxGenerated}
                  min={1}
                  max={5}
                  step={1}
                  showValue
                  notchTicksVisible
                  onChange={(v: number) => void changeSetting("max_generated", String(v))}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
          onMenuWillOpen={openMenuWithFocus}
                  label={t("Compute path")}
                  selectedOption={settings.path || "auto"}
                  rgOptions={PATH_OPTIONS.map((p) => ({ data: p, label: p === "auto" ? t("Automatic") : p }))}
                  onChange={(o) => void changeSetting("path", String(o.data))}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label={t("Scene cut detection")}
                  description={t("No interpolation across camera cuts.")}
                  checked={settings.scene_cut !== "0"}
                  onChange={(on: boolean) => void changeSetting("scene_cut", on ? "1" : "0")}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={showPerf}>
                  {" "}{t("Performance by compute path")}{" "}</ButtonItem>
              </PanelSectionRow>
              {perf && perf.sessions.length > 0 && (
                <PanelSectionRow>
                  <div style={{ ...small, opacity: 1 }}>
                    {perf.summary && perf.summary.length > 0 && (
                      <div style={{ marginBottom: "6px" }}>
                        <b>{t("Best:")}</b> {perf.summary[0].path} ({perf.summary[0].total_ms} {" "}{t("ms GPU per real frame)")}{" "}{perf.summary.length > 1 &&
                          perf.summary
                            .slice(1)
                            .map((x) => t(" · {0} {1} ms", x.path, x.total_ms))
                            .join("")}
                      </div>
                    )}
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ textAlign: "left", opacity: 0.7 }}>
                          <th>{t("Path")}</th>
                          <th>{t("GPU ms")}</th>
                          <th>FPS</th>
                          <th>{t("Err")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {perf.sessions.map((x) => (
                          <tr key={x.log}>
                            <td>{x.path}</td>
                            <td>{x.total_ms ?? "—"}</td>
                            <td>
                              {x.real_fps ?? "—"}→{x.shown_fps ?? "—"}
                            </td>
                            <td style={{ color: x.errors ? "#ff7b72" : undefined }}>{x.errors}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ marginTop: "6px", opacity: 0.7 }}>
                      {" "}{t("GPU ms: ANR's GPU time per real frame (pair + generated frames), lower is better. Newest session first. Compare paths in the same scene for a fair result.")}{" "}</div>
                  </div>
                </PanelSectionRow>
              )}
              </>)}
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={showLog}>
                  {" "}{t("Show generator log")}{" "}</ButtonItem>
              </PanelSectionRow>
              {log && (
                <PanelSectionRow>
                  <pre style={{ ...small, whiteSpace: "pre-wrap", maxHeight: "240px", overflowY: "auto" }}>{log}</pre>
                </PanelSectionRow>
              )}
              </>}
            </>
          )}

          <PanelSectionRow>
            <ButtonItem layout="below" disabled={loadingStatus} onClick={() => void loadStatus(appid)}>
              {" "}{t("Refresh")}{" "}</ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

// ─── Benchmark (ANR FG test kit) ─────────────────────────────────────────────

const RUNNING_STAGES = ["starting", "download", "verify", "extract", "run"];

function BenchmarkSection() {
  const [bench, setBench] = useState<BenchState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setBench(await getBenchmark());
    } catch (e) {
      setBench({ status: "error", message: errorText(e), live: {} });
    }
  }, []);

  const running = RUNNING_STAGES.includes(bench?.live?.stage || "");

  useEffect(() => void load(), [load]);
  useEffect(() => {
    if (!running) return undefined;
    const id = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(id);
  }, [running, load]);

  const stage = bench?.live?.stage;
  const lastStage = useRef<string | undefined>(undefined);
  useEffect(() => {
    const was = lastStage.current;
    lastStage.current = stage;
    if (!was || !RUNNING_STAGES.includes(was)) return;
    if (stage === "done") toast(bench?.live?.message || t("Benchmark finished."));
    if (stage === "error") toast(t("Benchmark: {0}", bench?.live?.message));
  }, [stage]);

  const act = async (fn: () => Promise<{ status: string; message?: string }>) => {
    setBusy(true);
    try {
      const r = await fn();
      if (r.message) toast(r.message);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
      await load();
    }
  };

  const result = bench?.live?.result || bench?.result || null;
  const live = bench?.live || {};
  const pct =
    live.total && live.total > 0 ? Math.min(100, Math.round(((live.progress || 0) / live.total) * 100)) : null;
  const sizes = result ? Object.keys(result.table).sort((a, b) => parseInt(a) - parseInt(b)) : [];
  const paths = result
    ? Array.from(new Set(sizes.flatMap((s) => Object.keys(result.table[s])))).sort((a, b) => {
        const ms = (p: string) => result.table[sizes[0]]?.[p]?.ms ?? 1e9;
        return ms(a) - ms(b);
      })
    : [];

  return (
    <PanelSection title={t("Benchmark")}>
      <PanelSectionRow>
        <div style={small}>
          {" "}{t("Runs ANR's official test kit on this GPU: every compute path at 1080p, 1440p and 4K, timed and checked against reference frames, next to AMD FSR 3.1 frame generation. Downloads ~570 MB once; takes 5–15 min. Close games first and plug the device in.")}{" "}</div>
      </PanelSectionRow>

      {running ? (
        <>
          <PanelSectionRow>
            <div style={{ ...small, opacity: 1 }}>
              {live.message}
              {pct !== null && (
                <div style={{ marginTop: "6px", height: "6px", borderRadius: "3px", background: "rgba(255,255,255,0.15)" }}>
                  <div style={{ width: `${pct}%`, height: "100%", borderRadius: "3px", background: "#58a6ff" }} />
                </div>
              )}
              {live.stage === "download" && live.total ? (
                <div style={{ marginTop: "4px" }}>
                  {Math.round((live.progress || 0) / 2 ** 20)} / {Math.round(live.total / 2 ** 20)} {" "}{t("MB")}{" "}</div>
              ) : null}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={() => act(cancelBenchmark)}>
              {" "}{t("Stop the benchmark")}{" "}</ButtonItem>
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => act(startBenchmark)}>
            {result ? t("Run the benchmark again") : t("Run the benchmark")}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {live.stage === "error" && !running && (
        <PanelSectionRow>
          <div style={{ ...small, color: "#ff7b72" }}>{live.message}</div>
        </PanelSectionRow>
      )}

      {result && (
        <>
          <PanelSectionRow>
            <div style={{ ...small, opacity: 1 }}>
              <div style={{ marginBottom: "6px" }}>
                {result.gpu} · ANR {result.version} · {result.runs} {" "}{t("runs,")}{" "}{result.failed ?? 0} {" "}{t("failed")}{" "}</div>
              <div style={{ marginBottom: "6px" }}>
                <b>{t("Best:")}{" "}{result.best_path}</b>
                {result.auto_path && result.auto_path !== result.best_path
                  ? t(" (auto picks {0})", result.auto_path)
                  : result.auto_path
                  ? t(" (= auto)")
                  : ""}
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", opacity: 0.7 }}>
                    <th>{t("2X, ms · dB")}</th>
                    {sizes.map((s) => (
                      <th key={s}>{s}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paths.map((p) => (
                    <tr key={p} style={{ fontWeight: p === result.best_path ? 700 : 400 }}>
                      <td>{p}</td>
                      {sizes.map((s) => {
                        const e = result.table[s]?.[p];
                        return (
                          <td key={s}>
                            {e?.ms ?? "—"}
                            {e?.db ? <span style={{ opacity: 0.6 }}> · {e.db}</span> : null}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {Object.keys(result.fsr || {}).length > 0 && (
                    <tr style={{ opacity: 0.8 }}>
                      <td>FSR 3.1 FG</td>
                      {sizes.map((s) => (
                        <td key={s}>{result.fsr[s] ?? "—"}</td>
                      ))}
                    </tr>
                  )}
                </tbody>
              </table>
              <div style={{ marginTop: "6px", opacity: 0.7 }}>
                {" "}{t("ms: GPU time per real frame at 2X, lower is better. dB: match to reference frames, higher is better.")}{" "}</div>
            </div>
          </PanelSectionRow>
          {result.best_path && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || running}
                onClick={() => act(() => applyPathAll(result.best_path as string))}
              >
                {bench?.preferred_path === result.best_path
                  ? t("{0} is applied (re-apply to all games)", result.best_path)
                  : t("Use {0} in all games", result.best_path)}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {bench?.preferred_path && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || running} onClick={() => act(() => applyPathAll("auto"))}>
                {" "}{t("Back to auto in all games")}{" "}</ButtonItem>
            </PanelSectionRow>
          )}
        </>
      )}

      {!running && (bench?.kit_mb || 0) > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => act(deleteBenchmarkKit)}>
            {" "}{t("Delete the test kit (")}{bench?.kit_mb}{" "}{t("MB)")}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// ─── Help ────────────────────────────────────────────────────────────────────

function HelpSection() {
  return (
    <PanelSection title={t("How to use")}>
      <PanelSectionRow>
        <div style={small}>
          {" "}{t("1. Choose a game above and press Install Hub: the plugin copies its files and sets the launch options.")}{" "}<br />
          {" "}{t("2. 1 · Image quality: pick an upscaler (FSR 4 / FSR 4 Lite / NPU 900p/720p/576p → 1080p) or Off.")}{" "}<br />
          {" "}{t("3. 2 · Smoothness: pick a frame generator. Lossless Scaling works in any game; ANR FG and XeFG replace DLSS Frame Generation, so turn that on in the game.")}{" "}<br />
          {" "}{t("4. Follow \"What to set in the game\" in the game card, start the game, turn in-game V-Sync off.")}{" "}<br />
          {" "}{t("Restore game removes everything the plugin changed. OptiScaler's menu: Insert key.")}{" "}</div>
      </PanelSectionRow>
    </PanelSection>
  );
}

function LegacyBanner() {
  const [legacy, setLegacy] = useState<{ installed: boolean; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await getLegacyInfo();
      setLegacy({ installed: Boolean(r.legacy_installed), name: r.legacy_name || "Decky ANR" });
    } catch {
      setLegacy(null);
    }
  }, []);
  useEffect(() => void load(), [load]);
  if (!legacy?.installed) return null;
  const remove = async () => {
    setBusy(true);
    try {
      await DeckyBackend.call("utilities/uninstall_plugin", legacy.name);
      toast(t("{0} removed. Your game profiles were carried over.", legacy.name));
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
      await load();
    }
  };
  return (
    <PanelSection title={t("Renamed")}>
      <PanelSectionRow>
        <div style={banner("rgba(88,166,255,0.18)")}>
          <b>{legacy.name}</b> {" "}{t("is now")}{" "}<b>{TITLE}</b>{t(". Your game profiles, ANR packages and XeFG files were carried over. Remove the old plugin so the two do not both manage the same games.")}{" "}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={remove}>
          {busy ? t("Removing…") : t("Remove the old {0} plugin", legacy.name)}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function Fsr4Libraries({ onImported }: { onImported: () => void }) {
  const [library, setLibrary] = useState<Fsr4Library | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setLibrary(await getFsr4Library()); } catch (e) { toast(errorText(e)); }
  }, []);
  useEffect(() => void load(), [load]);
  const importFiles = async (kind: "driver" | "zip") => {
    let path: string;
    try {
      const file = await openFilePicker(FileSelectionType.FILE,
        library?.home || "/home", true, true, undefined,
        [kind === "driver" ? "exe" : "zip"], false, false);
      path = file.realpath || file.path;
    } catch { return; }
    setBusy(true);
    try {
      const result = await (kind === "driver" ? extractFsr4Driver(path)
        : importFsr4Libraries(path));
      toast(result.message || result.status);
      if (result.status === "success") { await load(); onImported(); }
    } catch (e) { toast(errorText(e)); }
    finally { setBusy(false); }
  };
  return (
    <PanelSection title={t("FSR 4 libraries")}>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void importFiles("driver")}
          description={library?.available
            ? t("Imported AMD library {0}. Select a newer driver to update. Closed games using Lite update automatically.", library.version)
            : t("Download an AMD Windows driver with FSR 4 Lite, then select its .exe here. Extracts and imports the libraries without installing the driver. Internet is needed only if portable 7-Zip is missing.")}>
          {busy ? t("Processing libraries… please wait") : t("Extract FSR 4 libraries from driver (.exe)")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void importFiles("zip")}
          description={t("Already extracted? Choose a ZIP containing amdxcffx64.dll and amdvkffx64.dll. For a new game, choose FSR 4 Lite in Upscaler after importing.")}>
          {" "}{t("Import libraries from ZIP")}{" "}</ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function FullBundleSection({ onImported }: { onImported: () => void }) {
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<{ path: string; name: string } | null>(null);
  useEffect(() => {
    void findLocalBundle().then((r) => {
      if (r.status === "success" && r.path && r.name) setFound({ path: r.path, name: r.name });
    }).catch(() => {});
  }, []);
  const runImport = async (path: string) => {
    setBusy(true);
    try {
      const r = await importAllInOneBundle(path);
      toast(r.message || r.status);
      if (r.status === "success") onImported();
    } catch (e) { toast(errorText(e)); }
    finally { setBusy(false); }
  };
  const pickBundle = async () => {
    let path: string;
    try {
      const file = await openFilePicker(FileSelectionType.FILE, "/home", true, true, undefined, ["zip"], false, false);
      path = file.realpath || file.path;
    } catch { return; }
    await runImport(path);
  };
  return (
    <PanelSection title={t("All-in-one backup bundle")}>
      {found && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => void runImport(found.path)}
            description={t("Found offline bundle in Downloads. Restores NPU-SR + models, FSR 4, and Lossless Scaling without internet.")}>
            {busy ? t("Importing…") : t("Restore from {0}", found.name)}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void pickBundle()}
          description={t("One-click restore after reinstalling: choose your personal bundle ZIP to install NPU-SR + models, FSR 4, and Lossless Scaling at once.")}>
          {busy ? t("Importing…") : t("Import full bundle (NPU + FSR 4 + Lossless)")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function NpuPackageSection({ onImported }: { onImported: () => void }) {
  const [pkg, setPkg] = useState<NpuPackage | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setPkg(await getNpuPackage()); } catch (e) { toast(errorText(e)); }
  }, []);
  useEffect(() => void load(), [load]);
  const importZip = async () => {
    let path: string;
    try {
      const file = await openFilePicker(FileSelectionType.FILE, pkg?.home || "/home", true, true, undefined,
        ["zip"], false, false);
      path = file.realpath || file.path;
    } catch { return; }
    setBusy(true);
    try {
      const r = await importNpuPackage(path);
      toast(r.message || r.status);
      if (r.status === "success") { await load(); onImported(); }
    } catch (e) { toast(errorText(e)); }
    finally { setBusy(false); }
  };
  const installGithub = async () => {
    setBusy(true);
    try {
      const r = await installNpuFromGithub();
      toast(r.message || r.status);
      if (r.status === "success") { await load(); onImported(); }
    } catch (e) { toast(errorText(e)); }
    finally { setBusy(false); }
  };
  const warn = { ...small, color: "#ffd866" };
  return (
    <PanelSection title={t("NPU upscaler (Ryzen AI)")}>
      <PanelSectionRow>
        <Field label={t("NPU package")} focusable>
          {pkg === null ? "…" : pkg.installed ? t("{0} · {1} models", pkg.version ?? "?", pkg.models ?? 0) : t("not installed")}
        </Field>
      </PanelSectionRow>
      {pkg && !pkg.npu_device && (
        <PanelSectionRow><div style={warn}>{t("No Ryzen AI NPU found (/dev/accel). NPU upscaling needs a Ryzen AI APU and the amdxdna kernel driver.")}</div></PanelSectionRow>
      )}
      {pkg && !pkg.runtime_ok && (
        <PanelSectionRow><div style={warn}>{t("AMD Ryzen AI 1.9 runtime is missing (not redistributable). Install it to: {0}.", (pkg.runtime_missing ?? []).join(", "))}</div></PanelSectionRow>
      )}
      {pkg?.installed && !pkg.layer_registered && (
        <PanelSectionRow><div style={warn}>{t("One-time step: in Desktop Mode open Konsole and run")}{" "}<code>{pkg.layer_command}</code></div></PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void installGithub()}
          description={t("Downloads the latest npu-sr release (Vulkan layer, NPU service, models) from GitHub, verifies SHA-256, and registers the layer automatically without sudo.")}>
          {busy ? t("Downloading…") : t("Download / update NPU-SR from GitHub")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void importZip()}
          description={t("Private package you prepare yourself (npu-sr ZIP: Vulkan layer, NPU service, models). Checked by SHA-256; replaces the installed version, the selected model and game list are kept.")}>
          {busy ? t("Importing…") : t("Import NPU package (ZIP)")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  const focusRoot = useRef<HTMLDivElement>(null);
  useEffect(() => registerFocusRoot(focusRoot.current), []);
  const [fsrRevision, setFsrRevision] = useState(0);
  const [showTools, setShowTools] = useState(false);
  const [info, setInfo] = useState<AnrInfo | null>(null);
  const reload = useCallback(async () => {
    try {
      setInfo(await getAnrInfo());
    } catch (e) {
      toast(errorText(e));
    }
  }, []);
  useEffect(() => void reload(), [reload]);

  return (
    <div ref={focusRoot} style={{ display: "contents" }}>
      <LegacyBanner />
      <GameSection key={fsrRevision} info={info} />
      <PanelSection title={t("Tools")}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowTools(value => !value)}
            description={t("Private libraries (FSR 4 Lite, Lossless Scaling, NPU), plugin updates, benchmarks and help.")}>
            {showTools ? t("Hide libraries and updates") : t("Libraries and updates")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {showTools && <>
        <PackageSection info={info} reload={reload} />
        <FullBundleSection onImported={() => setFsrRevision((v) => v + 1)} />
        <Fsr4Libraries onImported={() => setFsrRevision((v) => v + 1)} />
        <NpuPackageSection onImported={() => setFsrRevision((v) => v + 1)} />
        <BenchmarkSection />
        <HelpSection />
      </>}
    </div>
  );
}

function LocalizedContent() {
  const language = useSyncExternalStore(subscribeLanguage, getLanguage, getLanguage);
  return <Content key={language} />;
}

export default definePlugin(() => {
  const stopLanguage = initializeLanguage(getUiLanguage);
  // The backend checks GitHub at start and every 6 hours and emits this once per new version.
  const onUpdate = (kind: string, version: string) => {
    const what: Record<string, string> = {
      plugin: t("{0} {1} is out: open the plugin to update.", TITLE, version),
      anr_auto: t("ANR FG {0} updated automatically. Running games update after closing.", version),
      anr: t("ANR FG {0} is out: open {1} to download it.", version, TITLE),
      lsfg: t("lsfg-vk {0} is out: open {1} to update it.", version, TITLE),
      xefg: t("XeFG {0} is out: it comes with the next {1} update.", version, TITLE),
      fsr4: t("A newer FSR 4 DLL ({0}) is available: open {1} to update your games.", version, TITLE),
    };
    toast(what[kind] || t("{0} {1} is out.", kind, version));
  };
  const listener = addEventListener<[string, string]>("anr_update_available", onUpdate);
  return {
    name: TITLE,
    titleView: <div style={{ fontSize: "16px", lineHeight: "20px", fontWeight: 700 }}>FrameGen Hub</div>,
    content: <LocalizedContent />,
    icon: <MdAutoAwesome />,
    onDismount() {
      stopLanguage();
      removeEventListener("anr_update_available", listener);
    },
  };
});
