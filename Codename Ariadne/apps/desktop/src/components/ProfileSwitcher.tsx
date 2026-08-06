/** Persistent profile selector backed by the Phase 3 core boundary and workflow store. */
import { useEffect, useId, useMemo, useState } from 'react'
import { Trash2, X } from 'lucide-react'
import type { ProfileSummary } from '../../../../packages/contracts/src/generated/api'
import { deleteProfile, listProfiles } from '../app/phase3Boundary'
import {
  clearPhase3WorkflowMemory,
  forgetRememberedProfile,
  rememberedProfileId,
  usePhase3WorkflowStore,
} from '../app/phase3WorkflowStore'

type LoadState = 'IDLE' | 'LOADING' | 'READY' | 'ERROR'

function initials(label: string): string {
  const parts = label.trim().split(/\s+/u)
  return parts
    .slice(0, 2)
    .map((part) => part.slice(0, 1).toLocaleUpperCase())
    .join('')
}

/** Preserve useful native error text without assuming Tauri rejects with Error. */
function deletionErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim() !== '') return error.message
  if (typeof error === 'string' && error.trim() !== '') return error
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = Reflect.get(error, 'message')
    if (typeof message === 'string' && message.trim() !== '') return message
  }
  return 'The profile could not be deleted. The vault remains unlocked; retry after current work finishes.'
}

export function NativeProfileSwitcher() {
  const activeProfileId = usePhase3WorkflowStore((state) => state.profileId)
  const setProfileId = usePhase3WorkflowStore((state) => state.setProfileId)
  const [profiles, setProfiles] = useState<ReadonlyArray<ProfileSummary>>([])
  const [hasMore, setHasMore] = useState(false)
  const [loadState, setLoadState] = useState<LoadState>('IDLE')
  const [deleting, setDeleting] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [confirmationLabel, setConfirmationLabel] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const confirmationInputId = useId()

  useEffect(() => {
    let cancelled = false
    setLoadState('LOADING')
    void listProfiles()
      .then((result) => {
        if (cancelled) return
        if (activeProfileId === null) {
          const remembered = rememberedProfileId()
          if (remembered !== null && result.profiles.some(
            (profile) => profile.profileId === remembered &&
              ['ACTIVE', 'DRAFT'].includes(profile.status),
          )) {
            setProfileId(remembered)
            return
          }
          if (!result.hasMore) forgetRememberedProfile()
        }
        if (
          activeProfileId !== null &&
          !result.profiles.some(
            (profile) => profile.profileId === activeProfileId,
          ) &&
          !result.hasMore
        ) {
          forgetRememberedProfile()
          clearPhase3WorkflowMemory()
          return
        }
        setProfiles(result.profiles)
        setHasMore(result.hasMore)
        setLoadState('READY')
      })
      .catch(() => {
        if (!cancelled) setLoadState('ERROR')
      })
    return () => {
      cancelled = true
    }
  }, [activeProfileId, setProfileId])

  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.profileId === activeProfileId),
    [activeProfileId, profiles],
  )
  const resumableProfiles = profiles.filter((profile) =>
    ['ACTIVE', 'DRAFT'].includes(profile.status),
  )
  const title = activeProfile?.displayLabel ??
    (activeProfileId !== null
      ? 'Active local profile'
      : loadState === 'LOADING'
        ? 'Loading profiles'
        : loadState === 'ERROR'
          ? 'Profiles unavailable'
          : profiles.length === 0
            ? 'No profiles yet'
            : 'Select profile')
  const detail = activeProfile
    ? `${activeProfile.status.toLocaleLowerCase()} · local vault`
    : 'Choose one to resume'

  const removeActiveProfile = async () => {
    if (!activeProfile || deleting) return
    if (confirmationLabel !== activeProfile.displayLabel) return
    setDeleting(true)
    setDeleteError(null)
    try {
      const latest = await listProfiles()
      const current = latest.profiles.find(
        (profile) => profile.profileId === activeProfile.profileId,
      )
      if (!current) {
        throw new Error('Profile is no longer available')
      }
      await deleteProfile({
        profileId: current.profileId,
        expectedRevision: current.revision,
        confirmationLabel,
      })
      forgetRememberedProfile()
      clearPhase3WorkflowMemory()
      setProfiles(latest.profiles.filter(
        (profile) => profile.profileId !== current.profileId,
      ))
      setLoadState('READY')
      setConfirmationLabel('')
      setDeleteDialogOpen(false)
    } catch (error) {
      setDeleteError(deletionErrorMessage(error))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="profile-switcher-group">
      <label className="profile-switcher">
        <span aria-hidden="true">{activeProfile ? initials(activeProfile.displayLabel) : 'LP'}</span>
        <div>
          <strong>{title}</strong>
          <small>{detail}</small>
        </div>
        <select
          aria-label="Active local profile"
          value={activeProfileId ?? ''}
          disabled={resumableProfiles.length === 0 || deleting}
          onChange={(event) => setProfileId(event.currentTarget.value)}
        >
          <option value="" disabled>
            Select a profile to resume
          </option>
          {profiles.map((profile) => (
            <option
              key={profile.profileId}
              value={profile.profileId}
              disabled={!['ACTIVE', 'DRAFT'].includes(profile.status)}
            >
              {profile.displayLabel}
              {profile.status === 'ACTIVE' ? '' : ` (${profile.status.toLocaleLowerCase()})`}
            </option>
          ))}
          {hasMore ? <option disabled>More profiles are not shown</option> : null}
        </select>
      </label>
      <button
        className="profile-delete-button"
        type="button"
        aria-label="Delete active local profile"
        title="Delete active local profile"
        disabled={!activeProfile || deleting}
        onClick={() => {
          setConfirmationLabel('')
          setDeleteError(null)
          setDeleteDialogOpen(true)
        }}
      >
        <Trash2 size={15} aria-hidden="true" />
      </button>
      {deleteDialogOpen && activeProfile ? (
        <div
          className="profile-delete-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deleting) {
              setDeleteDialogOpen(false)
            }
          }}
        >
          <section
            aria-labelledby={`${confirmationInputId}-title`}
            aria-modal="true"
            className="profile-delete-dialog"
            role="dialog"
          >
            <button
              aria-label="Close profile deletion"
              className="profile-delete-dialog__close"
              disabled={deleting}
              type="button"
              onClick={() => setDeleteDialogOpen(false)}
            >
              <X size={17} aria-hidden="true" />
            </button>
            <span className="eyebrow">Permanent local deletion</span>
            <h2 id={`${confirmationInputId}-title`}>Delete {activeProfile.displayLabel}?</h2>
            <p>
              This removes the profile, identifiers, runs, findings, and saved
              analysis from this Mac. Type the profile name exactly to confirm.
            </p>
            <label htmlFor={confirmationInputId}>Profile name</label>
            <input
              autoFocus
              id={confirmationInputId}
              value={confirmationLabel}
              onChange={(event) => {
                setConfirmationLabel(event.currentTarget.value)
                setDeleteError(null)
              }}
            />
            {deleteError ? (
              <p className="profile-delete-dialog__error" role="alert">{deleteError}</p>
            ) : null}
            <div className="profile-delete-dialog__actions">
              <button
                className="button button--secondary"
                disabled={deleting}
                type="button"
                onClick={() => setDeleteDialogOpen(false)}
              >
                Cancel
              </button>
              <button
                className="button button--danger"
                disabled={
                  deleting || confirmationLabel !== activeProfile.displayLabel
                }
                type="button"
                onClick={() => { void removeActiveProfile() }}
              >
                {deleting ? 'Deleting local data…' : 'Delete profile permanently'}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  )
}
