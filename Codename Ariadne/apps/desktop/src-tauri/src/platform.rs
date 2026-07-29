//! Small operating-system adapter for user-mediated browser handoff.

#[cfg(target_os = "macos")]
mod macos {
    use objc2_app_kit::NSWorkspace;
    use objc2_foundation::{NSString, NSURL};

    pub fn open_external_url(value: &str) -> bool {
        let value = NSString::from_str(value);
        NSURL::URLWithString(&value).is_some_and(|url| NSWorkspace::sharedWorkspace().openURL(&url))
    }
}

#[cfg(target_os = "macos")]
pub use macos::open_external_url;

#[cfg(not(target_os = "macos"))]
pub fn open_external_url(_value: &str) -> bool {
    false
}
