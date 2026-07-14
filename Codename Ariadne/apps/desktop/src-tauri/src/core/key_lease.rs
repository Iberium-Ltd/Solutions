#![allow(
    dead_code,
    reason = "the standalone key-lease protocol is integrated in the next vault command slice"
)]

use std::{
    fmt,
    io::{self, Read, Write},
    os::{
        fd::{AsRawFd, FromRawFd, RawFd},
        unix::net::UnixStream,
    },
    sync::{Arc, Mutex, MutexGuard},
    time::{Duration, Instant},
};

use sha2::{Digest, Sha256};
use tokio::process::Command;
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::security::key_custody::{KeyMaterial, KeyReference};

pub(crate) const KEY_LEASE_CHILD_FD: RawFd = 198;
pub(crate) const KEY_LEASE_PROTOCOL_VERSION: u8 = 1;
pub(crate) const MAX_KEY_LEASE_FRAME_BYTES: usize = 256;
pub(crate) const HELLO_TIMEOUT: Duration = Duration::from_secs(30);
pub(crate) const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
pub(crate) const KEYCHAIN_TIMEOUT: Duration = Duration::from_secs(120);
pub(crate) const GRANT_TIMEOUT: Duration = Duration::from_secs(2);
pub(crate) const PREPARED_TIMEOUT: Duration = Duration::from_secs(5);
pub(crate) const COMMIT_TIMEOUT: Duration = Duration::from_secs(2);

const MAGIC: &[u8; 4] = b"AKL1";
const HEADER_BYTES: usize = 16;
const UUID_BYTES: usize = 16;
const LEASE_NONCE_BYTES: usize = 32;
const DIGEST_BYTES: usize = 32;
const KEY_BYTES: usize = 32;
const KEY_REFERENCE_BYTES: usize = 42;
const HELLO_PAYLOAD_BYTES: usize = UUID_BYTES + LEASE_NONCE_BYTES;
const BINDING_PAYLOAD_BYTES: usize = 160;
const GRANT_PAYLOAD_BYTES: usize = BINDING_PAYLOAD_BYTES + KEY_BYTES;
const FINAL_PAYLOAD_BYTES: usize = UUID_BYTES * 2 + LEASE_NONCE_BYTES + DIGEST_BYTES;
const _: () = assert!(HEADER_BYTES + GRANT_PAYLOAD_BYTES <= MAX_KEY_LEASE_FRAME_BYTES);

#[cfg(test)]
pub(crate) static FD_TEST_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u16)]
pub(crate) enum LeaseOperation {
    DatabaseCreateV1 = 1,
    DatabaseUnlockV1 = 2,
}

impl TryFrom<u16> for LeaseOperation {
    type Error = KeyLeaseError;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::DatabaseCreateV1),
            2 => Ok(Self::DatabaseUnlockV1),
            _ => Err(KeyLeaseError::InvalidFrame),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
enum FrameKind {
    Hello = 1,
    Request = 2,
    Grant = 3,
    Prepared = 4,
    Commit = 5,
    Committed = 6,
}

impl FrameKind {
    const fn sequence(self) -> u32 {
        match self {
            Self::Hello => 0,
            Self::Request => 1,
            Self::Grant => 2,
            Self::Prepared => 3,
            Self::Commit => 4,
            Self::Committed => 5,
        }
    }

    const fn payload_bytes(self) -> usize {
        match self {
            Self::Hello => HELLO_PAYLOAD_BYTES,
            Self::Request => BINDING_PAYLOAD_BYTES,
            Self::Grant => GRANT_PAYLOAD_BYTES,
            Self::Prepared | Self::Commit | Self::Committed => FINAL_PAYLOAD_BYTES,
        }
    }
}

impl TryFrom<u8> for FrameKind {
    type Error = KeyLeaseError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::Hello),
            2 => Ok(Self::Request),
            3 => Ok(Self::Grant),
            4 => Ok(Self::Prepared),
            5 => Ok(Self::Commit),
            6 => Ok(Self::Committed),
            _ => Err(KeyLeaseError::InvalidFrame),
        }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
struct LeaseNonce([u8; LEASE_NONCE_BYTES]);

impl fmt::Debug for LeaseNonce {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LeaseNonce([OPAQUE])")
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) struct ManifestDigest([u8; DIGEST_BYTES]);

impl ManifestDigest {
    pub(crate) const fn new(bytes: [u8; DIGEST_BYTES]) -> Self {
        Self(bytes)
    }
}

impl fmt::Debug for ManifestDigest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ManifestDigest([OPAQUE])")
    }
}

#[derive(Clone, Eq, PartialEq)]
struct UnlockBinding {
    startup_nonce: Uuid,
    lease_nonce: LeaseNonce,
    transaction_id: Uuid,
    vault_id: Uuid,
    manifest_digest: ManifestDigest,
    key_reference: KeyReference,
    key_reference_bytes: [u8; KEY_REFERENCE_BYTES],
    key_version: u32,
    operation: LeaseOperation,
}

impl fmt::Debug for UnlockBinding {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("UnlockBinding([OPAQUE])")
    }
}

impl UnlockBinding {
    fn digest(&self) -> [u8; DIGEST_BYTES] {
        let encoded = self.encode();
        Sha256::digest(encoded.as_slice()).into()
    }

    fn encode(&self) -> Zeroizing<Vec<u8>> {
        let mut payload = Zeroizing::new(Vec::with_capacity(BINDING_PAYLOAD_BYTES));
        push_uuid(&mut payload, self.startup_nonce);
        payload.extend_from_slice(&self.lease_nonce.0);
        push_uuid(&mut payload, self.transaction_id);
        push_uuid(&mut payload, self.vault_id);
        payload.extend_from_slice(&self.manifest_digest.0);
        payload.extend_from_slice(&self.key_reference_bytes);
        payload.extend_from_slice(&self.key_version.to_be_bytes());
        payload.extend_from_slice(&(self.operation as u16).to_be_bytes());
        debug_assert_eq!(payload.len(), BINDING_PAYLOAD_BYTES);
        payload
    }

    fn decode(payload: &[u8]) -> Result<Self, KeyLeaseError> {
        require_length(payload, BINDING_PAYLOAD_BYTES)?;
        let startup_nonce = uuid_at(payload, 0)?;
        let mut lease_nonce = [0_u8; LEASE_NONCE_BYTES];
        lease_nonce.copy_from_slice(&payload[16..48]);
        let transaction_id = uuid_at(payload, 48)?;
        let vault_id = uuid_at(payload, 64)?;
        let mut manifest_digest = [0_u8; DIGEST_BYTES];
        manifest_digest.copy_from_slice(&payload[80..112]);
        let mut key_reference_bytes = [0_u8; KEY_REFERENCE_BYTES];
        key_reference_bytes.copy_from_slice(&payload[112..154]);
        let key_reference = reference_from_canonical(&key_reference_bytes)?;
        let key_version = u32::from_be_bytes(
            payload[154..158]
                .try_into()
                .map_err(|_| KeyLeaseError::InvalidFrame)?,
        );
        if key_version == 0 {
            return Err(KeyLeaseError::InvalidFrame);
        }
        let operation = LeaseOperation::try_from(u16::from_be_bytes(
            payload[158..160]
                .try_into()
                .map_err(|_| KeyLeaseError::InvalidFrame)?,
        ))?;
        Ok(Self {
            startup_nonce,
            lease_nonce: LeaseNonce(lease_nonce),
            transaction_id,
            vault_id,
            manifest_digest: ManifestDigest(manifest_digest),
            key_reference,
            key_reference_bytes,
            key_version,
            operation,
        })
    }

