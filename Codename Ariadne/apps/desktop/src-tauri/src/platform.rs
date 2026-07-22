//! Small operating-system adapter for browser handoff and lock-relevant events.
//!
//! Platform notifications do not mutate vault state directly; they request the
//! supervisor's normal lock path so key revocation and sidecar shutdown remain
//! centralized.

#[cfg(target_os = "macos")]
mod macos {
    use std::ptr::NonNull;

    use block2::RcBlock;
    use objc2::{
        rc::Retained,
        runtime::{AnyObject, ProtocolObject},
    };
    use objc2_app_kit::{
        NSWorkspace, NSWorkspaceDidWakeNotification, NSWorkspaceScreensDidSleepNotification,
        NSWorkspaceScreensDidWakeNotification, NSWorkspaceSessionDidBecomeActiveNotification,
        NSWorkspaceSessionDidResignActiveNotification, NSWorkspaceWillSleepNotification,
    };
    use objc2_foundation::{
        NSNotification, NSNotificationCenter, NSNotificationName, NSObjectProtocol, NSString, NSURL,
    };

    use crate::core::CoreSupervisor;

    type Observer = Retained<ProtocolObject<dyn NSObjectProtocol>>;

    pub fn open_external_url(value: &str) -> bool {
        let value = NSString::from_str(value);
        NSURL::URLWithString(&value).is_some_and(|url| NSWorkspace::sharedWorkspace().openURL(&url))
    }

    pub struct PlatformSecurityObservers {
        center: Retained<NSNotificationCenter>,
        observers: Vec<Observer>,
    }

    impl PlatformSecurityObservers {
        /// Retain observation tokens for exactly the lifetime of the application state.
        pub fn install(supervisor: CoreSupervisor) -> Self {
            let workspace = NSWorkspace::sharedWorkspace();
            let center = workspace.notificationCenter();
            // SAFETY: these are immutable AppKit notification-name constants
            // available on every supported macOS deployment target.
            let names = unsafe {
                [
                    NSWorkspaceWillSleepNotification,
                    NSWorkspaceDidWakeNotification,
                    NSWorkspaceScreensDidSleepNotification,
                    NSWorkspaceScreensDidWakeNotification,
                    NSWorkspaceSessionDidResignActiveNotification,
                    NSWorkspaceSessionDidBecomeActiveNotification,
                ]
            };
            let observers = names
                .into_iter()
                .map(|name| observe(&center, name, supervisor.clone()))
                .collect();
            Self { center, observers }
        }
    }

    impl Drop for PlatformSecurityObservers {
        fn drop(&mut self) {
            for observer in self.observers.drain(..) {
                let observer: &ProtocolObject<dyn NSObjectProtocol> = &observer;
                let observer: &AnyObject = observer.as_ref();
                // SAFETY: every token was returned by this notification center and
                // remains alive for the duration of the removal call.
                unsafe { self.center.removeObserver(observer) };
            }
        }
    }

    fn observe(
        center: &NSNotificationCenter,
        name: &NSNotificationName,
        supervisor: CoreSupervisor,
    ) -> Observer {
        let callback: RcBlock<dyn Fn(NonNull<NSNotification>)> =
            RcBlock::new(move |_notification| {
                supervisor.request_system_lock();
            });
        // SAFETY: the name is an AppKit static, no object filter is used, delivery
        // occurs on the posting thread, and the copied block captures only Send +
        // Sync Rust state with process-lifetime ownership.
        unsafe {
            center.addObserverForName_object_queue_usingBlock(Some(name), None, None, &callback)
        }
    }
}

#[cfg(target_os = "macos")]
pub use macos::PlatformSecurityObservers;

#[cfg(target_os = "macos")]
pub use macos::open_external_url;

#[cfg(not(target_os = "macos"))]
pub struct PlatformSecurityObservers;

#[cfg(not(target_os = "macos"))]
impl PlatformSecurityObservers {
    pub fn install(_supervisor: crate::core::CoreSupervisor) -> Self {
        Self
    }
}

#[cfg(not(target_os = "macos"))]
pub fn open_external_url(_value: &str) -> bool {
    false
}
