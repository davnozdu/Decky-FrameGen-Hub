import { callable as rawCallable } from "@decky/api";
import { localizeResult } from "./i18n";
const callable = <Args extends any[] = [], Return = void>(route: string) => {
  const call = rawCallable<Args, Return>(route);
  return async (...args: Args): Promise<Return> => localizeResult(await call(...args));
};

export type Result = { status: "success" | "error"; message?: string; output?: string };

export type AnrInfo = Result & {
  installed?: boolean;
  version?: string | null;
  versions?: string[];
  built_at?: string | null;
  optiscaler?: string | null;
};

export type GameEntry = { appid: string; name: string; installed: boolean; patched: boolean };

export type Candidate = { dir: string; exe: string };

export type GameStatus = Result & {
  appid?: string;
  name?: string;
  installed?: boolean;
  patched?: boolean;
  managed?: boolean;
  mode?: "full" | "addon" | null;
  proxy?: string | null;
  optiscaler_required?: boolean;
  dxgi_fix_enabled?: boolean;
  dxgi_fix_available?: boolean;
  signed_optiscaler?: boolean;
  optiscaler_core?: "package" | "signed" | "signed095" | "nightly";
  signed095_available?: boolean;
  optiscaler_cores?: { fg: string; ls: string };
  requires_signed_core?: boolean;
  fg_available?: boolean;
  target_dir?: string;
  target_rel?: string;
  game_version?: string | null;
  active_version?: string | null;
  generator?: { choice: "anr" | "xefg" | "lsfg" | "off" | "custom"; provider: string; build: string; ready: boolean; available: boolean };
  lsfg?: LsfgProfile | null;
  settings?: Record<string, string | null>;
  log_file?: string | null;
  candidates?: Candidate[];
  suggested_dir?: string;
  conflict?: string | null;
  running?: boolean;
  proton?: { tool: string | null; source: "game" | "default"; prefix: string | null; native: boolean };
};

export type NpuSrLive = { in?: string; out?: string; frames?: number; npu_frames?: number; fallback_frames?: number;
  npu_ms?: number; connected?: boolean };
export type NpuSrModel = { file: string; label: string; note?: string };
export type NpuSrStatus = Result & { available?: boolean; missing?: string[]; enabled?: boolean; service?: string;
  model?: string | null; models?: NpuSrModel[]; live?: NpuSrLive | null };

export type PatchResult = Result & { launch_options?: string; mode?: string; proxy?: string | null };

export const getAnrInfo = callable<[], AnrInfo>("get_anr_info");
export const installBundled = callable<[], Result & { version?: string }>("install_bundled");
export const updateFromGithub = callable<[], Result & { version?: string }>("update_from_github");
export const setActiveVersion = callable<[version: string], Result>("set_active_version");
export const syncShortcuts = callable<[shortcuts: import("./steam").LiveShortcut[]], Result>("sync_shortcuts");
export const listGames = callable<[], Result & { games: GameEntry[] }>("list_games");
export const updateNightlyOptiscaler = callable<[appid: string], Result>("update_nightly_optiscaler");
export const setOptiscalerCore = callable<[appid: string, core: string, current: string], PatchResult>("set_optiscaler_core");
export const setSignedOptiscaler = callable<[appid: string, enabled: boolean, current: string], PatchResult>("set_signed_optiscaler");
export const setDxgiFix = callable<[appid: string, enabled: boolean, current: string], PatchResult>("set_dxgi_fix");
export const recommendedLaunchOptions = callable<[appid: string, current: string], PatchResult>("recommended_launch_options");
export const getNpuSr = callable<[appid: string], NpuSrStatus>("get_npu_sr");
export const setNpuSr = callable<[appid: string, enabled: boolean, current: string], PatchResult>("set_npu_sr");
export const setNpuSrModel = callable<[model: string], Result>("set_npu_sr_model");
export const getGameStatus = callable<[appid: string], GameStatus>("get_game_status");
export const patchGame = callable<
  [appid: string, current_launch_options: string, target_dir: string],
  PatchResult
>("patch_game");
export const unpatchGame = callable<[appid: string, current_launch_options: string], PatchResult>(
  "unpatch_game"
);
export const setGameSetting = callable<[appid: string, key: string, value: string], Result>(
  "set_game_setting"
);
export const readGameLog = callable<[appid: string, lines: number], Result & { log?: string; path?: string }>(
  "read_game_log"
);
export const logError = callable<[string], void>("log_error");

export type UpdateInfo = Result & {
  checked_at?: string;
  errors?: string[];
  anr_latest?: string | null;
  anr_update?: boolean;
  anr_notes_url?: string;
  plugin_current?: string;
  plugin_latest?: string | null;
  plugin_update?: boolean;
  plugin_url?: string;
  plugin_hash?: string;
  plugin_notes_url?: string;
  xefg_current?: string;
  xefg_latest?: string | null;
  xefg_update?: boolean;
  lsfg_current?: string | null;
  lsfg_latest?: string | null;
  lsfg_update?: boolean;
  fsr4_latest?: string | null;
  fsr4_update_games?: string[];
};

