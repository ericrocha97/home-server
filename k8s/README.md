# Kubernetes platform

Slice 1 installs the single-node k3s platform and configures the bundled Traefik
instance in `kube-system`. Later slices add monitoring, Portainer and Glance.

Host-native Docker Compose services are routed directly by Traefik's file provider;
they are not represented by Kubernetes Services or EndpointSlices.

Slice 2 adds 3 backends Docker via file provider — `jenkins` (`18080`), `n8n` (`15678`) and `metabase` (`13001`) — apontando para `server_lan_ip:porta` com healthCheck; `cockpit` permanece como backend original. Nenhum Service/EndpointSlice é criado para esses 3 serviços.
