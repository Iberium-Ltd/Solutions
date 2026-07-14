import { useEffect, useMemo, useState } from 'react'
import type { ProfileSummary } from '../../../../packages/contracts/src/generated/api'
import { listProfiles } from '../app/phase3Boundary'
import {
  clearPhase3WorkflowMemory,
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

  useEffect(() => {
    let cancelled = false
    setLoadState('LOADING')
    void listProfiles()
      .then((result) => {
        if (cancelled) return
        if (
          activeProfileId !== null &&
          !result.profiles.some(
            (profile) => profile.profileId === activeProfileId,
          ) &&
          !result.hasMore
        ) {
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
  }, [activeProfileId])

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

  return (
    <label className="profile-switcher">
      <span aria-hidden="true">{activeProfile ? initials(activeProfile.displayLabel) : 'LP'}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
      <select
        aria-label="Active local profile"
        value={activeProfileId ?? ''}
        disabled={resumableProfiles.length === 0}
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
  )
}
