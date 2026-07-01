// Prevents an extra console window on Windows in release. No-op on macOS/Linux.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    command_center_lib::run()
}
