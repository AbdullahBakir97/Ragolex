# Deployment

Ragolex deploys itself: every change merged into `start-001` runs on staging, and every release tag runs on production, from images built once and published to the GitHub Container Registry. A deployment that does not come up healthy goes back to the one before, on its own.

```text
push to start-001 ──► build and publish images ──► staging
tag v1.4.0 ─────────► build and publish images ──► production (after approval, if required)
run by hand ────────► an earlier tag ────────────► staging or production (a rollback)
```

## Images

`.github/workflows/deploy.yml` builds the API and the web app and publishes them as `ghcr.io/<owner>/ragolex` and `ghcr.io/<owner>/ragolex-web` (the owner in lowercase), tagged with:

| Tag | When |
|---|---|
| `sha-1a2b3c4` | Every build: the commit, so any build can be deployed again |
| `edge` | Every push to `start-001` |
| `1.4.0` and `1.4` | A release tag `v1.4.0` |

Deployments use the `sha-` tag, which never moves.

## A server

Any Linux machine with Docker Engine and the compose plugin. Once:

1. Create a user for deployments, in the `docker` group, and give it the public half of a new SSH key:

   ```bash
   sudo useradd --create-home --groups docker deploy
   sudo -u deploy mkdir -m 700 /home/deploy/.ssh
   sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < deploy_key.pub
   ```

2. Create the deployment's folder with its settings, from [`.env.example`](../.env.example) (see [Configuration](configuration.md)):

   ```bash
   sudo -u deploy mkdir /home/deploy/ragolex
   sudo -u deploy cp .env.example /home/deploy/ragolex/.env   # then fill it in
   ```

3. Put what differs from the default stack in `compose.override.yaml` in the same folder, which Docker Compose reads with `compose.yaml`: for example the database password, ports bound to 127.0.0.1 behind a reverse proxy that terminates TLS, or `METRICS_TOKEN`. Deployments replace `compose.yaml` and `deploy.sh` with the release's, and never touch `.env` or `compose.override.yaml`.

## GitHub environments

In the repository's Settings > Environments, create `staging` and `production`, each with:

| Name | Kind | Value |
|---|---|---|
| `DEPLOY_HOST` | Variable | The server's address |
| `DEPLOY_USER` | Variable | `deploy` |
| `DEPLOY_PATH` | Variable | `/home/deploy/ragolex` |
| `DEPLOY_PORT` | Variable | The SSH port, if not 22 |
| `DEPLOY_KNOWN_HOSTS` | Variable | The server's host key line, from `ssh-keyscan -t ed25519 <host>`, checked against the server itself: deployments refuse any other host key |
| `APP_URL` | Variable | Where the web app answers, e.g. `https://staging.example.com`; checked after each deployment and linked from the run |
| `DEPLOY_SSH_KEY` | Secret | The private half of the deploy user's key |

Give `production` required reviewers, so a release waits for someone's approval, and limit it to tags matching `v*`. An environment without `DEPLOY_HOST` still gets its images built and published: nothing is deployed, and the run says so.

## A deployment

The `deploy` job copies `compose.yaml` and `tools/deploy.sh` to the server, signs the server in to the registry with the job's own token (which expires with the job), and runs:

```bash
RAGOLEX_IMAGES=ghcr.io/<owner> sh deploy.sh sha-1a2b3c4
```

`deploy.sh` pulls the two images, starts them with `docker compose up --wait`, and waits up to `DEPLOY_TIMEOUT` seconds (180) for both health checks to pass. The API applies the database migrations as it starts. When the new images do not become healthy, it prints `docker compose ps` and the last lines of the logs, starts the images that ran before, and fails the job. The tags that run now and ran before are in `.deploy/current` and `.deploy/previous`.

Then the job checks that `APP_URL/api/v1/health` answers. One deployment per environment runs at a time; the next waits for it.

## Releasing

```bash
git tag v1.4.0 && git push origin v1.4.0
```

## Rolling back

- From GitHub: Actions > Deploy > Run workflow, with the environment and an earlier tag, e.g. `sha-1a2b3c4` or `1.3.2`. Nothing is built; that tag is deployed.
- On the server, to the deployment before the current one:

  ```bash
  cd /home/deploy/ragolex && sh deploy.sh rollback
  sh deploy.sh status
  ```

A rollback runs the older code on the database as the newer release left it, since migrations are not undone. So each release's migrations must keep the schema usable by the release before: add tables, columns and indexes in one release, and remove or rename what the older code reads only in a later one. Back up the database before a release whose migrations change existing data.

## Running it by hand

Without GitHub, `deploy.sh` works the same from any shell on the server, with images from any registry the server can pull from:

```bash
RAGOLEX_IMAGES=registry.example.com/team sh deploy.sh 1.4.0
```
