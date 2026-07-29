#![allow(
    dead_code,
    reason = "managed key custody is reserved for the next vault unlock slice"
)]

//! macOS key custody represented by opaque references and zeroizing leases.
//!
//! Raw vault keys are generated and retrieved only inside this native module;
//! logs, renderer messages, manifests, and errors carry opaque references only.

use std::{fmt, sync::Arc};

#[cfg(test)]
use std::{collections::HashMap, sync::Mutex};

use uuid::{Uuid, Variant};
use zeroize::Zeroizing;

const KEY_BYTES: usize = 32;
const OPAQUE_REFERENCE_PREFIX: &str = "kc:v1:";
const VAULT_KEYCHAIN_SERVICE: &str = "app.codenameariadne.desktop.vault-key.v1";

#[cfg(test)]
const MANUAL_TEST_KEYCHAIN_SERVICE: &str = "app.codenameariadne.desktop.manual-test.vault-key.v1";

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub(crate) struct KeyReference {
    namespace: KeyNamespace,
    id: Uuid,
}

impl KeyReference {
    pub(crate) fn new_vault() -> Self {
        Self {
            namespace: KeyNamespace::Vault,
            id: Uuid::new_v4(),
        }
    }

    pub(crate) fn parse_vault(value: &str) -> Result<Self, KeyCustodyError> {
        let encoded = value
            .strip_prefix(OPAQUE_REFERENCE_PREFIX)
            .ok_or_else(KeyCustodyError::invalid_reference)?;
        let id = Uuid::parse_str(encoded).map_err(|_| KeyCustodyError::invalid_reference())?;
        if id.hyphenated().to_string() != encoded
            || id.get_version_num() != 4
            || id.get_variant() != Variant::RFC4122
        {
            return Err(KeyCustodyError::invalid_reference());
        }
        Ok(Self {
            namespace: KeyNamespace::Vault,
            id,
        })
    }

    pub(crate) fn opaque_reference(self) -> String {
        format!("{OPAQUE_REFERENCE_PREFIX}{}", self.id.hyphenated())
    }

    fn service(self) -> &'static str {
        match self.namespace {
            KeyNamespace::Vault => VAULT_KEYCHAIN_SERVICE,
            #[cfg(test)]
            KeyNamespace::ManualTest => MANUAL_TEST_KEYCHAIN_SERVICE,
        }
    }

    fn account(self) -> String {
        format!("vault-key/{}", self.id.hyphenated())
    }

    #[cfg(all(test, target_os = "macos"))]
    fn new_manual_test() -> Self {
        Self {
            namespace: KeyNamespace::ManualTest,
            id: Uuid::new_v4(),
        }
    }
}

impl fmt::Debug for KeyReference {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("KeyReference([OPAQUE])")
    }
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
enum KeyNamespace {
    Vault,
    #[cfg(test)]
    ManualTest,
}

pub(crate) struct KeyMaterial {
    bytes: Zeroizing<[u8; KEY_BYTES]>,
}

impl KeyMaterial {
    fn generate() -> Result<Self, KeyCustodyError> {
        let mut bytes = Zeroizing::new([0_u8; KEY_BYTES]);
        getrandom::fill(bytes.as_mut()).map_err(|_| KeyCustodyError::key_generation_failed())?;
        Ok(Self { bytes })
    }

    fn from_zeroizing_vec(bytes: Zeroizing<Vec<u8>>) -> Result<Self, KeyCustodyError> {
        if bytes.len() != KEY_BYTES {
            return Err(KeyCustodyError::invalid_key_length());
        }
        let mut key = Zeroizing::new([0_u8; KEY_BYTES]);
        key.copy_from_slice(bytes.as_slice());
        Ok(Self { bytes: key })
    }

    fn copy_from_slice(bytes: &[u8; KEY_BYTES]) -> Self {
        let mut key = Zeroizing::new([0_u8; KEY_BYTES]);
        key.copy_from_slice(bytes);
        Self { bytes: key }
    }

    pub(crate) fn expose(&self) -> &[u8; KEY_BYTES] {
        &self.bytes
    }
}

impl fmt::Debug for KeyMaterial {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("KeyMaterial([REDACTED])")
    }
}