export const checkUpdates = callable<[force: boolean], UpdateInfo>("check_updates");
export const listOutdatedGames = callable<
  [],
  Result & { games: { appid: string; name: string; version: string }[]; active_version?: string | null }
>("list_outdated_games");
export const updateAllGames = callable<[], Result & { updated?: string[]; skipped?: string[] }>("update_all_games");

export type PerfSession = {
  log: string;
  started: string;
  path: string;
  resolution: string | null;
  multiplier: number | null;
  pair_ms: number | null;
  gen_ms: number | null;
  total_ms: number | null;
  real_fps: number | null;
  shown_fps: number | null;
  evaluations: number;
  errors: number;
};

export const getPerformance = callable<
  [appid: string, limit: number],
  Result & {
    sessions: PerfSession[];
    summary?: { path: string; sessions: number; total_ms: number; real_fps: number | null }[];
  }
>("get_performance");

export type BenchEntry = { ms?: number; db?: number; passes?: boolean; auto?: boolean };
export type BenchResult = {
  version: string;
  date: string;
  gpu: string | null;
  runs: number;
  failed: number | null;
  best_path: string | null;
  auto_path: string | null;
  table: Record<string, Record<string, BenchEntry>>;
  fsr: Record<string, number>;
  file?: string;
};
export type BenchState = Result & {
  live: { stage?: string; message?: string; progress?: number; total?: number; result?: BenchResult };
  result?: BenchResult | null;
  preferred_path?: string | null;
  kit_mb?: number;
};

export const startBenchmark = callable<[], Result>("start_benchmark");
export const cancelBenchmark = callable<[], Result>("cancel_benchmark");
export const getBenchmark = callable<[], BenchState>("get_benchmark");
export const applyPathAll = callable<[path: string], Result>("apply_path_all");
export const deleteBenchmarkKit = callable<[], Result>("delete_benchmark_kit");

export type UpscalerInfo = Result & {
  choice?: string;
  watermark?: boolean;
  rdna4?: boolean;
  fsr4_lite_available?: boolean;
  signed_sdk?: boolean;
  fsr4_source?: { path: string; version: string; own_prefix: boolean; source?: string } | null;
  gpu_family?: "rdna2" | "rdna3" | "rdna4" | "unknown";
  proton_experimental?: boolean;
  options?: { value: string; label: string }[];
  render_quality?: string;
  render_options?: { value: string; label: string; ratio: number | null }[];
  output?: [number, number] | null;
};
export const setRenderQuality = callable<[appid: string, choice: string], Result>("set_render_quality");
export const getUpscaler = callable<[appid: string], UpscalerInfo>("get_upscaler");
export const setUpscaler = callable<
  [appid: string, choice: string, watermark: boolean],
  Result & { need_ffx4_upgrade?: boolean }
>("set_upscaler");

export const getOptiSettings = callable<[appid: string], Result & { settings: Record<string, string> }>(
  "get_opti_settings"
);
export const setOptiSetting = callable<[appid: string, key: string, value: string], Result & { dropped?: string[] }>(
  "set_opti_setting"
);
export const copyProfile = callable<[appid: string, from_appid: string], Result>("copy_profile");
export const resetProfile = callable<[appid: string], Result>("reset_profile");

export const setFrameGenerator = callable<[appid: string, choice: string], Result>("set_frame_generator");

export const getLegacyInfo = callable<[], Result & { legacy_installed?: boolean; legacy_name?: string }>("get_legacy_info");

export type LsfgProfile = { active_in: string[]; multiplier: number; flow_scale: number; performance_mode: boolean };
export type LsfgStatus = Result & {
  installed?: boolean; version?: string | null; dll?: string | null;
  dll_source?: "imported" | "steam"; home?: string;
  dll_state?: "ok" | "wrong_branch" | "missing"; profile?: LsfgProfile | null;
};
export const getLsfgStatus = callable<[appid: string], LsfgStatus>("get_lsfg_status");
export const installLsfg = callable<[], Result & { version?: string }>("install_lsfg");
export const setGeneratorMode = callable<
  [appid: string, choice: string, multiplier: number, flow_scale: number, performance_mode: boolean],
  Result
>("set_generator_mode");
export const refreshFsr4Dlls = callable<[], Result>("refresh_fsr4_dlls");

export type Fsr4Library = Result & { available?: boolean; version?: string | null; home?: string };
export const getFsr4Library = callable<[], Fsr4Library>("get_fsr4_library");
export const importFsr4Libraries = callable<[archive: string], Result & { version?: string }>("import_fsr4_libraries");
export const extractFsr4Driver = callable<[driver: string], Result>("extract_fsr4_driver");

export const importLsfgLibrary = callable<[filename: string], Result>("import_lsfg_library");

export const getUiLanguage = callable<[], { language?: string }>("get_ui_language");

export const getAutoUpdateAnr = callable<[], { enabled: boolean }>("get_auto_update_anr");
export const setAutoUpdateAnr = callable<[enabled: boolean], Result>("set_auto_update_anr");
