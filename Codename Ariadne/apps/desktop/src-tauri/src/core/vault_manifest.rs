//! Canonical, non-secret vault manifest validation.
//!
//! The manifest binds opaque Keychain references and database identity. Reads
//! reject symlinks, wrong ownership/mode, non-canonical JSON, or a missing
//! encrypted database so unlock can never silently create a replacement vault.

use std::{
    fmt,
    fs::{self, File, OpenOptions},
    io::{self, Read},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::{Uuid, Variant};

use crate::security::key_custody::KeyReference;

use super::key_lease::ManifestDigest;

const FORMAT_VERSION: u32 = 1;
const DATABASE_KEY_VERSION: u32 = 1;
const MAX_MANIFEST_BYTES: u64 = 4096;
const MANIFEST_FILENAME: &str = "vault.json";
const DATABASE_FILENAME: &str = "vault.db";

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct WireManifest {
    // Declaration order is the version-1 canonical JSON key order and therefore
    // part of the digest contract. Reordering fields requires a format version.
    backup_key_ref: String,
    database_key_ref: String,
    database_key_version: u32,
    format_version: u32,
    vault_id: String,
}

pub(crate) struct VaultManifest {
    vault_id: Uuid,
    database_key_ref: KeyReference,
    backup_key_ref: KeyReference,
    database_key_version: u32,
    #[cfg(test)]
    canonical: Vec<u8>,
    digest: [u8; 32],
}

impl fmt::Debug for VaultManifest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("VaultManifest([VALIDATED])")
    }
}

impl VaultManifest {
    pub(crate) fn new(
        vault_id: Uuid,
        database_key_ref: KeyReference,
        backup_key_ref: KeyReference,
    ) -> Result<Self, VaultManifestError> {
        if vault_id.get_variant() != Variant::RFC4122 || database_key_ref == backup_key_ref {
            return Err(VaultManifestError::Invalid);
        }
        let wire = WireManifest {
            backup_key_ref: backup_key_ref.opaque_reference(),
            database_key_ref: database_key_ref.opaque_reference(),
            database_key_version: DATABASE_KEY_VERSION,
            format_version: FORMAT_VERSION,
            vault_id: vault_id.hyphenated().to_string(),
        };
        Self::from_wire(wire, None)
    }

    pub(crate) fn load_for_unlock(root: &Path) -> Result<Self, VaultManifestError> {
        validate_root(root)?;
        let encoded = read_private_regular_file(&root.join(MANIFEST_FILENAME), 0o600, true)?;
        validate_private_database(&root.join(DATABASE_FILENAME))?;
        let wire: WireManifest =
            serde_json::from_slice(&encoded).map_err(|_| VaultManifestError::Invalid)?;
        Self::from_wire(wire, Some(encoded))
    }

    fn from_wire(
        wire: WireManifest,
        expected_canonical: Option<Vec<u8>>,
    ) -> Result<Self, VaultManifestError> {
        if wire.format_version != FORMAT_VERSION
            || wire.database_key_version != DATABASE_KEY_VERSION
        {
            return Err(VaultManifestError::UnsupportedVersion);
        }
        let vault_id = Uuid::parse_str(&wire.vault_id).map_err(|_| VaultManifestError::Invalid)?;
        if vault_id.hyphenated().to_string() != wire.vault_id
            || vault_id.get_variant() != Variant::RFC4122
        {
            return Err(VaultManifestError::Invalid);
        }
        let database_key_ref = KeyReference::parse_vault(&wire.database_key_ref)
            .map_err(|_| VaultManifestError::Invalid)?;
        let backup_key_ref = KeyReference::parse_vault(&wire.backup_key_ref)
            .map_err(|_| VaultManifestError::Invalid)?;
        if database_key_ref == backup_key_ref {
            return Err(VaultManifestError::Invalid);
        }
        let canonical = serde_json::to_vec(&wire).map_err(|_| VaultManifestError::Invalid)?;
        if canonical.len() as u64 > MAX_MANIFEST_BYTES
            || expected_canonical
                .as_ref()
                .is_some_and(|expected| expected != &canonical)
        {
            return Err(VaultManifestError::NonCanonical);
        }
        let digest = Sha256::digest(&canonical).into();
        Ok(Self {
            vault_id,
            database_key_ref,
            backup_key_ref,
            database_key_version: wire.database_key_version,
            #[cfg(test)]
            canonical,
            digest,
        })
    }