pub(crate) trait KeyCustodian: Send + Sync {
    fn create_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError>;
    fn get_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError>;
    fn delete_key(&self, reference: &KeyReference) -> Result<(), KeyCustodyError>;
}

#[derive(Clone)]
pub(crate) struct KeyCustody {
    backend: Arc<dyn KeyCustodian>,
}

impl KeyCustody {
    pub(crate) fn platform() -> Self {
        #[cfg(target_os = "macos")]
        let backend: Arc<dyn KeyCustodian> = Arc::new(MacOsKeychainCustodian);

        #[cfg(not(target_os = "macos"))]
        let backend: Arc<dyn KeyCustodian> = Arc::new(UnsupportedKeyCustodian);

        Self { backend }
    }

    #[cfg(test)]
    fn with_backend(backend: Arc<dyn KeyCustodian>) -> Self {
        Self { backend }
    }

    #[cfg(test)]
    pub(crate) fn memory_for_test() -> Self {
        Self::with_backend(Arc::new(TestMemoryKeyCustodian::default()))
    }

    #[allow(dead_code, reason = "reserved for the next vault unlock slice")]
    pub(crate) fn create_key(
        &self,
        reference: &KeyReference,
    ) -> Result<KeyMaterial, KeyCustodyError> {
        self.backend.create_key(reference)
    }

    #[allow(dead_code, reason = "reserved for the next vault unlock slice")]
    pub(crate) fn get_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        self.backend.get_key(reference)
    }

    #[allow(dead_code, reason = "reserved for the next vault unlock slice")]
    pub(crate) fn delete_key(&self, reference: &KeyReference) -> Result<(), KeyCustodyError> {
        self.backend.delete_key(reference)
    }
}

#[cfg(test)]
#[derive(Default)]
struct TestMemoryKeyCustodian {
    keys: Mutex<HashMap<KeyReference, Zeroizing<[u8; KEY_BYTES]>>>,
}

#[cfg(test)]
impl KeyCustodian for TestMemoryKeyCustodian {
    fn create_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        let mut keys = self.keys.lock().unwrap();
        if keys.contains_key(reference) {
            return Err(KeyCustodyError::duplicate());
        }
        let key = KeyMaterial::generate()?;
        let mut stored = Zeroizing::new([0_u8; KEY_BYTES]);
        stored.copy_from_slice(key.expose());
        keys.insert(*reference, stored);
        Ok(key)
    }

    fn get_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        let keys = self.keys.lock().unwrap();
        let key = keys.get(reference).ok_or_else(KeyCustodyError::not_found)?;
        Ok(KeyMaterial::copy_from_slice(key))
    }

    fn delete_key(&self, reference: &KeyReference) -> Result<(), KeyCustodyError> {
        if self.keys.lock().unwrap().remove(reference).is_none() {
            return Err(KeyCustodyError::not_found());
        }
        Ok(())
    }
}

impl fmt::Debug for KeyCustody {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("KeyCustody([MANAGED])")
    }
}

#[cfg(target_os = "macos")]
struct MacOsKeychainCustodian;

#[cfg(target_os = "macos")]
impl KeyCustodian for MacOsKeychainCustodian {
    fn create_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        use security_framework::os::macos::keychain::SecKeychain;

        let key = KeyMaterial::generate()?;
        let keychain = SecKeychain::default().map_err(map_security_error)?;
        keychain
            .add_generic_password(reference.service(), &reference.account(), key.expose())
            .map_err(map_security_error)?;
        Ok(key)
    }

    fn get_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        use security_framework::passwords::PasswordOptions;

        let options =
            PasswordOptions::new_generic_password(reference.service(), &reference.account());
        let bytes =
            security_framework::passwords::generic_password(options).map_err(map_security_error)?;
        KeyMaterial::from_zeroizing_vec(Zeroizing::new(bytes))
    }

    fn delete_key(&self, reference: &KeyReference) -> Result<(), KeyCustodyError> {
        security_framework::passwords::delete_generic_password(
            reference.service(),
            &reference.account(),
        )
        .map_err(map_security_error)
    }
}

#[cfg(not(target_os = "macos"))]
struct UnsupportedKeyCustodian;

