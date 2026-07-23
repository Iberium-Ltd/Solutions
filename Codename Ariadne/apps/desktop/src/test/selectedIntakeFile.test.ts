/** Proves selected file bytes remain bounded and transient until explicit intake. */
import { describe, expect, it } from 'vitest'
import {
  prepareSelectedIntakeFile,
  selectedIntakeFileLimits,
} from '../app/selectedIntakeFile'

describe('browser-selected intake file boundary', () => {
  it('prepares one bounded allowed file without exposing a path', async () => {
    const file = new File(['synthetic local note'], 'local_note.txt', {
      type: 'text/plain',
    })

    const prepared = await prepareSelectedIntakeFile(file)

    expect(prepared).toEqual({
      contentBase64: 'c3ludGhldGljIGxvY2FsIG5vdGU=',
      declaredMediaType: 'text/plain',
      displayName: 'local_note.txt',
      expectedSha256:
        'b4a6b849ebe96e458a9434270df06d05d2c918afd2544a9e498ae32f69b8bc58',
      expectedSizeBytes: 20,
    })
    expect(prepared).not.toHaveProperty('path')
  })

  it('accepts a txt file that macOS content-sniffs as csv while declaring plain text', async () => {
    const prepared = await prepareSelectedIntakeFile(
      new File(['kind,value\nusername,synthetic_handle'], 'labelled_note.txt', {
        type: 'text/csv',
      }),
    )

    expect(prepared.declaredMediaType).toBe('text/plain')
    expect(prepared.displayName).toBe('labelled_note.txt')
  })

  it('rejects mismatched, unsupported, empty, and oversized files before encoding', async () => {
    await expect(
      prepareSelectedIntakeFile(
        new File(['{}'], 'local_note.json', { type: 'text/csv' }),
      ),
    ).rejects.toThrow('does not match')
    await expect(
      prepareSelectedIntakeFile(new File(['x'], 'local_note.pdf')),
    ).rejects.toThrow('TXT, MD, CSV, JSON, or VCF')
    await expect(
      prepareSelectedIntakeFile(new File([], 'local_note.txt')),
    ).rejects.toThrow('non-empty')
    await expect(
      prepareSelectedIntakeFile(
        new File(
          [new Uint8Array(selectedIntakeFileLimits.maximumBytes + 1)],
          'local_note.txt',
        ),
      ),
    ).rejects.toThrow('1 MiB')
  })

  it('rejects control and bidirectional filename characters', async () => {
    await expect(
      prepareSelectedIntakeFile(new File(['x'], 'safe\u202Etxt.md')),
    ).rejects.toThrow('file name')
  })
})
