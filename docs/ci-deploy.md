## CI-Driven Deployment Overview

This repository deploys production changes through a GitHub Actions workflow at `.github/workflows/deploy.yml`. The job builds container images for each Docker target, pushes them to GitHub Container Registry (GHCR), and then instructs the production host to pull and run the new images with the Compose `production` profile.

### Workflow Triggers
- Automatic: every push to the `main` branch.
- Manual: `workflow_dispatch` for on-demand rebuilds.

### Jobs
1. **build**
   - Strategy matrix over Docker targets (`api`, `archive_loader`, `backfill`, `load_admin_boundaries`).
   - Uses `docker/setup-buildx-action` and `docker/build-push-action` to build each target and push images tagged as `ghcr.io/<owner>/osm-meet-your-mappers:<target>`.
   - Requires `packages: write` permission so the default `GITHUB_TOKEN` can publish to GHCR.

2. **deploy**
   - Runs only for `main` pushes and depends on `build`.
   - Checks out the repo, then copies `scripts/deploy.sh` to `/tmp/scripts/deploy.sh` on the production host via `appleboy/scp-action` (keeps the working tree clean for `git pull`).
   - Executes the script remotely with `appleboy/ssh-action`. The script performs a fast-forward pull of the deployment branch and issues `docker compose --profile production pull && up -d`.
   - Targets the GitHub Actions `production` environment (use this to require approvals if desired).

### Required GitHub Secrets / Variables
- `DEPLOY_HOST`: SSH hostname or IP of the production server.
- `DEPLOY_USER`: SSH user with permission to run `docker compose` (e.g., the dedicated `deploy` account).
- `DEPLOY_DIR`: Absolute path to the repository clone on the host.
- `DEPLOY_SSH_KEY`: Private key (OpenSSH format) that authenticates as `DEPLOY_USER`. The matching public key must be listed in `/home/<deploy_user>/.ssh/authorized_keys`.
- Optional repository variables: you can override `REGISTRY` or `IMAGE_PREFIX` if publishing somewhere other than GHCR.

### Production Host Preparation
1. **Create a restricted deploy user**
   ```bash
   adduser deploy --disabled-password --gecos ""
   usermod -aG docker deploy
   install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
   ```
2. **Authorize the CI key**
   - Locally: `ssh-keygen -t ed25519 -f ~/.ssh/id_ci-deploy -C "gha@osm-meet-your-mappers"`.
   - Upload the public key (`id_ci-deploy.pub`) to `/home/deploy/.ssh/authorized_keys`, `chown deploy:deploy`, and `chmod 600`.
   - Store the matching private key in the `DEPLOY_SSH_KEY` repository secret.
3. **Clone the repository for the deploy user**
   ```bash
   sudo mkdir -p /srv/osm-meet-your-mappers
   sudo chown deploy:deploy /srv/osm-meet-your-mappers
   sudo -u deploy ssh-keygen -t ed25519 -f /home/deploy/.ssh/id_github -C "deploy@mappers.osm.lol"
   # Add /home/deploy/.ssh/id_github.pub as a read-only Deploy Key on GitHub
   sudo -u deploy tee -a /home/deploy/.ssh/config <<'EOF'
   Host github.com
     IdentityFile /home/deploy/.ssh/id_github
     IdentitiesOnly yes
   EOF
   sudo -u deploy git clone git@github.com:mvexel/osm-meet-your-mappers.git /srv/osm-meet-your-mappers
   ```
4. **Configure environment**
   - Copy `.env.example` to `.env`, fill in required settings, and add `REGISTRY_IMAGE_PREFIX=ghcr.io/<owner>/osm-meet-your-mappers`.
   - Ensure `docker compose --profile production ps` runs without sudo for `deploy`.

### Deploy Script (`scripts/deploy.sh`)
The script expects two environment variables:
- `DEPLOY_DIR`: directory containing the Git checkout on the host.
- `DEPLOY_BRANCH` (optional, defaults to `main`): branch to deploy.

It removes any untracked `scripts/deploy.sh` dropped by CI, performs a fast-forward-only update of the deployment branch, then runs:
```bash
docker compose --profile production pull
docker compose --profile production up -d
```

### Day-to-Day Operation
- Push to `main`: CI builds fresh images and redeploys automatically.
- To force a redeploy without new commits, use the “Run workflow” button under GitHub Actions.
- Use GitHub environment protection rules on `production` to gate deploys if required.
