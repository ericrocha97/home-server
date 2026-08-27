# Compose

Projetos host-native. Dados persistentes ficam em `/srv/home-server/data/<service>` fora do Git.

Validação estática:

```bash
docker compose --env-file compose/postgres/.env.example -f compose/postgres/compose.yaml config
docker compose --env-file compose/jenkins/.env.example -f compose/jenkins/compose.yaml config
docker compose --env-file compose/n8n/.env.example -f compose/n8n/compose.yaml config
docker compose --env-file compose/metabase/.env.example -f compose/metabase/compose.yaml config
```
