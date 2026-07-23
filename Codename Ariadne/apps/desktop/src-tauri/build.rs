//! Tauri build entry point.
//!
//! Runtime composition stays in the application crate; this helper only emits
//! the platform metadata and build directives required by Tauri.

fn main() {
    tauri_build::build()
}
