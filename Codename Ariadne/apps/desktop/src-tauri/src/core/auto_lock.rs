use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

use tokio::time::MissedTickBehavior;

use super::CoreSupervisor;

const DEFAULT_AUTO_LOCK_TIMEOUT: Duration = Duration::from_secs(300);
const IDLE_POLL_INTERVAL: Duration = Duration::from_secs(1);

#[derive(Clone, Default)]
pub struct AppActivity {
    focused: Arc<AtomicBool>,
}

impl AppActivity {
    pub fn set_focused(&self, focused: bool) {
        self.focused.store(focused, Ordering::Release);
    }

    fn is_focused(&self) -> bool {
        self.focused.load(Ordering::Acquire)
    }
}

pub fn spawn_auto_lock(supervisor: CoreSupervisor, activity: AppActivity) {
    tauri::async_runtime::spawn(async move {
        let mut policy = IdleLockPolicy::new(DEFAULT_AUTO_LOCK_TIMEOUT);
        let mut ticker = tokio::time::interval(IDLE_POLL_INTERVAL);
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);

        loop {
            ticker.tick().await;
            let should_lock = policy.observe(
                Instant::now(),
                supervisor.vault_is_unlocked(),
                activity.is_focused(),
                platform_idle_seconds(),
            );
            if should_lock {
                let _ = supervisor.lock_current_vault().await;
            }
        }
    });
}

struct IdleLockPolicy {
    timeout: Duration,
    fallback_deadline: Option<Instant>,
}

impl IdleLockPolicy {
    fn new(timeout: Duration) -> Self {
        Self {
            timeout,
            fallback_deadline: None,
        }
    }

    fn observe(
        &mut self,
        now: Instant,
        vault_unlocked: bool,
        app_focused: bool,
        platform_idle_seconds: Option<f64>,
    ) -> bool {
        if !vault_unlocked {
            self.fallback_deadline = None;
            return false;
        }

        let deadline = self
            .fallback_deadline
            .get_or_insert_with(|| now + self.timeout);
        if app_focused && let Some(idle_seconds) = valid_idle_seconds(platform_idle_seconds) {
            if idle_seconds >= self.timeout.as_secs_f64() {
                self.fallback_deadline = None;
                return true;
            }
            *deadline = now + Duration::from_secs_f64(self.timeout.as_secs_f64() - idle_seconds);
        }

        if self
            .fallback_deadline
            .is_some_and(|deadline| now >= deadline)
        {
            self.fallback_deadline = None;
            return true;
        }
        false
    }
}

fn valid_idle_seconds(value: Option<f64>) -> Option<f64> {
    value.filter(|seconds| seconds.is_finite() && *seconds >= 0.0)
}

#[cfg(target_os = "macos")]
fn platform_idle_seconds() -> Option<f64> {
    use objc2_core_graphics::{CGEventSource, CGEventSourceStateID, CGEventType};

    valid_idle_seconds(Some(CGEventSource::seconds_since_last_event_type(
        CGEventSourceStateID::CombinedSessionState,
        CGEventType(u32::MAX),
    )))
}

#[cfg(not(target_os = "macos"))]
fn platform_idle_seconds() -> Option<f64> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn background_inactivity_locks_at_the_fallback_deadline() {
        let now = Instant::now();
        let mut policy = IdleLockPolicy::new(Duration::from_secs(30));

        assert!(!policy.observe(now, true, false, None));
        assert!(!policy.observe(now + Duration::from_secs(29), true, false, None));
        assert!(policy.observe(now + Duration::from_secs(30), true, false, None));
        assert!(!policy.observe(now + Duration::from_secs(31), false, false, None));
    }

    #[test]
    fn focused_activity_extends_but_never_disables_the_deadline() {
        let now = Instant::now();
        let mut policy = IdleLockPolicy::new(Duration::from_secs(30));

        assert!(!policy.observe(now, true, true, Some(20.0)));
        assert!(!policy.observe(now + Duration::from_secs(5), true, true, Some(0.0)));
        assert!(!policy.observe(now + Duration::from_secs(34), true, false, Some(0.0)));
        assert!(policy.observe(now + Duration::from_secs(35), true, false, Some(0.0)));
    }

    #[test]
    fn platform_idle_threshold_and_invalid_values_fail_safely() {
        let now = Instant::now();
        let mut policy = IdleLockPolicy::new(Duration::from_secs(30));
        assert!(policy.observe(now, true, true, Some(30.0)));

        assert!(!policy.observe(now, true, true, Some(f64::NAN)));
        assert!(policy.observe(now + Duration::from_secs(30), true, true, None));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn macos_idle_query_returns_only_a_finite_duration() {
        assert!(platform_idle_seconds().is_some());
    }
}