#[cfg(not(target_os = "macos"))]
impl KeyCustodian for UnsupportedKeyCustodian {
    fn create_key(&self, _reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        Err(KeyCustodyError::backend_unavailable())
    }

    fn get_key(&self, _reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
        Err(KeyCustodyError::backend_unavailable())
    }

    fn delete_key(&self, _reference: &KeyReference) -> Result<(), KeyCustodyError> {
        Err(KeyCustodyError::backend_unavailable())
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) enum KeyCustodyErrorCode {
    Duplicate,
    NotFound,
    PermissionDenied,
    InvalidReference,
    InvalidKeyLength,
    BackendUnavailable,
    KeyGenerationFailed,
    OperationFailed,
}

impl KeyCustodyErrorCode {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Duplicate => "KEYCHAIN_DUPLICATE",
            Self::NotFound => "KEYCHAIN_ITEM_NOT_FOUND",
            Self::PermissionDenied => "KEYCHAIN_PERMISSION_DENIED",
            Self::InvalidReference => "KEYCHAIN_REFERENCE_INVALID",
            Self::InvalidKeyLength => "KEYCHAIN_KEY_LENGTH_INVALID",
            Self::BackendUnavailable => "KEYCHAIN_UNAVAILABLE",
            Self::KeyGenerationFailed => "KEY_GENERATION_FAILED",
            Self::OperationFailed => "KEYCHAIN_OPERATION_FAILED",
        }
    }
}

impl fmt::Debug for KeyCustodyErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) struct KeyCustodyError {
    code: KeyCustodyErrorCode,
}

impl KeyCustodyError {
    pub(crate) const fn code(self) -> KeyCustodyErrorCode {
        self.code
    }

    const fn new(code: KeyCustodyErrorCode) -> Self {
        Self { code }
    }

    const fn duplicate() -> Self {
        Self::new(KeyCustodyErrorCode::Duplicate)
    }

    const fn not_found() -> Self {
        Self::new(KeyCustodyErrorCode::NotFound)
    }

    const fn permission_denied() -> Self {
        Self::new(KeyCustodyErrorCode::PermissionDenied)
    }

    const fn invalid_reference() -> Self {
        Self::new(KeyCustodyErrorCode::InvalidReference)
    }

    const fn invalid_key_length() -> Self {
        Self::new(KeyCustodyErrorCode::InvalidKeyLength)
    }

    const fn backend_unavailable() -> Self {
        Self::new(KeyCustodyErrorCode::BackendUnavailable)
    }

    const fn key_generation_failed() -> Self {
        Self::new(KeyCustodyErrorCode::KeyGenerationFailed)
    }

    const fn operation_failed() -> Self {
        Self::new(KeyCustodyErrorCode::OperationFailed)
    }
}

impl fmt::Debug for KeyCustodyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("KeyCustodyError")
            .field("code", &self.code)
            .finish()
    }
}

impl fmt::Display for KeyCustodyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code.as_str())
    }
}

impl std::error::Error for KeyCustodyError {}

#[cfg(target_os = "macos")]
fn map_security_error(error: security_framework::base::Error) -> KeyCustodyError {
    map_security_status(error.code())
}

