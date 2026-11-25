// SteamClient helpers for reading and writing a game's launch options.

declare const SteamClient: any;

export const getLaunchOptions = (appId: number): Promise<string> =>
  new Promise((resolve) => {
    if (typeof SteamClient === "undefined" || !SteamClient?.Apps?.RegisterForAppDetails) {
      resolve("");
      return;
    }
    let settled = false;
    let unregister = () => {};
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      unregister();
      resolve("");
    }, 5000);
    const registration = SteamClient.Apps.RegisterForAppDetails(
      appId,
      (details: { strLaunchOptions?: string }) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        // Unregistering inside the callback can race the registration's return value.
        window.setTimeout(() => unregister(), 0);
        resolve(details?.strLaunchOptions ?? (details as any)?.strShortcutLaunchOptions ?? "");
      }
    );
    unregister = () => registration?.unregister?.();
  });

export const setLaunchOptions = (appId: number, options: string): void => {
  if (typeof SteamClient !== "undefined" && SteamClient?.Apps?.SetAppLaunchOptions) {
    SteamClient.Apps.SetAppLaunchOptions(appId, options);
  }
};

export const getResolutionOverride = (appId: number): Promise<string> =>
  new Promise((resolve) => {
    if (typeof SteamClient === "undefined" || !SteamClient?.Apps?.RegisterForAppDetails) {
      resolve("");
      return;
    }
    let settled = false;
    let unregister = () => {};
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      unregister();
      resolve("");
    }, 3000);
    const registration = SteamClient.Apps.RegisterForAppDetails(
      appId,
      (details: { strDisplayResolutionOverride?: string }) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        window.setTimeout(() => unregister(), 0);
        resolve(details?.strDisplayResolutionOverride ?? "");
      }
    );
    unregister = () => registration?.unregister?.();
  });

export const setResolutionOverride = (appId: number, res: string): boolean => {
  if (typeof SteamClient !== "undefined" && SteamClient?.Apps?.SetAppResolutionOverride) {
    SteamClient.Apps.SetAppResolutionOverride(appId, res);
    return true;
  }
  return false;
};

// Clipboard in Game Mode: execCommand on a hidden input works where navigator.clipboard often does not.
export const copyText = async (text: string): Promise<boolean> => {
  const input = document.createElement("input");
  input.value = text;
  input.style.position = "absolute";
  input.style.left = "-9999px";
  document.body.appendChild(input);
  try {
    input.focus();
    input.select();
    if (document.execCommand("copy")) return true;
  } catch {
    // fall through to the async clipboard API
  } finally {
    document.body.removeChild(input);
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

// Steam may keep new shortcuts in memory until shutdown; don't require a restart.
export type LiveShortcut = { appid: number; appname: string; exe: string; StartDir: string; LaunchOptions: string };
export const getNonSteamShortcuts = async (): Promise<LiveShortcut[]> => {
  const store = (window as any).appStore;
  if (!store?.allApps || typeof SteamClient?.Apps?.RegisterForAppDetails !== "function") return [];
  const apps = store.allApps.filter((app: any) => app.app_type === 1073741824 || app.BIsShortcut?.());
  const results = await Promise.all(apps.map((app: any) => new Promise<LiveShortcut | null>((resolve) => {
    let registration: any;
    let settled = false;
    const finish = (value: LiveShortcut | null) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      window.setTimeout(() => registration?.unregister?.(), 0);
      resolve(value);
    };
    const timer = window.setTimeout(() => finish(null), 3000);
    registration = SteamClient.Apps.RegisterForAppDetails(app.appid, (details: any) => {
      if (!details?.strShortcutExe) return;
      finish({ appid: app.appid, appname: app.display_name || "", exe: details.strShortcutExe,
               StartDir: details.strShortcutStartDir || "",
               LaunchOptions: details.strLaunchOptions ?? details.strShortcutLaunchOptions ?? "" });
    });
  })));
  return results.filter((value): value is LiveShortcut => value !== null);
};
