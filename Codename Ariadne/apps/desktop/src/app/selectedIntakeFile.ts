const MAX_FILE_BYTES = 1_048_576

const FORMATS = {
  '.txt': {
    mediaType: 'text/plain',
    // WebKit/macOS may content-sniff comma-delimited inert text as text/csv.
    acceptedMediaTypes: new Set(['', 'text/plain', 'text/csv']),
  },
  '.md': {
    mediaType: 'text/markdown',
    acceptedMediaTypes: new Set(['', 'text/markdown', 'text/x-markdown']),
  },
  '.csv': {
    mediaType: 'text/csv',
    acceptedMediaTypes: new Set(['', 'text/csv']),
  },
  '.json': {
    mediaType: 'application/json',
    acceptedMediaTypes: new Set(['', 'application/json']),
  },
  '.vcf': {
    mediaType: 'text/vcard',
    acceptedMediaTypes: new Set(['', 'text/vcard', 'text/x-vcard']),
  },
} as const

type AllowedSuffix = keyof typeof FORMATS

export interface PreparedSelectedFile {
  readonly contentBase64: string
  readonly declaredMediaType: string
  readonly displayName: string
  readonly expectedSha256: string
  readonly expectedSizeBytes: number
}

function suffixOf(name: string): AllowedSuffix | null {
  const dot = name.lastIndexOf('.')
  if (dot < 0) return null
  const suffix = name.slice(dot).toLocaleLowerCase('en-US')
  return suffix in FORMATS ? (suffix as AllowedSuffix) : null
}

function validateDisplayName(name: string): void {
  const hasUnsafeCodePoint = Array.from(name).some((character) => {
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
    name.length === 0 ||
    name.length > 255 ||
    name !== name.trim() ||
    hasUnsafeCodePoint
  ) {
    throw new Error('The selected file name is not supported')
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

function encodeHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join(
    '',
  )
}

export async function prepareSelectedIntakeFile(
  file: File,
): Promise<PreparedSelectedFile> {
  validateDisplayName(file.name)
  const suffix = suffixOf(file.name)
  if (suffix === null) {
    throw new Error('Choose a TXT, MD, CSV, JSON, or VCF file')
  }
  if (file.size < 1 || file.size > MAX_FILE_BYTES) {
    throw new Error('Choose a non-empty file no larger than 1 MiB')
  }

  const format = FORMATS[suffix]
  const browserMediaType = file.type.toLocaleLowerCase('en-US').split(';', 1)[0]
  if (!format.acceptedMediaTypes.has(browserMediaType)) {
    throw new Error('The file type does not match its extension')
  }

  const buffer = await file.arrayBuffer()
  if (buffer.byteLength !== file.size) {
    throw new Error('The selected file changed while it was being read')
  }
  const bytes = new Uint8Array(buffer)
  try {
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    return {
      contentBase64: encodeBase64(bytes),
      declaredMediaType: format.mediaType,
      displayName: file.name,
      expectedSha256: encodeHex(new Uint8Array(digest)),
      expectedSizeBytes: bytes.byteLength,
    }
  } finally {
    bytes.fill(0)
  }
}

export const selectedIntakeFileLimits = {
  maximumBytes: MAX_FILE_BYTES,
  allowedSuffixes: Object.freeze(Object.keys(FORMATS)),
}
