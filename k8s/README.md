# Kubernetes platform

Slice 1 installs the single-node k3s platform and configures the bundled Traefik
instance in `kube-system`. Later slices add monitoring, Portainer and Glance.

Host-native Docker Compose services are routed directly by Traefik's file provider;
they are not represented by Kubernetes Services or EndpointSlices.
