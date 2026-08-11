//! Monarch Command Center — native desktop shell (bundled app).
//!
//! The window opens on the **bundled** app (`index.html`): it plays the local
//! intro and then reveals the dashboard in the same document — no navigation,
//! no download. Live data reaches the app as JSON over Tailscale via ordinary
//! fetch/SSE (`apiBase.js` rewrites `/api` to the backend origin, pinned by the
//! CSP `connect-src`). The privileged webview content stays fully local and
//! immutable; only JSON crosses the wire.
//!
//! Security posture (see desktop/README.md for the full rationale):
//!   * Only local, bundled-asset origins are renderable. The navigation guard
//!     refuses EVERY remote origin, so no backend response can navigate the
//!     webview to attacker-controlled content — the original full-isolation
//!     posture, restored from the (2026-07-20) hybrid that trusted one remote
//!     origin. Remote data still arrives via fetch/SSE, which `on_navigation`
//!     does not gate.
//!   * The capability set is minimal: core defaults + local notifications. No
//!     shell, fs, http, or dialog access is granted. Because the window never
//!     leaves the local origin, the `default` (local) capability covers native
//!     notifications; no remote capability is needed.

use tauri::{WebviewUrl, WebviewWindowBuilder};

/// Returns `true` only for the local, bundled-asset origins Tauri itself uses
/// (`tauri://localhost` on macOS, `http://tauri.localhost` on Linux/Windows)
/// and its internal IPC origin. Everything else — every remote origin — is
/// refused. This IS the navigation allow-list.
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
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(move |app| {
            // Build the main window in code so we can attach the navigation
            // guard. `WebviewUrl::App` resolves to the bundled index.html.
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Monarch Command Center")
                .inner_size(1320.0, 880.0)
                .min_inner_size(900.0, 600.0)
                .center()
                .background_color(tauri::webview::Color(4, 4, 15, 255)) // #04040F — no white flash on launch
                .on_navigation(move |url| {
                    // Local origins only: refuse every remote navigation.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_only_local_bundled_origins() {
        assert!(is_local_origin(&tauri::Url::parse("tauri://localhost").unwrap()));
        assert!(is_local_origin(&tauri::Url::parse("http://tauri.localhost/x").unwrap()));
        assert!(is_local_origin(&tauri::Url::parse("https://ipc.localhost/y").unwrap()));
    }

    #[test]
    fn denies_all_remotes_including_the_former_console_and_credential_smuggling() {
        // The old hybrid trusted a console origin; the bundle model trusts none.
        assert!(!is_local_origin(&tauri::Url::parse("https://host.ts.net:8443/").unwrap()));
        assert!(!is_local_origin(&tauri::Url::parse("https://evil.com").unwrap()));
        // credentials-in-URL: host is evil.com, not a local origin
        assert!(!is_local_origin(&tauri::Url::parse("https://tauri.localhost@evil.com").unwrap()));
        // a real remote http host that merely resembles the local virtual host
        assert!(!is_local_origin(&tauri::Url::parse("http://tauri.localhost.evil.com").unwrap()));
    }
}
