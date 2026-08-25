#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^(lab|prod)$ ]]; then
  printf 'usage: %s lab|prod\n' "$0" >&2
  exit 2
fi

environment="$1"
inventory="ansible/inventories/${environment}/hosts.yml"

if [[ ! -f "$inventory" ]]; then
  printf 'inventory not found: %s\n' "$inventory" >&2
  exit 1
fi

inventory_json="$(ansible-inventory -i "$inventory" --list)"
hostvars_json="$(jq -er '._meta.hostvars | to_entries[0].value' <<<"$inventory_json")"
server_ip="$(jq -er '(.server_lan_ip // .ansible_host)' <<<"$hostvars_json")"
base_domain="$(jq -er '.base_domain' <<<"$hostvars_json")"

for service in cockpit glance grafana jenkins metabase n8n portainer prometheus; do
  printf '%s %s.%s\n' "$server_ip" "$service" "$base_domain"
done
