//! Monarch Command Center — native desktop shell.
//!
//! Security posture (see desktop/README.md for the full rationale):
//!   * The webview only ever renders the **bundled, local** frontend
//!     (`frontendDist`). No remote URL is ever loaded into the privileged
//!     webview — only JSON crosses the wire (to the monarch backend over
//!     Tailscale), constrained by the CSP `connect-src` allow-list.
//!   * A navigation guard refuses any attempt to navigate the top-level
//!     webview to a remote origin — defence-in-depth behind the CSP.
//!   * The capability set is minimal: core defaults + local notifications.
//!     No shell, fs, http, or dialog access is granted.

use tauri::{WebviewUrl, WebviewWindowBuilder};

/// Returns `true` only for the local, bundled-asset origins Tauri itself uses
/// (`tauri://localhost` on macOS, `http://tauri.localhost` on Linux/Windows)
/// and its internal IPC origin. Everything else is refused.
fn is_local_origin(url: &tauri::Url) -> bool {
    match url.scheme() {
        // macOS custom protocol + Tauri's internal IPC scheme.
        "tauri" | "ipc" => true,
        // Linux/Windows serve bundled assets over a virtual http(s) host.
        "http" | "https" => matches!(
            url.host_str(),
            Some("tauri.localhost") | Some("ipc.localhost")
        ),
        _ => false,
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            // Build the main window in code so we can attach the navigation
            // guard. `WebviewUrl::App` resolves to the bundled index.html.
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Monarch Command Center")
                .inner_size(1320.0, 880.0)
                .min_inner_size(900.0, 600.0)
                .center()
                .on_navigation(|url| {
                    let allowed = is_local_origin(url);
                    if !allowed {
                        eprintln!("[command-center] blocked navigation to: {url}");
                    }
                    allowed
                })
                .build()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the Monarch Command Center desktop app");
}