    fn final_context(&self) -> FinalContext {
        FinalContext {
            startup_nonce: self.startup_nonce,
            lease_nonce: self.lease_nonce,
            transaction_id: self.transaction_id,
            binding_digest: self.digest(),
        }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
struct FinalContext {
    startup_nonce: Uuid,
    lease_nonce: LeaseNonce,
    transaction_id: Uuid,
    binding_digest: [u8; DIGEST_BYTES],
}

impl fmt::Debug for FinalContext {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("FinalContext([OPAQUE])")
    }
}

impl FinalContext {
    fn encode(self) -> Zeroizing<Vec<u8>> {
        let mut payload = Zeroizing::new(Vec::with_capacity(FINAL_PAYLOAD_BYTES));
        push_uuid(&mut payload, self.startup_nonce);
        payload.extend_from_slice(&self.lease_nonce.0);
        push_uuid(&mut payload, self.transaction_id);
        payload.extend_from_slice(&self.binding_digest);
        debug_assert_eq!(payload.len(), FINAL_PAYLOAD_BYTES);
        payload
    }

    fn decode(payload: &[u8]) -> Result<Self, KeyLeaseError> {
        require_length(payload, FINAL_PAYLOAD_BYTES)?;
        let startup_nonce = uuid_at(payload, 0)?;
        let mut lease_nonce = [0_u8; LEASE_NONCE_BYTES];
        lease_nonce.copy_from_slice(&payload[16..48]);
        let transaction_id = uuid_at(payload, 48)?;
        let mut binding_digest = [0_u8; DIGEST_BYTES];
        binding_digest.copy_from_slice(&payload[64..96]);
        Ok(Self {
            startup_nonce,
            lease_nonce: LeaseNonce(lease_nonce),
            transaction_id,
            binding_digest,
        })
    }
}

enum Frame {
    Hello {
        startup_nonce: Uuid,
        lease_nonce: LeaseNonce,
    },
    Request(UnlockBinding),
    Grant {
        binding: UnlockBinding,
        key: Zeroizing<[u8; KEY_BYTES]>,
    },
    Prepared(FinalContext),
    Commit(FinalContext),
    Committed(FinalContext),
}

impl Frame {
    const fn kind(&self) -> FrameKind {
        match self {
            Self::Hello { .. } => FrameKind::Hello,
            Self::Request(_) => FrameKind::Request,
            Self::Grant { .. } => FrameKind::Grant,
            Self::Prepared(_) => FrameKind::Prepared,
            Self::Commit(_) => FrameKind::Commit,
            Self::Committed(_) => FrameKind::Committed,
        }
    }
}

impl fmt::Debug for Frame {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Frame")
            .field("kind", &self.kind())
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) struct AuthorizationDescriptor {
    pub(crate) transaction_id: Uuid,
    pub(crate) vault_id: Uuid,
    pub(crate) operation: LeaseOperation,
}

impl fmt::Debug for AuthorizationDescriptor {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AuthorizationDescriptor([OPAQUE])")
    }
}

struct Authorization {
    binding: UnlockBinding,
    expires_at: Instant,
}

impl fmt::Debug for Authorization {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("Authorization([OPAQUE])")
    }
}

#[derive(Default)]
struct SharedState {
    lease_nonce: Option<LeaseNonce>,
    pending: Option<Authorization>,
    terminal: bool,
    poisoned: bool,
}

#[derive(Clone)]
pub(crate) struct KeyLeaseHandle {
    startup_nonce: Uuid,
    shared: Arc<Mutex<SharedState>>,
}

impl fmt::Debug for KeyLeaseHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("KeyLeaseHandle([OPAQUE])")
    }
}

impl KeyLeaseHandle {
    pub(crate) fn authorize(
        &self,
        vault_id: Uuid,
        manifest_digest: ManifestDigest,
        key_reference: KeyReference,
        key_version: u32,
        operation: LeaseOperation,
    ) -> Result<AuthorizationDescriptor, KeyLeaseError> {
        if key_version == 0 {
            return Err(KeyLeaseError::InvalidAuthorization);
        }
        let key_reference_bytes = canonical_reference(key_reference)?;
        let mut shared = lock_unpoisoned(&self.shared);
        if shared.poisoned {
            return Err(KeyLeaseError::Poisoned);
        }
        if shared.terminal {
            return Err(KeyLeaseError::Consumed);
        }
        if shared.pending.is_some() {
            return Err(KeyLeaseError::AuthorizationOutstanding);
        }
        let lease_nonce = shared.lease_nonce.ok_or(KeyLeaseError::HelloRequired)?;
        let transaction_id = Uuid::new_v4();
        let binding = UnlockBinding {
            startup_nonce: self.startup_nonce,
            lease_nonce,
            transaction_id,
            vault_id,
            manifest_digest,
            key_reference,
            key_reference_bytes,
            key_version,
            operation,
        };
        shared.pending = Some(Authorization {
            binding,
            expires_at: Instant::now() + REQUEST_TIMEOUT,
        });
        Ok(AuthorizationDescriptor {
            transaction_id,
            vault_id,
            operation,
        })
    }
}

pub(crate) trait LeaseKey: Send + 'static {
    fn expose(&self) -> &[u8; KEY_BYTES];
}