#[cfg(target_os = "macos")]
fn map_security_status(status: i32) -> KeyCustodyError {
    use security_framework_sys::base::{
        errSecAuthFailed as ERR_SEC_AUTH_FAILED, errSecDuplicateItem as ERR_SEC_DUPLICATE_ITEM,
        errSecItemNotFound as ERR_SEC_ITEM_NOT_FOUND,
    };

    const ERR_SEC_WRITE_PERMISSION: i32 = -61;
    const ERR_SEC_USER_CANCELED: i32 = -128;
    const ERR_SEC_NO_ACCESS_FOR_ITEM: i32 = -25243;
    const ERR_SEC_NOT_AVAILABLE: i32 = -25291;
    const ERR_SEC_READ_ONLY: i32 = -25292;
    const ERR_SEC_NO_DEFAULT_KEYCHAIN: i32 = -25307;
    const ERR_SEC_INTERACTION_NOT_ALLOWED: i32 = -25308;
    const ERR_SEC_READ_ONLY_ATTRIBUTE: i32 = -25309;
    const ERR_SEC_INTERACTION_REQUIRED: i32 = -25315;

    match status {
        ERR_SEC_DUPLICATE_ITEM => KeyCustodyError::duplicate(),
        ERR_SEC_ITEM_NOT_FOUND => KeyCustodyError::not_found(),
        ERR_SEC_AUTH_FAILED
        | ERR_SEC_WRITE_PERMISSION
        | ERR_SEC_USER_CANCELED
        | ERR_SEC_NO_ACCESS_FOR_ITEM
        | ERR_SEC_READ_ONLY
        | ERR_SEC_INTERACTION_NOT_ALLOWED
        | ERR_SEC_READ_ONLY_ATTRIBUTE
        | ERR_SEC_INTERACTION_REQUIRED => KeyCustodyError::permission_denied(),
        ERR_SEC_NOT_AVAILABLE | ERR_SEC_NO_DEFAULT_KEYCHAIN => {
            KeyCustodyError::backend_unavailable()
        }
        _ => KeyCustodyError::operation_failed(),
    }
}

#[cfg(test)]
mod tests {
    use std::{collections::HashMap, sync::Mutex, thread};

    use super::*;

    #[derive(Default)]
    struct InMemoryKeyCustodian {
        keys: Mutex<HashMap<KeyReference, Zeroizing<[u8; KEY_BYTES]>>>,
    }

    impl KeyCustodian for InMemoryKeyCustodian {
        fn create_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
            let mut keys = self.keys.lock().unwrap();
            if keys.contains_key(reference) {
                return Err(KeyCustodyError::duplicate());
            }

            let key = KeyMaterial::generate()?;
            let mut stored = Zeroizing::new([0_u8; KEY_BYTES]);
            stored.copy_from_slice(key.expose());
            keys.insert(*reference, stored);
            Ok(key)
        }

        fn get_key(&self, reference: &KeyReference) -> Result<KeyMaterial, KeyCustodyError> {
            let keys = self.keys.lock().unwrap();
            let key = keys.get(reference).ok_or_else(KeyCustodyError::not_found)?;
            Ok(KeyMaterial::copy_from_slice(key))
        }

