# Alchemist

Alchemist is a native macOS batch video compressor designed for this Apple-silicon M4 Max machine. It is intentionally local, visual, and direct: add videos, pick a recipe, choose where they go, then let the hardware media engines work.

## Run it

From Finder, double-click [Launch Alchemist.command](Launch%20Alchemist.command), or run:

```zsh
cd "/Volumes/Predator SSD GM7000/New Start/Alchemist"
./Scripts/build-app.sh
open Build/Alchemist.app
```

The build uses the installed Swift toolchain; it does not need FFmpeg, Homebrew, a server, or another app. The finished local app bundle is at `Build/Alchemist.app`.

## What it does

- Drag in individual video files or scan a folder recursively.
- Reads each video’s display resolution, duration, frame rate, codec, and source size.
- Filter the queue by 4K, 1440p, 1080p, 720p, 480p, or other and select/deselect that whole visible group for bulk conversion.
- Start with Smart, Near-original, Balanced, Smallest file, Share anywhere, or a custom recipe.
- Set a quality dial, target resolution, HEVC/H.264 codec, output container, bitrate override, and keyframe cadence.
- Export to a chosen folder with the same base filename, or export safely beside the original as `Name · Alchemist.mp4` / `.mov`.
- Enable **Replace originals after success** for compatible MP4/M4V/MOV files. Alchemist writes a unique hidden staging file first, completes the encode, and then uses macOS’s replacement API instead of deleting the source first.
- Choose a performance lane count. Turbo uses two simultaneous encodes, which matches the M4 Max’s two general-purpose video encode engines. M4 Max mode allows four queued active lanes if maximum throughput matters more than contention, heat, and battery.

## How compression is controlled

The quality dial maps to an adaptive VBR bitrate based on output pixels and frame rate. It is intentionally not a fake “quality” switch: selecting smaller resolution, HEVC, and a lower dial gives the largest real savings. Smart defaults to HEVC and preserves source resolution; Smallest file defaults to 720p and a low VBR target.

The encode engine is `AVAssetReader → AVAssetReaderVideoCompositionOutput → AVAssetWriter`. That means rotation is baked in correctly, resizing is real, and AVFoundation uses Apple’s hardware H.264/HEVC encoders on this Mac. Multiple jobs are bounded so the media engines stay busy without spawning sixteen encoders that would simply fight over disk, memory, and the same hardware blocks.

## Notes

- HEVC is the best default for a personal M4 Max workflow. Choose H.264 only when broad compatibility matters more than size.
- Standard SDR MP4/MOV sources are the main target. AVFoundation may reject unusual containers/codecs even if they are named as video files.
- The current pipeline emits SDR 8-bit H.264/HEVC. HDR, Dolby Vision, alpha video, spatial metadata, and subtitle streams need a dedicated preservation path and are not claimed as losslessly preserved here.
- Replacing originals is deliberately unavailable for incompatible source/container combinations; use a chosen output folder for those files.

## Development

```zsh
swift build
swift run
./Scripts/smoke-test.sh
```

The project is a self-contained Swift Package. `Sources/Alchemist/Services/TranscodeEngine.swift` contains the hardware writer pipeline, `App/AppModel.swift` coordinates folder scans and bounded parallel work, and `UI/AppShellView.swift` contains the SwiftUI interface and motion system.

`Scripts/smoke-test.sh` is an end-to-end, dependency-free gate for this particular Mac: it makes a temporary 960×540 H.264 clip, validates a HEVC 852×480 chosen-folder export without changing the source, then validates the atomic replace-original path. It exists because the installed Command Line Tools do not include XCTest.