impl LeaseKey for KeyMaterial {
    fn expose(&self) -> &[u8; KEY_BYTES] {
        KeyMaterial::expose(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum BrokerState {
    AwaitHello,
    Idle,
    AwaitRequest,
    AwaitGrant,
    AwaitPrepared,
    AwaitCommit,
    AwaitCommitted,
    Consumed,
    Poisoned,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct HelloAccepted;

pub(crate) struct KeyLeaseBroker {
    stream: UnixStream,
    startup_nonce: Uuid,
    shared: Arc<Mutex<SharedState>>,
    state: BrokerState,
}

impl fmt::Debug for KeyLeaseBroker {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("KeyLeaseBroker")
            .field("state", &self.state)
            .finish_non_exhaustive()
    }
}

impl KeyLeaseBroker {
    pub(crate) fn socket_pair(
        startup_nonce: Uuid,
    ) -> Result<(Self, KeyLeaseHandle, ChildLeaseEndpoint), KeyLeaseError> {
        let (parent, source_child) = UnixStream::pair().map_err(KeyLeaseError::Channel)?;
        set_cloexec(parent.as_raw_fd(), true).map_err(KeyLeaseError::Channel)?;
        set_cloexec(source_child.as_raw_fd(), true).map_err(KeyLeaseError::Channel)?;
        ensure_child_fd_limit().map_err(KeyLeaseError::Channel)?;
        let child = reserve_exact_child_fd(source_child)?;
        if !is_cloexec(parent.as_raw_fd()).map_err(KeyLeaseError::Channel)?
            || !is_cloexec(child.as_raw_fd()).map_err(KeyLeaseError::Channel)?
        {
            return Err(KeyLeaseError::DescriptorPolicy);
        }
        let shared = Arc::new(Mutex::new(SharedState::default()));
        Ok((
            Self {
                stream: parent,
                startup_nonce,
                shared: Arc::clone(&shared),
                state: BrokerState::AwaitHello,
            },
            KeyLeaseHandle {
                startup_nonce,
                shared,
            },
            ChildLeaseEndpoint { stream: child },
        ))
    }

    pub(crate) fn accept_hello(&mut self) -> Result<HelloAccepted, KeyLeaseError> {
        if self.state != BrokerState::AwaitHello {
            return self.poison(KeyLeaseError::InvalidState);
        }
        if let Err(error) = self.set_timeout(HELLO_TIMEOUT) {
            return self.poison(error);
        }
        let frame = read_frame(&mut self.stream).map_err(|error| self.poison_value(error))?;
        let lease_nonce = match frame {
            Frame::Hello {
                startup_nonce,
                lease_nonce,
            } if startup_nonce == self.startup_nonce => lease_nonce,
            _ => return self.poison(KeyLeaseError::ProtocolMismatch),
        };
        {
            let mut shared = lock_unpoisoned(&self.shared);
            shared.lease_nonce = Some(lease_nonce);
        }
        self.state = BrokerState::Idle;
        Ok(HelloAccepted)
    }

    pub(crate) fn run_authorized<K, F, P>(
        &mut self,
        key_supplier: F,
        authorization_still_valid: P,
    ) -> Result<(), KeyLeaseError>
    where
        K: LeaseKey,
        F: FnOnce(KeyReference) -> Result<K, KeyLeaseError>,
        P: Fn() -> bool,
    {
        if self.state != BrokerState::Idle {
            return self.poison(KeyLeaseError::InvalidState);
        }
        let authorization = {
            let mut shared = lock_unpoisoned(&self.shared);
            shared
                .pending
                .take()
                .ok_or(KeyLeaseError::NoAuthorization)?
        };
        self.state = BrokerState::AwaitRequest;
        if Instant::now() >= authorization.expires_at {
            return self.poison(KeyLeaseError::Expired);
        }
        if let Err(error) = self.set_deadline(authorization.expires_at) {
            return self.poison(error);
        }
        let request = read_frame(&mut self.stream).map_err(|error| self.poison_value(error))?;
        let request_binding = match request {
            Frame::Request(binding) => binding,
            _ => return self.poison(KeyLeaseError::ReplayOrUnexpectedFrame),
        };
        if request_binding != authorization.binding {
            return self.poison(KeyLeaseError::BindingMismatch);
        }

        self.state = BrokerState::AwaitGrant;
        let keychain_started = Instant::now();
        let key = key_supplier(authorization.binding.key_reference)
            .map_err(|error| self.poison_value(error))?;
        if keychain_started.elapsed() > KEYCHAIN_TIMEOUT {
            drop(key);
            return self.poison(KeyLeaseError::KeychainTimeout);
        }
        if !authorization_still_valid() {
            drop(key);
            return self.poison(KeyLeaseError::CommitRevoked);
        }
        let grant_deadline = Instant::now() + GRANT_TIMEOUT;
        if let Err(error) = self.set_deadline(grant_deadline) {
            drop(key);
            return self.poison(error);
        }
        if let Err(error) = write_grant(&mut self.stream, &authorization.binding, key.expose()) {
            drop(key);
            return self.poison(error);
        }
        if Instant::now() >= grant_deadline {
            drop(key);
            return self.poison(KeyLeaseError::Timeout);
        }

        self.state = BrokerState::AwaitPrepared;
        if let Err(error) = self.set_timeout(PREPARED_TIMEOUT) {
            drop(key);
            return self.poison(error);
        }
        let expected_context = authorization.binding.final_context();
        match read_frame(&mut self.stream).map_err(|error| self.poison_value(error))? {
            Frame::Prepared(context) if context == expected_context => {}
            _ => {
                drop(key);
                return self.poison(KeyLeaseError::ReplayOrUnexpectedFrame);
            }
        }

        self.state = BrokerState::AwaitCommit;
        let commit_deadline = Instant::now() + COMMIT_TIMEOUT;
        if !authorization_still_valid() || Instant::now() >= commit_deadline {
            drop(key);
            return self.poison(KeyLeaseError::CommitRevoked);
        }
        if let Err(error) = self.set_deadline(commit_deadline) {
            drop(key);
            return self.poison(error);
        }
        if let Err(error) = write_frame(&mut self.stream, &Frame::Commit(expected_context)) {
            drop(key);
            return self.poison(error);
        }
        self.state = BrokerState::AwaitCommitted;
        if let Err(error) = self.set_timeout(COMMIT_TIMEOUT) {
            drop(key);
            return self.poison(error);
        }
        match read_frame(&mut self.stream).map_err(|error| self.poison_value(error))? {
            Frame::Committed(context) if context == expected_context => {}
            _ => {
                drop(key);
                return self.poison(KeyLeaseError::ReplayOrUnexpectedFrame);
            }
        }
        drop(key);
        if let Err(error) = ensure_no_buffered_input(&self.stream) {
            return self.poison(error);
        }
        self.consume()
    }

    fn set_deadline(&self, deadline: Instant) -> Result<(), KeyLeaseError> {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|duration| !duration.is_zero())
            .ok_or(KeyLeaseError::Expired)?;
        self.set_timeout(remaining)
    }

    fn set_timeout(&self, duration: Duration) -> Result<(), KeyLeaseError> {
        self.stream
            .set_read_timeout(Some(duration))
            .map_err(KeyLeaseError::Channel)?;
        self.stream
            .set_write_timeout(Some(duration))
            .map_err(KeyLeaseError::Channel)
    }

    fn consume(&mut self) -> Result<(), KeyLeaseError> {
        self.state = BrokerState::Consumed;
        self.mark_terminal(false);
        let _ = self.stream.shutdown(std::net::Shutdown::Both);
        Ok(())
    }

    fn poison<T>(&mut self, error: KeyLeaseError) -> Result<T, KeyLeaseError> {
        Err(self.poison_value(error))
    }

    fn poison_value(&mut self, error: KeyLeaseError) -> KeyLeaseError {
        self.state = BrokerState::Poisoned;
        self.mark_terminal(true);
        let _ = self.stream.shutdown(std::net::Shutdown::Both);
        error
    }

    fn mark_terminal(&self, poisoned: bool) {
        let mut shared = lock_unpoisoned(&self.shared);
        shared.pending = None;
        shared.terminal = true;
        shared.poisoned = poisoned;
    }
}

impl Drop for KeyLeaseBroker {
    fn drop(&mut self) {
        if self.state != BrokerState::Consumed {
            self.state = BrokerState::Poisoned;
            self.mark_terminal(true);
        }
        let _ = self.stream.shutdown(std::net::Shutdown::Both);
    }
}

pub(crate) struct ChildLeaseEndpoint {
    stream: UnixStream,
}

impl fmt::Debug for ChildLeaseEndpoint {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ChildLeaseEndpoint([INHERITED])")
    }
}

impl ChildLeaseEndpoint {
    pub(crate) fn configure_command(&self, command: &mut Command) {
        debug_assert_eq!(self.stream.as_raw_fd(), KEY_LEASE_CHILD_FD);
        // SAFETY: the hook performs exactly one async-signal-safe fcntl operation.
        // This endpoint remains owned until the caller's spawn attempt completes.
        unsafe {
            command.pre_exec(|| {
                if libc::fcntl(KEY_LEASE_CHILD_FD, libc::F_SETFD, 0) == -1 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }

    #[cfg(test)]
    fn raw_fd(&self) -> RawFd {
        self.stream.as_raw_fd()
    }
}

fn reserve_exact_child_fd(source: UnixStream) -> Result<UnixStream, KeyLeaseError> {
    if source.as_raw_fd() == KEY_LEASE_CHILD_FD {
        return Ok(source);
    }
    // SAFETY: F_DUPFD_CLOEXEC duplicates the valid source descriptor and does not
    // access memory. It atomically reserves the lowest available descriptor >= 198.
    let duplicated = unsafe {
        libc::fcntl(
            source.as_raw_fd(),
            libc::F_DUPFD_CLOEXEC,
            KEY_LEASE_CHILD_FD,
        )
    };
    if duplicated == -1 {
        return Err(KeyLeaseError::Channel(io::Error::last_os_error()));
    }
    if duplicated != KEY_LEASE_CHILD_FD {
        // SAFETY: this descriptor was just created above and is not otherwise owned.
        unsafe {
            libc::close(duplicated);
        }
        return Err(KeyLeaseError::ChildDescriptorOccupied);
    }
    drop(source);
    // SAFETY: descriptor 198 was just returned uniquely by fcntl and ownership is
    // transferred to the UnixStream exactly once.
    Ok(unsafe { UnixStream::from_raw_fd(duplicated) })
}

fn ensure_child_fd_limit() -> io::Result<()> {
    let mut limit = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    // SAFETY: getrlimit writes one initialized rlimit structure.
    if unsafe { libc::getrlimit(libc::RLIMIT_NOFILE, &mut limit) } == -1 {
        return Err(io::Error::last_os_error());
    }
    if limit.rlim_cur <= KEY_LEASE_CHILD_FD as libc::rlim_t {
        return Err(io::Error::other(
            "child descriptor is outside the soft limit",
        ));
    }
    Ok(())
}

fn is_cloexec(fd: RawFd) -> io::Result<bool> {
    // SAFETY: F_GETFD reads flags from a valid owned descriptor.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags == -1 {
        return Err(io::Error::last_os_error());
    }
    Ok(flags & libc::FD_CLOEXEC != 0)
}

fn set_cloexec(fd: RawFd, enabled: bool) -> io::Result<()> {
    // SAFETY: F_GETFD/F_SETFD operate only on descriptor flags.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags == -1 {
        return Err(io::Error::last_os_error());
    }
    let updated = if enabled {
        flags | libc::FD_CLOEXEC
    } else {
        flags & !libc::FD_CLOEXEC
    };
    if unsafe { libc::fcntl(fd, libc::F_SETFD, updated) } == -1 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn write_frame(stream: &mut UnixStream, frame: &Frame) -> Result<(), KeyLeaseError> {
    if matches!(frame, Frame::Grant { .. }) {
        return Err(KeyLeaseError::InvalidState);
    }
    let encoded = encode_frame(frame)?;
    stream.write_all(encoded.as_slice()).map_err(map_io_error)?;
    stream.flush().map_err(map_io_error)
}

fn write_grant(
    stream: &mut UnixStream,
    binding: &UnlockBinding,
    key: &[u8; KEY_BYTES],
) -> Result<(), KeyLeaseError> {
    let mut prefix = encode_header(FrameKind::Grant)?;
    let binding_bytes = binding.encode();
    prefix.extend_from_slice(binding_bytes.as_slice());
    debug_assert_eq!(prefix.len(), HEADER_BYTES + BINDING_PAYLOAD_BYTES);
    stream.write_all(prefix.as_slice()).map_err(map_io_error)?;
    stream.write_all(key).map_err(map_io_error)?;
    stream.flush().map_err(map_io_error)
}

fn read_frame(stream: &mut UnixStream) -> Result<Frame, KeyLeaseError> {
    let mut header = [0_u8; HEADER_BYTES];
    stream.read_exact(&mut header).map_err(map_io_error)?;
    let (kind, payload_length) = decode_header(&header)?;
    let mut payload = Zeroizing::new(vec![0_u8; payload_length]);
    stream
        .read_exact(payload.as_mut_slice())
        .map_err(map_io_error)?;
    decode_payload(kind, payload.as_slice())
}

fn encode_frame(frame: &Frame) -> Result<Zeroizing<Vec<u8>>, KeyLeaseError> {
    let kind = frame.kind();
    let mut encoded = encode_header(kind)?;
    match frame {
        Frame::Hello {
            startup_nonce,
            lease_nonce,
        } => {
            push_uuid(&mut encoded, *startup_nonce);
            encoded.extend_from_slice(&lease_nonce.0);
        }
        Frame::Request(binding) => encoded.extend_from_slice(binding.encode().as_slice()),
        Frame::Grant { binding, key } => {
            encoded.extend_from_slice(binding.encode().as_slice());
            encoded.extend_from_slice(key.as_slice());
        }
        Frame::Prepared(context) | Frame::Commit(context) | Frame::Committed(context) => {
            encoded.extend_from_slice(context.encode().as_slice());
        }
    }
    if encoded.len() != HEADER_BYTES + kind.payload_bytes()
        || encoded.len() > MAX_KEY_LEASE_FRAME_BYTES
    {
        return Err(KeyLeaseError::InvalidFrame);
    }
    Ok(encoded)
}

fn encode_header(kind: FrameKind) -> Result<Zeroizing<Vec<u8>>, KeyLeaseError> {
    let frame_length = HEADER_BYTES + kind.payload_bytes();
    if frame_length > MAX_KEY_LEASE_FRAME_BYTES {
        return Err(KeyLeaseError::FrameTooLarge);
    }
    let mut header = Zeroizing::new(Vec::with_capacity(frame_length));
    header.extend_from_slice(MAGIC);
    header.push(KEY_LEASE_PROTOCOL_VERSION);
    header.push(kind as u8);
    header.extend_from_slice(&0_u16.to_be_bytes());
    header.extend_from_slice(&(kind.payload_bytes() as u32).to_be_bytes());
    header.extend_from_slice(&kind.sequence().to_be_bytes());
    Ok(header)
}

fn decode_header(header: &[u8; HEADER_BYTES]) -> Result<(FrameKind, usize), KeyLeaseError> {
    if &header[..4] != MAGIC || header[4] != KEY_LEASE_PROTOCOL_VERSION || header[6..8] != [0, 0] {
        return Err(KeyLeaseError::InvalidFrame);
    }
    let kind = FrameKind::try_from(header[5])?;
    let payload_length = u32::from_be_bytes(
        header[8..12]
            .try_into()
            .map_err(|_| KeyLeaseError::InvalidFrame)?,
    ) as usize;
    let sequence = u32::from_be_bytes(
        header[12..16]
            .try_into()
            .map_err(|_| KeyLeaseError::InvalidFrame)?,
    );
    if payload_length != kind.payload_bytes()
        || sequence != kind.sequence()
        || HEADER_BYTES + payload_length > MAX_KEY_LEASE_FRAME_BYTES
    {
        return Err(KeyLeaseError::InvalidFrame);
    }
    Ok((kind, payload_length))
}

fn decode_payload(kind: FrameKind, payload: &[u8]) -> Result<Frame, KeyLeaseError> {
    require_length(payload, kind.payload_bytes())?;
    match kind {
        FrameKind::Hello => {
            let startup_nonce = uuid_at(payload, 0)?;
            let mut lease_nonce = [0_u8; LEASE_NONCE_BYTES];
            lease_nonce.copy_from_slice(&payload[16..48]);
            Ok(Frame::Hello {
                startup_nonce,
                lease_nonce: LeaseNonce(lease_nonce),
            })
        }
        FrameKind::Request => Ok(Frame::Request(UnlockBinding::decode(payload)?)),
        FrameKind::Grant => {
            let binding = UnlockBinding::decode(&payload[..BINDING_PAYLOAD_BYTES])?;
            let mut key = Zeroizing::new([0_u8; KEY_BYTES]);
            key.copy_from_slice(&payload[BINDING_PAYLOAD_BYTES..]);
            Ok(Frame::Grant { binding, key })
        }
        FrameKind::Prepared => Ok(Frame::Prepared(FinalContext::decode(payload)?)),
        FrameKind::Commit => Ok(Frame::Commit(FinalContext::decode(payload)?)),
        FrameKind::Committed => Ok(Frame::Committed(FinalContext::decode(payload)?)),
    }
}

fn ensure_no_buffered_input(stream: &UnixStream) -> Result<(), KeyLeaseError> {
    let mut byte = [0_u8; 1];
    // SAFETY: recv only inspects one byte from the valid connected socket.
    let result = unsafe {
        libc::recv(
            stream.as_raw_fd(),
            byte.as_mut_ptr().cast(),
            byte.len(),
            libc::MSG_PEEK | libc::MSG_DONTWAIT,
        )
    };
    if result > 0 {
        return Err(KeyLeaseError::TrailingFrame);
    }
    if result == 0 {
        return Ok(());
    }
    let error = io::Error::last_os_error();
    if matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
    ) {
        Ok(())
    } else {
        Err(KeyLeaseError::Channel(error))
    }
}

fn canonical_reference(
    reference: KeyReference,
) -> Result<[u8; KEY_REFERENCE_BYTES], KeyLeaseError> {
    let opaque = reference.opaque_reference();
    let bytes: [u8; KEY_REFERENCE_BYTES] = opaque
        .as_bytes()
        .try_into()
        .map_err(|_| KeyLeaseError::InvalidAuthorization)?;
    if KeyReference::parse_vault(&opaque).map_err(|_| KeyLeaseError::InvalidAuthorization)?
        != reference
    {
        return Err(KeyLeaseError::InvalidAuthorization);
    }
    Ok(bytes)
}

fn reference_from_canonical(
    bytes: &[u8; KEY_REFERENCE_BYTES],
) -> Result<KeyReference, KeyLeaseError> {
    let encoded = std::str::from_utf8(bytes).map_err(|_| KeyLeaseError::InvalidFrame)?;
    let reference = KeyReference::parse_vault(encoded).map_err(|_| KeyLeaseError::InvalidFrame)?;
    if canonical_reference(reference).map_err(|_| KeyLeaseError::InvalidFrame)? != *bytes {
        return Err(KeyLeaseError::InvalidFrame);
    }
    Ok(reference)
}

fn push_uuid(buffer: &mut Vec<u8>, value: Uuid) {
    buffer.extend_from_slice(value.as_bytes());
}

fn uuid_at(bytes: &[u8], offset: usize) -> Result<Uuid, KeyLeaseError> {
    Uuid::from_slice(
        bytes
            .get(offset..offset + UUID_BYTES)
            .ok_or(KeyLeaseError::InvalidFrame)?,
    )
    .map_err(|_| KeyLeaseError::InvalidFrame)
}

fn require_length(bytes: &[u8], expected: usize) -> Result<(), KeyLeaseError> {
    if bytes.len() == expected {
        Ok(())
    } else {
        Err(KeyLeaseError::InvalidFrame)
    }
}

fn map_io_error(error: io::Error) -> KeyLeaseError {
    if matches!(
        error.kind(),
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
    ) {
        KeyLeaseError::Timeout
    } else if matches!(
        error.kind(),
        io::ErrorKind::UnexpectedEof | io::ErrorKind::BrokenPipe | io::ErrorKind::ConnectionReset
    ) {
        KeyLeaseError::ChannelClosed
    } else {
        KeyLeaseError::Channel(error)
    }
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum KeyLeaseError {
    #[error("key lease channel I/O failed")]
    Channel(#[source] io::Error),
    #[error("key lease channel closed")]
    ChannelClosed,
    #[error("key lease channel timed out")]
    Timeout,
    #[error("key lease descriptor policy failed")]
    DescriptorPolicy,
    #[error("key lease child descriptor is occupied")]
    ChildDescriptorOccupied,
    #[error("key lease frame is invalid")]
    InvalidFrame,
    #[error("key lease frame exceeds its bound")]
    FrameTooLarge,
    #[error("key lease protocol mismatch")]
    ProtocolMismatch,
    #[error("key lease binding mismatch")]
    BindingMismatch,
    #[error("key lease replay or unexpected frame")]
    ReplayOrUnexpectedFrame,
    #[error("key lease trailing frame rejected")]
    TrailingFrame,
    #[error("key lease HELLO has not been accepted")]
    HelloRequired,
    #[error("key lease authorization is unavailable")]
    NoAuthorization,
    #[error("a key lease authorization is already outstanding")]
    AuthorizationOutstanding,
    #[error("key lease authorization is invalid")]
    InvalidAuthorization,
    #[error("key lease channel has already been consumed")]
    Consumed,
    #[error("key lease channel is poisoned")]
    Poisoned,
    #[error("key lease state is invalid")]
    InvalidState,
    #[error("key lease authorization expired")]
    Expired,
    #[error("key lease Keychain operation exceeded its bound")]
    KeychainTimeout,
    #[error("key lease Keychain item is unavailable")]
    KeyUnavailable,
    #[error("key lease commit authorization was revoked")]
    CommitRevoked,
}

#[cfg(test)]
mod tests {
    use std::{
        sync::{
            Arc,
            atomic::{AtomicBool, AtomicUsize, Ordering},
            mpsc,
        },
        thread,
    };

    use super::*;

    const STARTUP: Uuid = Uuid::from_u128(0x00112233_4455_6677_8899_aabbccddeeff);
    const TRANSACTION: Uuid = Uuid::from_u128(0x10213243_5465_7687_98a9_bacbdcedfe0f);
    const VAULT: Uuid = Uuid::from_u128(0x11223344_5566_7788_99aa_bbccddeeff00);
    const REFERENCE: Uuid = Uuid::from_u128(0x12345678_1234_4abc_8def_1234567890ab);
    const LEASE: LeaseNonce = LeaseNonce([0xaa; LEASE_NONCE_BYTES]);
    const MANIFEST: ManifestDigest = ManifestDigest([0x55; DIGEST_BYTES]);

    struct TestKey {
        bytes: Zeroizing<[u8; KEY_BYTES]>,
        dropped: Arc<AtomicBool>,
    }

    impl TestKey {
        fn new(bytes: [u8; KEY_BYTES], dropped: Arc<AtomicBool>) -> Self {
            Self {
                bytes: Zeroizing::new(bytes),
                dropped,
            }
        }
    }

    impl LeaseKey for TestKey {
        fn expose(&self) -> &[u8; KEY_BYTES] {
            &self.bytes
        }
    }

    impl Drop for TestKey {
        fn drop(&mut self) {
            self.bytes.fill(0);
            self.dropped.store(true, Ordering::SeqCst);
        }
    }

    fn reference() -> KeyReference {
        reference_from_canonical(b"kc:v1:12345678-1234-4abc-8def-1234567890ab").unwrap()
    }

    fn binding(operation: LeaseOperation) -> UnlockBinding {
        UnlockBinding {
            startup_nonce: STARTUP,
            lease_nonce: LEASE,
            transaction_id: TRANSACTION,
            vault_id: VAULT,
            manifest_digest: MANIFEST,
            key_reference: reference(),
            key_reference_bytes: *b"kc:v1:12345678-1234-4abc-8def-1234567890ab",
            key_version: 7,
            operation,
        }
    }

    fn test_channel() -> (KeyLeaseBroker, KeyLeaseHandle, UnixStream) {
        let (parent, child) = UnixStream::pair().unwrap();
        let shared = Arc::new(Mutex::new(SharedState::default()));
        (
            KeyLeaseBroker {
                stream: parent,
                startup_nonce: STARTUP,
                shared: Arc::clone(&shared),
                state: BrokerState::AwaitHello,
            },
            KeyLeaseHandle {
                startup_nonce: STARTUP,
                shared,
            },
            child,
        )
    }

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    fn write_fragmented(stream: &mut UnixStream, bytes: &[u8]) {
        for chunk in bytes.chunks(3) {
            stream.write_all(chunk).unwrap();
        }
        stream.flush().unwrap();
    }

    fn accept_hello(broker: &mut KeyLeaseBroker, child: &mut UnixStream) {
        write_frame(
            child,
            &Frame::Hello {
                startup_nonce: STARTUP,
                lease_nonce: LEASE,
            },
        )
        .unwrap();
        assert_eq!(broker.accept_hello().unwrap(), HelloAccepted);
        assert_eq!(broker.state, BrokerState::Idle);
    }

    #[test]
    fn golden_header_hello_request_grant_and_final_vectors_are_stable() {
        let hello = encode_frame(&Frame::Hello {
            startup_nonce: STARTUP,
            lease_nonce: LEASE,
        })
        .unwrap();
        assert_eq!(
            hex(&hello),
            concat!(
                "414b4c31010100000000003000000000",
                "00112233445566778899aabbccddeeff",
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        );

        let request =
            encode_frame(&Frame::Request(binding(LeaseOperation::DatabaseUnlockV1))).unwrap();
        assert_eq!(request.len(), 176);
        assert_eq!(
            &request[..16],
            b"AKL1\x01\x02\x00\x00\x00\x00\x00\xa0\x00\x00\x00\x01"
        );
        assert_eq!(
            hex(&request[16..]),
            concat!(
                "00112233445566778899aabbccddeeff",
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "102132435465768798a9bacbdcedfe0f",
                "112233445566778899aabbccddeeff00",
                "55555555555555555555555555555555",
                "55555555555555555555555555555555",
                "6b633a76313a31323334353637382d313233342d346162632d386465662d313233343536373839306162",
                "000000070002"
            )
        );

        let grant = Frame::Grant {
            binding: binding(LeaseOperation::DatabaseUnlockV1),
            key: Zeroizing::new([0x5a; KEY_BYTES]),
        };
        let encoded_grant = encode_frame(&grant).unwrap();
        assert_eq!(encoded_grant.len(), 208);
        assert_eq!(
            &encoded_grant[..16],
            b"AKL1\x01\x03\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x02"
        );
        assert_eq!(&encoded_grant[176..], &[0x5a; KEY_BYTES]);
        assert_eq!(format!("{grant:?}"), "Frame { kind: Grant, .. }");

        let prepared = encode_frame(&Frame::Prepared(
            binding(LeaseOperation::DatabaseUnlockV1).final_context(),
        ))
        .unwrap();
        assert_eq!(prepared.len(), 112);
        assert_eq!(
            &prepared[..16],
            b"AKL1\x01\x04\x00\x00\x00\x00\x00\x60\x00\x00\x00\x03"
        );
        assert_eq!(
            hex(&prepared[80..112]),
            "794c1ddac20cb20b78ad2427d0d51da299198da2b49bb26fa8c1297337b14aea"
        );
    }

    #[test]
    fn fragmented_reads_and_exact_256_byte_boundary_fail_closed() {
        let (mut writer, mut reader) = UnixStream::pair().unwrap();
        let encoded = encode_frame(&Frame::Hello {
            startup_nonce: STARTUP,
            lease_nonce: LEASE,
        })
        .unwrap();
        let task = thread::spawn(move || write_fragmented(&mut writer, &encoded));
        assert!(matches!(read_frame(&mut reader), Ok(Frame::Hello { .. })));
        task.join().unwrap();

        let mut exact_header = [0_u8; HEADER_BYTES];
        exact_header[..4].copy_from_slice(MAGIC);
        exact_header[4] = 1;
        exact_header[5] = FrameKind::Grant as u8;
        exact_header[8..12].copy_from_slice(&240_u32.to_be_bytes());
        exact_header[12..16].copy_from_slice(&2_u32.to_be_bytes());
        assert!(matches!(
            decode_header(&exact_header),
            Err(KeyLeaseError::InvalidFrame)
        ));

        let mut oversized = exact_header;
        oversized[8..12].copy_from_slice(&241_u32.to_be_bytes());
        assert!(matches!(
            decode_header(&oversized),
            Err(KeyLeaseError::InvalidFrame)
        ));
    }

    #[test]
    fn header_rejects_wrong_flags_lengths_sequences_and_unknown_kinds() {
        let encoded = encode_frame(&Frame::Hello {
            startup_nonce: STARTUP,
            lease_nonce: LEASE,
        })
        .unwrap();
        for (offset, value) in [(6, 1), (11, 49), (15, 1), (5, 99)] {
            let mut header: [u8; HEADER_BYTES] = encoded[..HEADER_BYTES].try_into().unwrap();
            header[offset] = value;
            assert!(decode_header(&header).is_err());
        }
    }

    #[test]
    fn fixed_descriptor_is_reserved_cloexec_without_overwrite() {
        let _guard = FD_TEST_LOCK.lock().unwrap();
        let (broker, _handle, child) = KeyLeaseBroker::socket_pair(STARTUP).unwrap();
        assert_eq!(child.raw_fd(), KEY_LEASE_CHILD_FD);
        assert!(is_cloexec(child.raw_fd()).unwrap());
        assert!(is_cloexec(broker.stream.as_raw_fd()).unwrap());
        assert!(ensure_child_fd_limit().is_ok());
        drop(child);
        drop(broker);
    }

    #[test]
    fn occupied_descriptor_198_fails_without_overwrite() {
        let _guard = FD_TEST_LOCK.lock().unwrap();
        let (source, _peer) = UnixStream::pair().unwrap();
        // SAFETY: this duplicates a valid test descriptor and the returned descriptor
        // is closed below before the test releases its process-wide lock.
        let occupied = unsafe {
            libc::fcntl(
                source.as_raw_fd(),
                libc::F_DUPFD_CLOEXEC,
                KEY_LEASE_CHILD_FD,
            )
        };
        assert_eq!(occupied, KEY_LEASE_CHILD_FD);
        assert!(matches!(
            KeyLeaseBroker::socket_pair(STARTUP),
            Err(KeyLeaseError::ChildDescriptorOccupied)
        ));
        // SAFETY: occupied is uniquely owned by this test.
        unsafe {
            libc::close(occupied);
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn configured_child_exec_inherits_only_reserved_descriptor() {
        let guard = FD_TEST_LOCK.lock().unwrap();
        let (broker, _handle, child) = KeyLeaseBroker::socket_pair(STARTUP).unwrap();
        let mut command = Command::new("/bin/ls");
        command
            .arg("/dev/fd/198")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        child.configure_command(&mut command);
        let mut process = command.spawn().unwrap();
        drop(child);
        drop(guard);
        assert!(process.wait().await.unwrap().success());
        assert!(is_cloexec(broker.stream.as_raw_fd()).unwrap());
    }

    #[test]
    fn authorization_waits_in_idle_without_a_key_or_short_deadline() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        thread::sleep(Duration::from_millis(10));
        let descriptor = handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        assert_eq!(descriptor.vault_id, VAULT);
        assert_eq!(broker.state, BrokerState::Idle);
    }

    #[test]
    fn successful_sequence_fetches_after_exact_request_and_zeroizes() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        let descriptor = handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        let authorized_binding = {
            let shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_ref().unwrap().binding.clone()
        };
        assert_eq!(descriptor.transaction_id, authorized_binding.transaction_id);
        let context = authorized_binding.final_context();
        let dropped = Arc::new(AtomicBool::new(false));
        let key_dropped = Arc::clone(&dropped);

        let peer = thread::spawn(move || {
            write_frame(&mut child, &Frame::Request(authorized_binding)).unwrap();
            match read_frame(&mut child).unwrap() {
                Frame::Grant { binding, key } => {
                    assert_eq!(binding.vault_id, VAULT);
                    assert_eq!(key.as_slice(), &[0x5a; KEY_BYTES]);
                }
                frame => panic!("unexpected frame: {frame:?}"),
            }
            write_frame(&mut child, &Frame::Prepared(context)).unwrap();
            assert!(matches!(read_frame(&mut child), Ok(Frame::Commit(value)) if value == context));
            write_frame(&mut child, &Frame::Committed(context)).unwrap();
        });

        let supplier_called = Arc::new(AtomicBool::new(false));
        let called = Arc::clone(&supplier_called);
        broker
            .run_authorized(
                move |received_reference| {
                    assert_eq!(received_reference, reference());
                    called.store(true, Ordering::SeqCst);
                    Ok(TestKey::new([0x5a; KEY_BYTES], key_dropped))
                },
                || true,
            )
            .unwrap();
        peer.join().unwrap();
        assert!(supplier_called.load(Ordering::SeqCst));
        assert!(dropped.load(Ordering::SeqCst));
        assert_eq!(broker.state, BrokerState::Consumed);
        assert!(matches!(
            handle.authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1
            ),
            Err(KeyLeaseError::Consumed)
        ));
    }

    #[test]
    fn binding_mismatch_and_replay_poison_before_key_fetch() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        let mut mismatch = {
            let shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_ref().unwrap().binding.clone()
        };
        mismatch.vault_id = Uuid::new_v4();
        write_frame(&mut child, &Frame::Request(mismatch)).unwrap();
        let called = Arc::new(AtomicBool::new(false));
        let marker = Arc::clone(&called);
        let result = broker.run_authorized::<TestKey, _, _>(
            move |_| {
                marker.store(true, Ordering::SeqCst);
                unreachable!()
            },
            || true,
        );
        assert!(matches!(result, Err(KeyLeaseError::BindingMismatch)));
        assert!(!called.load(Ordering::SeqCst));
        assert_eq!(broker.state, BrokerState::Poisoned);

        let (mut replay_broker, replay_handle, mut replay_child) = test_channel();
        accept_hello(&mut replay_broker, &mut replay_child);
        replay_handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseCreateV1,
            )
            .unwrap();
        write_frame(
            &mut replay_child,
            &Frame::Hello {
                startup_nonce: STARTUP,
                lease_nonce: LEASE,
            },
        )
        .unwrap();
        assert!(matches!(
            replay_broker.run_authorized::<TestKey, _, _>(|_| unreachable!(), || true),
            Err(KeyLeaseError::ReplayOrUnexpectedFrame)
        ));
    }

    #[test]
    fn every_canonical_binding_field_is_authoritative() {
        let mutators: [fn(&mut UnlockBinding); 8] = [
            |value| value.startup_nonce = Uuid::new_v4(),
            |value| value.lease_nonce = LeaseNonce([0xbb; LEASE_NONCE_BYTES]),
            |value| value.transaction_id = Uuid::new_v4(),
            |value| value.vault_id = Uuid::new_v4(),
            |value| value.manifest_digest = ManifestDigest([0x66; DIGEST_BYTES]),
            |value| {
                value.key_reference =
                    reference_from_canonical(b"kc:v1:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
                        .unwrap();
                value.key_reference_bytes = *b"kc:v1:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
            },
            |value| value.key_version += 1,
            |value| value.operation = LeaseOperation::DatabaseCreateV1,
        ];

        for mutate in mutators {
            let (mut broker, handle, mut child) = test_channel();
            accept_hello(&mut broker, &mut child);
            handle
                .authorize(
                    VAULT,
                    MANIFEST,
                    reference(),
                    7,
                    LeaseOperation::DatabaseUnlockV1,
                )
                .unwrap();
            let mut request_binding = {
                let shared = lock_unpoisoned(&handle.shared);
                shared.pending.as_ref().unwrap().binding.clone()
            };
            mutate(&mut request_binding);
            write_frame(&mut child, &Frame::Request(request_binding)).unwrap();
            let called = Arc::new(AtomicBool::new(false));
            let marker = Arc::clone(&called);
            assert!(matches!(
                broker.run_authorized::<TestKey, _, _>(
                    move |_| {
                        marker.store(true, Ordering::SeqCst);
                        unreachable!()
                    },
                    || true
                ),
                Err(KeyLeaseError::BindingMismatch)
            ));
            assert!(!called.load(Ordering::SeqCst));
            assert_eq!(broker.state, BrokerState::Poisoned);
        }
    }

    #[test]
    fn expired_authorization_poisoned_before_request_or_key_fetch() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        {
            let mut shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_mut().unwrap().expires_at = Instant::now() - Duration::from_millis(1);
        }
        let called = Arc::new(AtomicBool::new(false));
        let marker = Arc::clone(&called);
        assert!(matches!(
            broker.run_authorized::<TestKey, _, _>(
                move |_| {
                    marker.store(true, Ordering::SeqCst);
                    unreachable!()
                },
                || true
            ),
            Err(KeyLeaseError::Expired)
        ));
        assert!(!called.load(Ordering::SeqCst));
        assert_eq!(broker.state, BrokerState::Poisoned);
    }

    #[test]
    fn revocation_after_prepared_fails_closed_and_drops_key() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseCreateV1,
            )
            .unwrap();
        let authorized = {
            let shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_ref().unwrap().binding.clone()
        };
        let context = authorized.final_context();
        let dropped = Arc::new(AtomicBool::new(false));
        write_frame(&mut child, &Frame::Request(authorized)).unwrap();
        let mut peer = child.try_clone().unwrap();
        let task = thread::spawn(move || {
            let _ = read_frame(&mut peer).unwrap();
            write_frame(&mut peer, &Frame::Prepared(context)).unwrap();
        });
        let drop_marker = Arc::clone(&dropped);
        let checks = AtomicUsize::new(0);
        assert!(matches!(
            broker.run_authorized(
                move |_| Ok(TestKey::new([0x33; KEY_BYTES], drop_marker)),
                || checks.fetch_add(1, Ordering::SeqCst) == 0
            ),
            Err(KeyLeaseError::CommitRevoked)
        ));
        task.join().unwrap();
        assert!(dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn revocation_during_key_retrieval_never_sends_grant() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        let authorized = {
            let shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_ref().unwrap().binding.clone()
        };
        write_frame(&mut child, &Frame::Request(authorized)).unwrap();
        child
            .set_read_timeout(Some(Duration::from_millis(250)))
            .unwrap();

        let still_authorized = Arc::new(AtomicBool::new(true));
        let supplier_authorized = Arc::clone(&still_authorized);
        let dropped = Arc::new(AtomicBool::new(false));
        let marker = Arc::clone(&dropped);
        assert!(matches!(
            broker.run_authorized(
                move |_| {
                    supplier_authorized.store(false, Ordering::SeqCst);
                    Ok(TestKey::new([0x35; KEY_BYTES], marker))
                },
                || still_authorized.load(Ordering::SeqCst)
            ),
            Err(KeyLeaseError::CommitRevoked)
        ));
        assert!(read_frame(&mut child).is_err());
        assert!(dropped.load(Ordering::SeqCst));
        assert_eq!(broker.state, BrokerState::Poisoned);
    }

