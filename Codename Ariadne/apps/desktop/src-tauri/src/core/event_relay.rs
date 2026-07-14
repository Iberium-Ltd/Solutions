use std::collections::{HashSet, VecDeque};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use uuid::Uuid;

use super::contract::{EventReplayDisposition, EventReplayResult, SafeCoreEvent};
use super::supervisor::CoreSupervisor;

const EVENT_CHANNEL: &str = "ariadne://core-events";
const POLL_INTERVAL: Duration = Duration::from_millis(500);
const DEDUPLICATION_CAPACITY: usize = 512;

pub(crate) fn spawn_event_relay(app: AppHandle, supervisor: CoreSupervisor) {
    tauri::async_runtime::spawn(async move {
        let mut state = RelayState::default();
        let mut ticker = tokio::time::interval(POLL_INTERVAL);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            ticker.tick().await;
            let replay = match supervisor.replay_events(state.cursor).await {
                Ok(Some(replay)) => replay,
                Ok(None) => continue,
                Err(_) => continue,
            };
            for event in state.accept(replay) {
                let _ = app.emit(EVENT_CHANNEL, event);
            }
        }
    });
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "kind", rename_all = "SCREAMING_SNAKE_CASE")]
enum RelayedCoreEvent {
    ResourceChanged {
        event_id: Uuid,
        resource_type: RelayResourceType,
        resource_id: Option<Uuid>,
        resource_revision: u64,
    },
    RefetchRequired {
        reason: RefetchReason,
    },
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
enum RelayResourceType {
    Job,
    Settings,
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
enum RefetchReason {
    CursorExpired,
    SequenceGap,
}

#[derive(Default)]
struct RelayState {
    cursor: Option<Uuid>,
    last_sequence: Option<u64>,
    seen_order: VecDeque<Uuid>,
    seen: HashSet<Uuid>,
}

impl RelayState {
    fn accept(&mut self, replay: EventReplayResult) -> Vec<RelayedCoreEvent> {
        let mut output = Vec::new();
        let mut refetch_emitted = false;
        match replay.disposition {
            EventReplayDisposition::CursorExpired => {
                output.push(RelayedCoreEvent::RefetchRequired {
                    reason: RefetchReason::CursorExpired,
                });
                refetch_emitted = true;
                self.last_sequence = None;
            }
            EventReplayDisposition::Gap => {
                output.push(RelayedCoreEvent::RefetchRequired {
                    reason: RefetchReason::SequenceGap,
                });
                refetch_emitted = true;
            }
            EventReplayDisposition::Ok => {}
        }

        for event in replay.events {
            if self.seen.contains(&event.event_id) {
                continue;
            }
            if self
                .last_sequence
                .is_some_and(|last| last.checked_add(1) != Some(event.sequence))
                && !refetch_emitted
            {
                output.push(RelayedCoreEvent::RefetchRequired {
                    reason: RefetchReason::SequenceGap,
                });
                refetch_emitted = true;
            }
            self.last_sequence = Some(event.sequence);
            self.remember(event.event_id);
            if let Some(relayed) = resource_change(event) {
                output.push(relayed);
            }
        }
        self.cursor = replay.next_cursor;
        output
    }

