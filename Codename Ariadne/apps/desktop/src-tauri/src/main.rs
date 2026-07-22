// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Minimal binary entry point; all application composition lives in the library.

fn main() {
    ariadne_desktop_lib::run();
}
