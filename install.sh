#!/bin/bash
set -euo pipefail
# keepassbox-managed-command

readonly command_marker='# keepassbox-managed-command'
readonly compose_marker='# Managed by the KeePassBox installer'
readonly installer_url='https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh'
temporary=''

log() {
	printf '[%s] %s\n' "$1" "$2" >&2
}

fail() {
	log ERROR "$1"
	exit 1
}

cleanup() {
	if [[ -n "$temporary" && -f "$temporary" ]]; then
		rm -- "$temporary"
	fi
}

trap cleanup EXIT
trap 'log ERROR "KeePassBox command failed at line $LINENO"' ERR

usage() {
	printf '%s\n' \
		'Usage: bash install.sh [--version latest|vX.Y.Z] [--port PORT]' \
		'       keepassbox start|stop|status|logs|token|config|uninstall' \
		'       keepassbox upgrade [--version latest|vX.Y.Z]'
}

validate_tag() {
	[[ "$1" == latest || "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
		fail 'Use latest or a version such as v0.1.1.'
}

validate_port() {
	if [[ ! "$1" =~ ^[1-9][0-9]{0,4}$ ]] || ((10#$1 > 65535)); then
		fail 'Port must be between 1 and 65535.'
	fi
}

require_docker() {
	command -v docker >/dev/null || fail 'Install Docker first.'
	docker compose version >/dev/null || fail 'Install Docker Compose first.'
}

set_paths() {
	config="${KEEPASSBOX_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/keepassbox}"
	bin_dir="${KEEPASSBOX_BIN_DIR:-$HOME/.local/bin}"
	[[ "$config" == /* && "$bin_dir" == /* ]] || fail 'Install paths must be absolute.'
	[[ ! -L "$config" && ! -L "$bin_dir" ]] || fail 'Install paths must be real directories.'
	launcher="$bin_dir/keepassbox"
	manifest="$config/compose.yaml"
	environment="$config/.env"
	access="$config/access.local.json"
	project_hash="$(printf '%s' "$config" | sha256sum)"
	project="keepassbox-${project_hash:0:12}"
}

verify_paths() {
	local path
	for path in "$manifest" "$environment" "$access" "$config/data"; do
		[[ ! -L "$path" ]] || fail "Refusing symlink at $path."
	done
	if [[ -e "$manifest" ]]; then
		grep -Fxq -- "$compose_marker" "$manifest" || fail "Unmanaged Compose file: $manifest"
	fi
	if [[ -e "$launcher" || -L "$launcher" ]]; then
		if [[ -L "$launcher" ]] || ! grep -Fxq -- "$command_marker" "$launcher"; then
			fail "Unmanaged command: $launcher"
		fi
	fi
}

setting() {
	local key="$1" fallback="$2" found=''
	if [[ -f "$environment" ]]; then
		found="$(awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); exit}' "$environment")"
	fi
	printf '%s\n' "${found:-$fallback}"
}

write_environment() {
	temporary="$(mktemp "$config/.env.XXXXXX")"
	printf 'KEEPASSBOX_IMAGE_TAG=%s\nKEEPASSBOX_PORT=%s\nKEEPASSBOX_UID=%s\nKEEPASSBOX_GID=%s\n' \
		"$1" "$2" "$(id -u)" "$(id -g)" >"$temporary"
	mv -T -- "$temporary" "$environment"
	temporary=''
}

write_compose() {
	temporary="$(mktemp "$config/.compose.XXXXXX")"
	printf '%s\n' "$compose_marker" >"$temporary"
	cat >>"$temporary" <<'YAML'
services:
  keepassbox:
    image: psyb0t/keepassbox:${KEEPASSBOX_IMAGE_TAG}
    user: "${KEEPASSBOX_UID}:${KEEPASSBOX_GID}"
    init: true
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    restart: unless-stopped
    mem_limit: 1g
    cpus: 2
    pids_limit: 128
    ports:
      - "127.0.0.1:${KEEPASSBOX_PORT}:8000"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
    volumes:
      - type: bind
        source: ./data
        target: /data
        bind:
          create_host_path: false
    secrets: [keepassbox_access]
    networks: [keepassbox]

secrets:
  keepassbox_access:
    file: ./access.local.json

networks:
  keepassbox:
YAML
	mv -T -- "$temporary" "$manifest"
	temporary=''
}

write_access() {
	local token
	command -v openssl >/dev/null || fail 'Install OpenSSL to generate the token.'
	token="$(openssl rand -hex 32)"
	[[ "$token" =~ ^[a-f0-9]{64}$ ]] || fail 'Token generation failed.'
	temporary="$(mktemp "$config/.access.XXXXXX")"
	cat >"$temporary" <<EOF
{
  "clients": [
    {
      "owner": "automation",
      "token": "$token",
      "scopes": ["vaults:create", "entries:read", "entries:write", "secrets:read", "vaults:admin"]
    }
  ]
}
EOF
	ln -- "$temporary" "$access" || fail 'Access file already exists. Existing tokens were preserved.'
	rm -- "$temporary"
	temporary=''
}

install_launcher() {
	temporary="$(mktemp "$bin_dir/.keepassbox.XXXXXX")"
	if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
		cp -- "${BASH_SOURCE[0]}" "$temporary"
	else
		curl -fsSL --proto '=https' "$installer_url" -o "$temporary"
	fi
	grep -Fxq -- "$command_marker" "$temporary" || fail 'Invalid KeePassBox command.'
	bash -n "$temporary" || fail 'Invalid KeePassBox command syntax.'
	chmod 0755 "$temporary"
	mv -T -- "$temporary" "$launcher"
	temporary=''
}

compose() {
	docker compose --project-directory "$config" --project-name "$project" \
		--env-file "$environment" -f "$manifest" "$@"
}

install_stack() {
	local tag port
	tag="$(setting KEEPASSBOX_IMAGE_TAG latest)"
	port="$(setting KEEPASSBOX_PORT 8000)"
	while (($#)); do
		case "$1" in
		--version)
			(($# > 1)) || fail 'Missing --version value.'
			tag="$2"
			shift 2
			;;
		--port)
			(($# > 1)) || fail 'Missing --port value.'
			port="$2"
			shift 2
			;;
		*) fail "Unknown option: $1" ;;
		esac
	done
	validate_tag "$tag"
	validate_port "$port"
	[[ "$(id -u)" != 0 ]] || fail 'Run the installer as your regular Docker user.'
	require_docker
	verify_paths
	umask 077
	install -d -m 0700 -- "$config" "$config/data"
	mkdir -p -- "$bin_dir"
	if [[ ! -f "$access" ]]; then
		write_access
	fi
	if [[ ! -f "$manifest" ]]; then
		write_compose
	fi
	write_environment "$tag" "$port"
	compose config --quiet || fail 'Compose configuration validation failed.'
	install_launcher
	log INFO "Installed $launcher"
	log INFO "Run keepassbox start. API: http://localhost:$port"
	log INFO "Read the token with keepassbox token."
}

upgrade_stack() {
	local tag port
	tag="$(setting KEEPASSBOX_IMAGE_TAG latest)"
	port="$(setting KEEPASSBOX_PORT 8000)"
	if (($#)); then
		[[ $# == 2 && "$1" == --version ]] || fail 'Usage: keepassbox upgrade [--version TAG]'
		tag="$2"
	fi
	validate_tag "$tag"
	validate_port "$port"
	KEEPASSBOX_IMAGE_TAG="$tag" compose pull keepassbox || fail 'Image pull failed.'
	KEEPASSBOX_IMAGE_TAG="$tag" compose up -d --wait keepassbox || fail 'Upgrade did not become healthy.'
	umask 077
	write_environment "$tag" "$port"
}

manage() {
	local action="$1"
	shift
	verify_paths
	[[ -f "$manifest" && -f "$environment" && -f "$access" ]] || fail 'Run the installer first.'
	if [[ "$action" == upgrade ]]; then
		require_docker
		upgrade_stack "$@"
		return
	fi
	(($# == 0)) || fail "Unexpected arguments for $action."
	case "$action" in
	token)
		awk -F '"' '$2 == "token" { print $4; exit }' "$access"
		return
		;;
	config)
		printf '%s\n' "$config"
		return
		;;
	esac
	require_docker
	case "$action" in
	start) compose up -d --wait keepassbox ;;
	stop) compose stop keepassbox ;;
	status) compose ps keepassbox ;;
	logs) compose logs -f keepassbox ;;
	uninstall)
		compose down || fail 'Could not remove the KeePassBox stack.'
		if [[ -f "$launcher" ]]; then
			rm -- "$launcher"
		fi
		log INFO "Vaults and access settings are still in $config"
		;;
	*) fail "Unknown command: $action" ;;
	esac
}

case "${1:-}" in
-h | --help | help) usage ;;
*)
	set_paths
	if [[ "${0##*/}" == keepassbox ]]; then
		(($# > 0)) || {
			usage
			exit 1
		}
		manage "$@"
	else
		install_stack "$@"
	fi
	;;
esac
