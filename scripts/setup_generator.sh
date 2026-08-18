#!/usr/bin/env bash
#
# Set up the local LeekWars fight generator used by src/localfight.
#
# Everything lands under .cache/ (gitignored): the generator clone, a private
# JDK and Gradle, and the built generator.jar. Nothing is installed system-wide
# and no sudo is needed. Safe to re-run — each step is skipped if already done.
#
# Usage:
#   scripts/setup_generator.sh          # set up / update everything
#   scripts/setup_generator.sh --force  # rebuild the jar even if up to date

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="$ROOT/.cache"
TOOLCHAIN="$CACHE/toolchain"
GENERATOR="$CACHE/leek-wars-generator"

# Pinned so a rebuild is reproducible. The generator requires Java 25 and
# Gradle 9.x (see its README); older toolchains fail to compile it.
JDK_VERSION=25
GRADLE_VERSION=9.1.0
JDK_URL="https://api.adoptium.net/v3/binary/latest/${JDK_VERSION}/ga/linux/x64/jdk/hotspot/normal/eclipse"
GRADLE_URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"

# GraalVM isolate image, needed to package the fat jar. Only JS/Python AIs
# actually execute it, but the jar task unconditionally expands it.
ISOLATE_JAR="js-isolate-resources-linux-amd64.jar"
ISOLATE_URL="https://github.com/leek-wars/leek-wars-graal-isolate/releases/download/v25.1.3-combined-2/${ISOLATE_JAR}"

# The upstream remotes are SSH; use HTTPS so this works without a deploy key.
GENERATOR_REPO="https://github.com/leek-wars/leek-wars-generator.git"
LEEKSCRIPT_REPO="https://github.com/leek-wars/leekscript.git"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

log() { printf '\n==> %s\n' "$1"; }

mkdir -p "$TOOLCHAIN"

# --- JDK ---------------------------------------------------------------
JAVA_HOME="$(find "$TOOLCHAIN" -maxdepth 1 -name "jdk-${JDK_VERSION}*" | sort -r | head -1)"
if [ -z "$JAVA_HOME" ]; then
	log "Downloading JDK ${JDK_VERSION} (~135 MB)"
	curl -fsSL -o "$TOOLCHAIN/jdk.tar.gz" "$JDK_URL"
	tar xzf "$TOOLCHAIN/jdk.tar.gz" -C "$TOOLCHAIN"
	rm -f "$TOOLCHAIN/jdk.tar.gz"
	JAVA_HOME="$(find "$TOOLCHAIN" -maxdepth 1 -name "jdk-${JDK_VERSION}*" | sort -r | head -1)"
fi
export JAVA_HOME
log "JDK: $("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"

# --- Gradle ------------------------------------------------------------
GRADLE="$TOOLCHAIN/gradle-${GRADLE_VERSION}/bin/gradle"
if [ ! -x "$GRADLE" ]; then
	log "Downloading Gradle ${GRADLE_VERSION} (~130 MB)"
	curl -fsSL -o "$TOOLCHAIN/gradle.zip" "$GRADLE_URL"
	unzip -q -o "$TOOLCHAIN/gradle.zip" -d "$TOOLCHAIN"
	rm -f "$TOOLCHAIN/gradle.zip"
fi
log "Gradle: $GRADLE"

# --- Generator sources -------------------------------------------------
if [ ! -d "$GENERATOR/.git" ]; then
	log "Cloning the generator"
	git clone --depth=1 "$GENERATOR_REPO" "$GENERATOR"
else
	log "Updating the generator"
	git -C "$GENERATOR" fetch --depth=1 "$GENERATOR_REPO" master
	git -C "$GENERATOR" reset --hard FETCH_HEAD
fi

# The leekscript submodule is a separate Gradle project (the compiler and
# runtime); the generator will not build against the wrong commit.
LEEKSCRIPT_COMMIT="$(git -C "$GENERATOR" ls-tree HEAD leekscript | awk '{print $3}')"
log "Syncing leekscript submodule to ${LEEKSCRIPT_COMMIT:0:10}"
git -C "$GENERATOR" config submodule.leekscript.url "$LEEKSCRIPT_REPO"
# -e, not -d: in a submodule checkout .git is a file pointing at the gitdir.
if [ ! -e "$GENERATOR/leekscript/.git" ]; then
	git clone "$LEEKSCRIPT_REPO" "$GENERATOR/leekscript"
fi
git -C "$GENERATOR/leekscript" remote set-url origin "$LEEKSCRIPT_REPO"
git -C "$GENERATOR/leekscript" fetch --depth=1 origin "$LEEKSCRIPT_COMMIT"
git -C "$GENERATOR/leekscript" checkout --force "$LEEKSCRIPT_COMMIT"

# --- GraalVM isolate ---------------------------------------------------
if [ ! -f "$GENERATOR/libs/$ISOLATE_JAR" ]; then
	log "Downloading the GraalVM isolate image (~127 MB)"
	mkdir -p "$GENERATOR/libs"
	curl -fsSL -o "$GENERATOR/libs/$ISOLATE_JAR" "$ISOLATE_URL"
fi

# --- Build -------------------------------------------------------------
if [ "$FORCE" = 1 ]; then
	log "Building generator.jar (forced)"
	(cd "$GENERATOR" && "$GRADLE" jar --no-daemon --rerun-tasks)
else
	log "Building generator.jar"
	(cd "$GENERATOR" && "$GRADLE" jar --no-daemon)
fi

log "Done: $GENERATOR/generator.jar"

# --- Expose the AI tree ------------------------------------------------
# The generator's NativeFileSystem roots every AI path at its own working
# directory and rejects anything escaping it, so tagadalive/ has to be
# reachable from inside. Paths are normalized textually before that check and
# reads follow the link, so a symlink is enough.
ln -sfn ../../tagadalive "$GENERATOR/tagadalive"
log "Linked tagadalive/ into the generator (AI path: tagadalive/main)"

# Must run from the generator directory: it resolves data/*.json (chips,
# weapons, summons, components) relative to the working directory.
(cd "$GENERATOR" && "$JAVA_HOME/bin/java" -jar generator.jar --analyze test/ai/basic.leek) >/dev/null \
	&& log "Smoke test passed (--analyze test/ai/basic.leek)"
