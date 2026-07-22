# Verification entry points are intentionally layered: phase checks exercise
# privacy, encrypted storage, contracts, Rust shell, packaging scripts, and UI.
.PHONY: bootstrap privacy-check privacy-check-staged frontend-check core-sync core-driver-check core-format core-lint core-typecheck core-test contracts-check rust-check sidecar-scripts-check sqlcipher-package-spike frozen-sidecar-spike stage-frozen-sidecar package-spike-app package-spike-app-check phase2-check phase3-check phase4-check phase5-check

RUST_PATH = PATH="/opt/homebrew/opt/rustup/bin:$(PATH)"

bootstrap: core-sync
	corepack pnpm install --frozen-lockfile

privacy-check:
	python3 scripts/privacy_check.py

privacy-check-staged:
	python3 scripts/privacy_check.py --staged

frontend-check:
	corepack pnpm typecheck
	corepack pnpm lint
	corepack pnpm test
	corepack pnpm build

core-sync:
	scripts/bootstrap_core.sh

core-driver-check:
	uv run --project services/core --frozen python -c 'from pysqlcipher3 import dbapi2 as db; connection = db.connect(":memory:"); assert callable(getattr(connection, "set_raw_key", None)); connection.close()'

core-format:
	uv run --project services/core --frozen ruff format services/core

core-lint:
	uv run --project services/core --frozen ruff format --check services/core
	uv run --project services/core --frozen ruff check services/core

core-typecheck:
	uv run --project services/core --frozen mypy services/core/src

core-test:
	uv run --project services/core --frozen pytest services/core/tests

contracts-check:
	uv run --project services/core --frozen python -m ariadne_core.cli generate-contracts --check

rust-check:
	$(RUST_PATH) cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
	$(RUST_PATH) cargo clippy --locked --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
	$(RUST_PATH) cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml

sidecar-scripts-check:
	bash -n scripts/package-sidecar/build_sqlcipher_commoncrypto.sh scripts/package-sidecar/inspect_sqlcipher_commoncrypto.sh scripts/package-sidecar/freeze_pyinstaller.sh scripts/package-sidecar/inspect_frozen_sidecar.sh scripts/package-sidecar/stage_tauri_sidecar.sh
	uv run --project services/core --frozen ruff format --check scripts/package-sidecar/runtime_probe.py scripts/package-sidecar/verify_frozen_sidecar.py scripts/package-sidecar/verify_packaged_app.py
	uv run --project services/core --frozen ruff check scripts/package-sidecar/runtime_probe.py scripts/package-sidecar/verify_frozen_sidecar.py scripts/package-sidecar/verify_packaged_app.py

sqlcipher-package-spike:
	scripts/package-sidecar/build_sqlcipher_commoncrypto.sh

frozen-sidecar-spike:
	scripts/package-sidecar/freeze_pyinstaller.sh

stage-frozen-sidecar:
	@test -n "$(FROZEN_OUTPUT_ROOT)" || { printf 'FROZEN_OUTPUT_ROOT is required\n' >&2; exit 2; }
	scripts/package-sidecar/stage_tauri_sidecar.sh "$(FROZEN_OUTPUT_ROOT)"

package-spike-app:
	@test -x apps/desktop/src-tauri/binaries/ariadne-core-aarch64-apple-darwin || { printf 'stage the frozen sidecar first\n' >&2; exit 2; }
	$(RUST_PATH) corepack pnpm --filter @ariadne/desktop tauri build --config src-tauri/tauri.packaging-spike.conf.json --bundles app

package-spike-app-check:
	uv run --project services/core --frozen python scripts/package-sidecar/verify_packaged_app.py "apps/desktop/src-tauri/target/release/bundle/macos/Codename Ariadne.app"

phase2-check: privacy-check core-driver-check core-lint core-typecheck core-test contracts-check rust-check sidecar-scripts-check frontend-check

phase3-check: privacy-check core-driver-check core-lint core-typecheck core-test contracts-check rust-check sidecar-scripts-check frontend-check

phase4-check: privacy-check core-driver-check core-lint core-typecheck core-test contracts-check rust-check sidecar-scripts-check frontend-check

phase5-check: privacy-check core-driver-check core-lint core-typecheck core-test contracts-check rust-check sidecar-scripts-check frontend-check
