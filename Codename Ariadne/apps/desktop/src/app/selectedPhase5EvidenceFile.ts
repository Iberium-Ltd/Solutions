import type { Phase5ManualArtifactKind } from './phase5Boundary'

const MAX_FILE_BYTES = 10 * 1_024 * 1_024

const KIND_FORMATS: Record<
  Phase5ManualArtifactKind,
  ReadonlyArray<{
    readonly suffixes: ReadonlyArray<string>
    readonly mediaTypes: ReadonlySet<string>
  }>
> = {
  SCREENSHOT: [
    { suffixes: ['.png'], mediaTypes: new Set(['', 'image/png']) },
    { suffixes: ['.jpg', '.jpeg'], mediaTypes: new Set(['', 'image/jpeg']) },
    { suffixes: ['.webp'], mediaTypes: new Set(['', 'image/webp']) },
  ],
  HTML: [
    { suffixes: ['.html', '.htm'], mediaTypes: new Set(['', 'text/html']) },
  ],
  PDF: [
    { suffixes: ['.pdf'], mediaTypes: new Set(['', 'application/pdf']) },
  ],
  RAW_JSON: [
    {
      suffixes: ['.json'],
      mediaTypes: new Set(['', 'application/json', 'text/json']),
    },
  ],
}

function validateFileName(name: string): void {
  const unsafe = Array.from(name).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0
    return (
      codePoint <= 31 ||
      (codePoint >= 127 && codePoint <= 159) ||
      codePoint === 0x200e ||
      codePoint === 0x200f ||
      (codePoint >= 0x202a && codePoint <= 0x202e) ||
      (codePoint >= 0x2066 && codePoint <= 0x2069)
    )
  })
  if (
    name.length < 1 ||
    name.length > 255 ||
    name !== name.trim() ||
    unsafe
  ) {
    throw new Error('The selected evidence file name is not supported')
  }
}

function validateKind(file: File, kind: Phase5ManualArtifactKind): void {
  const lowerName = file.name.toLocaleLowerCase('en-US')
  const mediaType = file.type.toLocaleLowerCase('en-US').split(';', 1)[0]
  const format = KIND_FORMATS[kind].find(({ suffixes }) =>
    suffixes.some((suffix) => lowerName.endsWith(suffix)),
  )
  if (format === undefined || !format.mediaTypes.has(mediaType)) {
    throw new Error('The selected evidence file does not match its artifact kind')
  }
}

function encodeBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return btoa(binary)
}

export async function preparePhase5EvidenceFile(
  file: File,
  expectedKind?: Phase5ManualArtifactKind,
): Promise<string> {
  validateFileName(file.name)
  if (file.size < 1 || file.size > MAX_FILE_BYTES) {
    throw new Error('Choose a non-empty evidence file no larger than 10 MiB')
  }
  if (expectedKind !== undefined) validateKind(file, expectedKind)

  const buffer = await file.arrayBuffer()
  if (buffer.byteLength !== file.size) {
    throw new Error('The selected evidence file changed while it was read')
  }
  const bytes = new Uint8Array(buffer)
  try {
    return encodeBase64(bytes)
  } finally {
    bytes.fill(0)
  }
}

export const selectedPhase5EvidenceFileLimits = {
  maximumBytes: MAX_FILE_BYTES,
  acceptedImportSuffixes: {
    SCREENSHOT: '.png,.jpg,.jpeg,.webp',
    HTML: '.html,.htm',
    PDF: '.pdf',
    RAW_JSON: '.json',
  } satisfies Record<Phase5ManualArtifactKind, string>,
} as const