    fn remember(&mut self, event_id: Uuid) {
        self.seen.insert(event_id);
        self.seen_order.push_back(event_id);
        while self.seen_order.len() > DEDUPLICATION_CAPACITY {
            if let Some(expired) = self.seen_order.pop_front() {
                self.seen.remove(&expired);
            }
        }
    }
}

fn resource_change(event: SafeCoreEvent) -> Option<RelayedCoreEvent> {
    let revision = event.resource_revision?;
    match (event.resource_type.as_deref(), event.event_type.as_str()) {
        (Some("JOB"), event_type) if event_type.starts_with("JOB_") => {
            Some(RelayedCoreEvent::ResourceChanged {
                event_id: event.event_id,
                resource_type: RelayResourceType::Job,
                resource_id: event.resource_id,
                resource_revision: revision,
            })
        }
        (Some("SETTINGS"), "SETTINGS_UPDATED") if event.resource_id.is_none() => {
            Some(RelayedCoreEvent::ResourceChanged {
                event_id: event.event_id,
                resource_type: RelayResourceType::Settings,
                resource_id: None,
                resource_revision: revision,
            })
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(sequence: u64, event_type: &str) -> SafeCoreEvent {
        SafeCoreEvent {
            event_id: Uuid::new_v4(),
            sequence,
            event_type: event_type.to_owned(),
            resource_type: Some("JOB".to_owned()),
            resource_id: Some(Uuid::new_v4()),
            resource_revision: Some(sequence),
        }
    }

    fn replay(
        disposition: EventReplayDisposition,
        events: Vec<SafeCoreEvent>,
    ) -> EventReplayResult {
        EventReplayResult {
            disposition,
            next_cursor: events.last().map(|event| event.event_id),
            events,
            has_more: false,
        }
    }

    #[test]
    fn duplicate_event_ids_are_tolerated() {
        let mut state = RelayState::default();
        let first = event(1, "JOB_QUEUED");
        let duplicate = SafeCoreEvent {
            event_id: first.event_id,
            sequence: first.sequence,
            event_type: first.event_type.clone(),
            resource_type: first.resource_type.clone(),
            resource_id: first.resource_id,
            resource_revision: first.resource_revision,
        };
        assert_eq!(
            state
                .accept(replay(EventReplayDisposition::Ok, vec![first]))
                .len(),
            1
        );
        assert!(
            state
                .accept(replay(EventReplayDisposition::Ok, vec![duplicate]))
                .is_empty()
        );
    }

    #[test]
    fn sequence_gap_and_expired_cursor_emit_refetch_without_cursor_disclosure() {
        let mut state = RelayState::default();
        state.accept(replay(
            EventReplayDisposition::Ok,
            vec![event(1, "JOB_QUEUED")],
        ));
        let gap = state.accept(replay(
            EventReplayDisposition::Ok,
            vec![event(3, "JOB_SUCCEEDED")],
        ));
        assert!(matches!(
            gap.first(),
            Some(RelayedCoreEvent::RefetchRequired {
                reason: RefetchReason::SequenceGap
            })
        ));

        let expired = state.accept(EventReplayResult {
            disposition: EventReplayDisposition::CursorExpired,
            events: vec![],
            next_cursor: Some(Uuid::new_v4()),
            has_more: false,
        });
        assert!(matches!(
            expired.as_slice(),
            [RelayedCoreEvent::RefetchRequired {
                reason: RefetchReason::CursorExpired
            }]
        ));
        let encoded = serde_json::to_string(&expired).unwrap();
        assert!(!encoded.contains("cursor"));
    }

    #[test]
    fn unknown_additive_variant_advances_cursor_without_reaching_webview() {
        let mut state = RelayState::default();
        let unknown = event(1, "FUTURE_ADDITIVE_VARIANT");
        let expected_cursor = unknown.event_id;
        assert!(
            state
                .accept(replay(EventReplayDisposition::Ok, vec![unknown]))
                .is_empty()
        );
        assert_eq!(state.cursor, Some(expected_cursor));
    }

    #[test]
    fn lock_or_sidecar_restart_pause_retains_the_rust_owned_cursor() {
        let mut state = RelayState::default();
        let first = event(1, "JOB_QUEUED");
        let first_cursor = first.event_id;
        state.accept(replay(EventReplayDisposition::Ok, vec![first]));

        // A locked supervisor returns no replay window, so the relay state is
        // deliberately untouched until a newly authenticated sidecar resumes.
        assert_eq!(state.cursor, Some(first_cursor));
        let resumed = state.accept(replay(
            EventReplayDisposition::Ok,
            vec![event(2, "JOB_RUNNING")],
        ));
        assert_eq!(resumed.len(), 1);
        assert!(matches!(
            resumed.first(),
            Some(RelayedCoreEvent::ResourceChanged { .. })
        ));
    }
}
