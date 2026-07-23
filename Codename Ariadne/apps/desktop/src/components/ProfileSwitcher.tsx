/** Persistent profile selector backed by the Phase 3 core boundary and workflow store. */
import { useEffect, useMemo, useState } from 'react'
import { Trash2 } from 'lucide-react'
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

export function NativeProfileSwitcher() {
  const activeProfileId = usePhase3WorkflowStore((state) => state.profileId)
  const setProfileId = usePhase3WorkflowStore((state) => state.setProfileId)
  const [profiles, setProfiles] = useState<ReadonlyArray<ProfileSummary>>([])
  const [hasMore, setHasMore] = useState(false)
  const [loadState, setLoadState] = useState<LoadState>('IDLE')
  const [deleting, setDeleting] = useState(false)

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
    const confirmation = globalThis.prompt?.(
      `Delete "${activeProfile.displayLabel}" and all of its local data?\n\nType the profile name exactly to confirm.`,
    )
    if (confirmation === null || confirmation === undefined) return
    if (confirmation !== activeProfile.displayLabel) {
      globalThis.alert?.('The profile name did not match. Nothing was deleted.')
      return
    }
    setDeleting(true)
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
        confirmationLabel: confirmation,
      })
      forgetRememberedProfile()
      clearPhase3WorkflowMemory()
      setProfiles(latest.profiles.filter(
        (profile) => profile.profileId !== current.profileId,
      ))
      setLoadState('READY')
    } catch {
      globalThis.alert?.(
        'The profile could not be deleted. Refresh and try again while the vault is unlocked.',
      )
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
        onClick={() => { void removeActiveProfile() }}
      >
        <Trash2 size={15} aria-hidden="true" />
      </button>
    </div>
  )
}