    #[test]
    fn post_committed_trailing_frame_poisoned() {
        let (mut broker, handle, mut child) = test_channel();
        accept_hello(&mut broker, &mut child);
        handle
            .authorize(
                VAULT,
                MANIFEST,
                reference(),
                7,
                LeaseOperation::DatabaseUnlockV1,
            )
            .unwrap();
        let authorized = {
            let shared = lock_unpoisoned(&handle.shared);
            shared.pending.as_ref().unwrap().binding.clone()
        };
        let context = authorized.final_context();
        let task = thread::spawn(move || {
            write_frame(&mut child, &Frame::Request(authorized)).unwrap();
            let _ = read_frame(&mut child).unwrap();
            write_frame(&mut child, &Frame::Prepared(context)).unwrap();
            let _ = read_frame(&mut child).unwrap();
            let committed = encode_frame(&Frame::Committed(context)).unwrap();
            let trailing = encode_frame(&Frame::Hello {
                startup_nonce: STARTUP,
                lease_nonce: LEASE,
            })
            .unwrap();
            let mut combined = Vec::with_capacity(committed.len() + trailing.len());
            combined.extend_from_slice(&committed);
            combined.extend_from_slice(&trailing);
            child.write_all(&combined).unwrap();
        });
        let dropped = Arc::new(AtomicBool::new(false));
        let marker = Arc::clone(&dropped);
        assert!(matches!(
            broker.run_authorized(
                move |_| Ok(TestKey::new([0x44; KEY_BYTES], marker)),
                || true
            ),
            Err(KeyLeaseError::TrailingFrame)
        ));
        task.join().unwrap();
        assert!(dropped.load(Ordering::SeqCst));
        assert_eq!(broker.state, BrokerState::Poisoned);
    }

