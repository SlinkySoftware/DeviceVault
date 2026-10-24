// SPDX-License-Identifier: GPL-3.0-or-later
// Device-group permission flags and their dependency rules (as in
// orchestrator/accounts/models.py). The API enforces them; these keep the
// editor consistent while ticking boxes.

import type { GrantFlag, GrantFlags } from '@/api/types'

export interface FlagInfo {
  flag: GrantFlag
  label: string
  /** One letter for the access matrix. */
  letter: string
  description: string
}

export const FLAGS: FlagInfo[] = [
  { flag: 'view', label: 'View Status', letter: 'S', description: 'See the group, its devices and their backup jobs' },
  { flag: 'backup_now', label: 'Backup Now', letter: 'B', description: 'Start a backup now' },
  { flag: 'view_contents', label: 'View Contents', letter: 'C', description: 'See and compare backup contents' },
  { flag: 'download', label: 'Download', letter: 'D', description: 'Download backup contents' },
  { flag: 'admin', label: 'Group Admin', letter: 'A', description: "Manage the group's devices and credentials" },
]

/** What each flag needs besides itself. */
export const REQUIRES: Record<GrantFlag, GrantFlag[]> = {
  view: [],
  backup_now: ['view'],
  view_contents: ['view'],
  download: ['view_contents', 'view'],
  admin: ['view', 'backup_now', 'view_contents', 'download'],
}

export function emptyFlags(): GrantFlags {
  return { view: true, backup_now: false, view_contents: false, download: false, admin: false }
}

/**
 * `flags` with `flag` turned on or off: turning a flag on turns on what it
 * needs, turning it off turns off what needs it.
 */
export function setFlag(flags: GrantFlags, flag: GrantFlag, on: boolean): GrantFlags {
  const next = { ...flags, [flag]: on }
  if (on) {
    for (const needed of REQUIRES[flag]) next[needed] = true
  } else {
    for (const info of FLAGS) {
      if (REQUIRES[info.flag].includes(flag)) next[info.flag] = false
    }
  }
  return next
}

/** Flags held only because a ticked flag needs them; the editor shows them ticked and disabled. */
export function lockedFlags(flags: GrantFlags): Set<GrantFlag> {
  const locked = new Set<GrantFlag>()
  for (const info of FLAGS) {
    if (flags[info.flag]) for (const needed of REQUIRES[info.flag]) locked.add(needed)
  }
  return locked
}

/** "S B C" style summary of held flags, in order. */
export function flagLetters(held: Iterable<GrantFlag>): string {
  const set = new Set(held)
  return FLAGS.filter((info) => set.has(info.flag))
    .map((info) => info.letter)
    .join(' ')
}

export function heldFlags(flags: GrantFlags): GrantFlag[] {
  return FLAGS.filter((info) => flags[info.flag]).map((info) => info.flag)
}