    pub(crate) const fn vault_id(&self) -> Uuid {
        self.vault_id
    }

    pub(crate) const fn database_key_ref(&self) -> KeyReference {
        self.database_key_ref
    }

    pub(crate) const fn backup_key_ref(&self) -> KeyReference {
        self.backup_key_ref
    }

    pub(crate) const fn database_key_version(&self) -> u32 {
        self.database_key_version
    }

    pub(crate) const fn format_version(&self) -> u32 {
        FORMAT_VERSION
    }

    pub(crate) fn manifest_digest(&self) -> ManifestDigest {
        ManifestDigest::new(self.digest)
    }

    pub(crate) fn digest_hex(&self) -> String {
        let mut encoded = String::with_capacity(64);
        for byte in self.digest {
            use std::fmt::Write as _;
            write!(&mut encoded, "{byte:02x}").expect("writing to String cannot fail");
        }
        encoded
    }

    #[cfg(test)]
    fn canonical(&self) -> &[u8] {
        &self.canonical
    }
}

pub(crate) fn validate_create_destination(root: &Path) -> Result<(), VaultManifestError> {
    if !root.is_absolute() {
        return Err(VaultManifestError::UnsafeRoot);
    }
    match fs::symlink_metadata(root) {
        Ok(_) => {
            validate_root(root)?;
            if fs::read_dir(root)
                .map_err(VaultManifestError::Io)?
                .next()
                .transpose()
                .map_err(VaultManifestError::Io)?
                .is_some()
            {
                return Err(VaultManifestError::DestinationNotEmpty);
            }
            Ok(())
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(VaultManifestError::Io(error)),
    }
}

fn validate_root(root: &Path) -> Result<(), VaultManifestError> {
    if !root.is_absolute() {
        return Err(VaultManifestError::UnsafeRoot);
    }
    let metadata = fs::symlink_metadata(root).map_err(VaultManifestError::Io)?;
    if !metadata.file_type().is_dir()
        || metadata.permissions().mode() & 0o777 != 0o700
        || metadata.uid() != effective_uid()
    {
        return Err(VaultManifestError::UnsafeRoot);
    }
    Ok(())
}

fn validate_private_database(path: &Path) -> Result<(), VaultManifestError> {
    let file = open_no_follow(path)?;
    validate_private_file(&file, 0o600)
}

fn read_private_regular_file(
    path: &Path,
    mode: u32,
    bounded: bool,
) -> Result<Vec<u8>, VaultManifestError> {
    let file = open_no_follow(path)?;
    validate_private_file(&file, mode)?;
    let maximum = if bounded {
        MAX_MANIFEST_BYTES + 1
    } else {
        u64::MAX
    };
    let mut encoded = Vec::new();
    file.take(maximum)
        .read_to_end(&mut encoded)
        .map_err(VaultManifestError::Io)?;
    if encoded.is_empty() || encoded.len() as u64 > MAX_MANIFEST_BYTES {
        return Err(VaultManifestError::Invalid);
    }
    Ok(encoded)
}

fn open_no_follow(path: &Path) -> Result<File, VaultManifestError> {
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(VaultManifestError::Io)
}

fn validate_private_file(file: &File, mode: u32) -> Result<(), VaultManifestError> {
    let metadata = file.metadata().map_err(VaultManifestError::Io)?;
    if !metadata.file_type().is_file()
        || metadata.permissions().mode() & 0o777 != mode
        || metadata.uid() != effective_uid()
    {
        return Err(VaultManifestError::UnsafeFile);
    }
    Ok(())
}

fn effective_uid() -> u32 {
    // SAFETY: geteuid has no preconditions and does not access memory.
    unsafe { libc::geteuid() }
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum VaultManifestError {
    #[error("vault manifest is invalid")]
    Invalid,
    #[error("vault manifest is not canonical")]
    NonCanonical,
    #[error("vault manifest version is unsupported")]
    UnsupportedVersion,
    #[error("vault root is unsafe")]
    UnsafeRoot,
    #[error("vault file is unsafe")]
    UnsafeFile,
    #[error("vault destination is not empty")]
    DestinationNotEmpty,
    #[error("vault filesystem operation failed")]
    Io(#[source] io::Error),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_manifest_matches_the_python_contract() {
        let vault_id = Uuid::parse_str("018f47e0-72a4-7c91-8f41-112233445566").unwrap();
        let database =
            KeyReference::parse_vault("kc:v1:11111111-1111-4111-8111-111111111111").unwrap();
        let backup =
            KeyReference::parse_vault("kc:v1:22222222-2222-4222-8222-222222222222").unwrap();
        let manifest = VaultManifest::new(vault_id, database, backup).unwrap();

        assert_eq!(
            manifest.canonical(),
            br#"{"backupKeyRef":"kc:v1:22222222-2222-4222-8222-222222222222","databaseKeyRef":"kc:v1:11111111-1111-4111-8111-111111111111","databaseKeyVersion":1,"formatVersion":1,"vaultId":"018f47e0-72a4-7c91-8f41-112233445566"}"#
        );
        assert_eq!(manifest.digest_hex().len(), 64);
        assert_eq!(manifest.database_key_version(), 1);
        assert_eq!(manifest.format_version(), 1);
    }

    #[test]
    fn create_destination_is_missing_or_safe_and_empty() {
        let root = temporary_root("destination");
        assert!(validate_create_destination(&root).is_ok());
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        assert!(validate_create_destination(&root).is_ok());
        fs::write(root.join("unexpected"), b"synthetic").unwrap();
        assert!(matches!(
            validate_create_destination(&root),
            Err(VaultManifestError::DestinationNotEmpty)
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unlock_load_requires_canonical_private_manifest_and_database() {
        let root = temporary_root("unlock");
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let manifest = VaultManifest::new(
            Uuid::new_v4(),
            KeyReference::new_vault(),
            KeyReference::new_vault(),
        )
        .unwrap();
        let manifest_path = root.join(MANIFEST_FILENAME);
        let database_path = root.join(DATABASE_FILENAME);
        fs::write(&manifest_path, manifest.canonical()).unwrap();
        fs::write(&database_path, b"synthetic encrypted database bytes").unwrap();
        fs::set_permissions(&manifest_path, fs::Permissions::from_mode(0o600)).unwrap();
        fs::set_permissions(&database_path, fs::Permissions::from_mode(0o600)).unwrap();

        let loaded = VaultManifest::load_for_unlock(&root).unwrap();
        assert_eq!(loaded.vault_id(), manifest.vault_id());
        assert_eq!(loaded.digest_hex(), manifest.digest_hex());

        let mut noncanonical = manifest.canonical().to_vec();
        noncanonical.push(b'\n');
        fs::write(&manifest_path, noncanonical).unwrap();
        assert!(matches!(
            VaultManifest::load_for_unlock(&root),
            Err(VaultManifestError::NonCanonical)
        ));

        fs::write(&manifest_path, manifest.canonical()).unwrap();
        fs::set_permissions(&database_path, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(matches!(
            VaultManifest::load_for_unlock(&root),
            Err(VaultManifestError::UnsafeFile)
        ));
        fs::remove_dir_all(root).unwrap();
    }

    fn temporary_root(label: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(format!(
            "/tmp/ariadne-manifest-{label}-{}",
            Uuid::new_v4().simple()
        ))
    }
}