        fn delete_key(&self, reference: &KeyReference) -> Result<(), KeyCustodyError> {
            let removed = self.keys.lock().unwrap().remove(reference);
            if removed.is_none() {
                return Err(KeyCustodyError::not_found());
            }
            Ok(())
        }
    }

    #[test]
    fn opaque_reference_round_trips_without_debug_disclosure() {
        let reference = KeyReference::new_vault();
        let opaque = reference.opaque_reference();

        assert_eq!(KeyReference::parse_vault(&opaque).unwrap(), reference);
        assert_eq!(format!("{reference:?}"), "KeyReference([OPAQUE])");
        assert!(!format!("{reference:?}").contains(&opaque));

        for invalid in [
            "",
            "kc:v2:00000000-0000-4000-8000-000000000001",
            "kc:v1:not-a-uuid",
            "kc:v1:00000000000040008000000000000001",
            "kc:v1:00000000-0000-0000-0000-000000000000",
            "kc:v1:00000000-0000-4000-8000-000000000001:extra",
        ] {
            let error = KeyReference::parse_vault(invalid).unwrap_err();
            assert_eq!(error.code(), KeyCustodyErrorCode::InvalidReference);
        }
    }

    #[test]
    fn key_material_is_exactly_32_bytes_and_debug_redacted() {
        let key = KeyMaterial::generate().unwrap();
        assert_eq!(key.expose().len(), KEY_BYTES);
        assert_eq!(format!("{key:?}"), "KeyMaterial([REDACTED])");

        let short = KeyMaterial::from_zeroizing_vec(Zeroizing::new(vec![7_u8; 31])).unwrap_err();
        assert_eq!(short.code(), KeyCustodyErrorCode::InvalidKeyLength);
        let long = KeyMaterial::from_zeroizing_vec(Zeroizing::new(vec![7_u8; 33])).unwrap_err();
        assert_eq!(long.code(), KeyCustodyErrorCode::InvalidKeyLength);
    }

    #[test]
    fn in_memory_custodian_enforces_create_get_delete_semantics() {
        let custody = KeyCustody::with_backend(Arc::new(InMemoryKeyCustodian::default()));
        let reference = KeyReference::new_vault();

        let created = custody.create_key(&reference).unwrap();
        let fetched = custody.get_key(&reference).unwrap();
        assert_eq!(created.expose(), fetched.expose());

        let duplicate = custody.create_key(&reference).unwrap_err();
        assert_eq!(duplicate.code(), KeyCustodyErrorCode::Duplicate);

        custody.delete_key(&reference).unwrap();
        let missing = custody.get_key(&reference).unwrap_err();
        assert_eq!(missing.code(), KeyCustodyErrorCode::NotFound);
        let missing_delete = custody.delete_key(&reference).unwrap_err();
        assert_eq!(missing_delete.code(), KeyCustodyErrorCode::NotFound);
    }

    #[test]
    fn concurrent_create_has_one_winner_and_safe_duplicate_errors() {
        let custody = KeyCustody::with_backend(Arc::new(InMemoryKeyCustodian::default()));
        let reference = KeyReference::new_vault();
        let workers: Vec<_> = (0..8)
            .map(|_| {
                let custody = custody.clone();
                thread::spawn(move || custody.create_key(&reference).map(|_| ()))
            })
            .collect();

        let results: Vec<_> = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert!(
            results
                .iter()
                .filter_map(|result| result.as_ref().err())
                .all(|error| error.code() == KeyCustodyErrorCode::Duplicate)
        );
    }

    #[test]
    fn safe_errors_and_manager_debug_never_include_references_or_keys() {
        let reference = KeyReference::new_vault();
        let opaque = reference.opaque_reference();
        let key = KeyMaterial::copy_from_slice(&[0x5a; KEY_BYTES]);
        let custody = KeyCustody::with_backend(Arc::new(InMemoryKeyCustodian::default()));
        let error = custody.get_key(&reference).unwrap_err();

        let diagnostics = format!("{custody:?} {reference:?} {key:?} {error:?} {error}");
        assert!(!diagnostics.contains(&opaque));
        assert!(!diagnostics.contains("5a"));
        assert!(diagnostics.contains("KEYCHAIN_ITEM_NOT_FOUND"));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn security_statuses_map_to_stable_safe_codes() {
        use security_framework_sys::base::{
            errSecAuthFailed, errSecDuplicateItem, errSecItemNotFound,
        };

        assert_eq!(
            map_security_status(errSecDuplicateItem).code(),
            KeyCustodyErrorCode::Duplicate
        );
        assert_eq!(
            map_security_status(errSecItemNotFound).code(),
            KeyCustodyErrorCode::NotFound
        );
        for status in [
            errSecAuthFailed,
            -61,
            -128,
            -25243,
            -25292,
            -25308,
            -25309,
            -25315,
        ] {
            assert_eq!(
                map_security_status(status).code(),
                KeyCustodyErrorCode::PermissionDenied
            );
        }
        assert_eq!(
            map_security_status(-25291).code(),
            KeyCustodyErrorCode::BackendUnavailable
        );
        assert_eq!(
            map_security_status(i32::MIN).code(),
            KeyCustodyErrorCode::OperationFailed
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    #[ignore = "manual test mutates the user's macOS Keychain and may prompt for access"]
    fn manual_macos_keychain_round_trip_is_isolated_and_cleaned_up() {
        struct Cleanup<'a> {
            backend: &'a MacOsKeychainCustodian,
            reference: KeyReference,
            armed: bool,
        }

        impl Drop for Cleanup<'_> {
            fn drop(&mut self) {
                if self.armed {
                    let _ = self.backend.delete_key(&self.reference);
                }
            }
        }

        let backend = MacOsKeychainCustodian;
        let reference = KeyReference::new_manual_test();
        let mut cleanup = Cleanup {
            backend: &backend,
            reference,
            armed: true,
        };

        let created = backend.create_key(&reference).unwrap();
        let fetched = backend.get_key(&reference).unwrap();
        assert_eq!(created.expose(), fetched.expose());
        backend.delete_key(&reference).unwrap();
        cleanup.armed = false;
    }
}