    #[test]
    fn malformed_reference_and_operation_are_rejected() {
        let mut encoded = binding(LeaseOperation::DatabaseUnlockV1).encode();
        encoded[112] = b'X';
        assert!(UnlockBinding::decode(&encoded).is_err());

        let mut invalid_operation = binding(LeaseOperation::DatabaseUnlockV1).encode();
        invalid_operation[158..160].copy_from_slice(&99_u16.to_be_bytes());
        assert!(UnlockBinding::decode(&invalid_operation).is_err());
    }

    #[test]
    fn errors_and_debug_never_disclose_keys_or_binding_identifiers() {
        let secret = Frame::Grant {
            binding: binding(LeaseOperation::DatabaseUnlockV1),
            key: Zeroizing::new([0xab; KEY_BYTES]),
        };
        let diagnostics = format!(
            "{secret:?} {:?} {}",
            binding(LeaseOperation::DatabaseUnlockV1),
            KeyLeaseError::BindingMismatch
        );
        assert!(!diagnostics.contains("abab"));
        assert!(!diagnostics.contains(&VAULT.to_string()));
        assert!(!diagnostics.contains(&REFERENCE.to_string()));
    }

    #[test]
    fn hello_signal_can_be_observed_before_later_authorization() {
        let (mut broker, _handle, mut child) = test_channel();
        let (sender, receiver) = mpsc::channel();
        let (release_sender, release_receiver) = mpsc::channel();
        let task = thread::spawn(move || {
            write_frame(
                &mut child,
                &Frame::Hello {
                    startup_nonce: STARTUP,
                    lease_nonce: LEASE,
                },
            )
            .unwrap();
            sender.send(()).unwrap();
            release_receiver.recv().unwrap();
        });
        receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(broker.accept_hello().unwrap(), HelloAccepted);
        release_sender.send(()).unwrap();
        task.join().unwrap();
        assert_eq!(broker.state, BrokerState::Idle);
    }
}
